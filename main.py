import os
import sys
import time
import json
import shutil
import subprocess
import glob
import re
from datetime import datetime

# --- Libraries ---
import requests
import google.generativeai as genai
from groq import Groq
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import zipfile

# --- Configuration ---
FINAL_CONTROL_DB_ID = "2b71bc8521e380868094ec506b41f664"
FINAL_FALLBACK_DB_ID = "2b71bc8521e38018a5c3c4b0c6b6627c"
TEMP_DIR = "temp_workspace"
CHUNK_LENGTH = 900  # 15分

# --- Setup & Init ---
def setup_env():
    if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR)
    if os.getenv("GCP_SA_KEY"):
        with open("service_account.json", "w") as f:
            f.write(os.getenv("GCP_SA_KEY"))

setup_env()

try:
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    NOTION_TOKEN = os.getenv("NOTION_TOKEN")
    HEADERS = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)
    INBOX_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
except Exception as e:
    print(f"❌ Init Error: {e}")
    sys.exit(1)

def sanitize_id(raw_id):
    if not raw_id: return None
    match = re.search(r'([a-fA-F0-9]{32})', str(raw_id).replace("-", ""))
    return match.group(1) if match else None

# --- Audio Pipeline ---
def run_ffmpeg(cmd):
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"⚠️ FFmpeg Error: {e}")
        raise

def mix_audio_ffmpeg(file_paths):
    print(f"🎛️ Mixing {len(file_paths)} tracks...", flush=True)
    output_path = os.path.join(TEMP_DIR, "mixed_full.mp3")
    inputs = []
    for f in file_paths: inputs.extend(['-i', f])
    if len(file_paths) > 1:
        filter_cmd = f"amix=inputs={len(file_paths)}:duration=longest"
        cmd = ['ffmpeg', '-y'] + inputs + ['-filter_complex', filter_cmd, '-ac', '1', '-b:a', '64k', output_path]
    else:
        cmd = ['ffmpeg', '-y', '-i', file_paths[0], '-ac', '1', '-b:a', '64k', output_path]
    run_ffmpeg(cmd)
    return output_path

def split_audio_ffmpeg(input_path):
    output_pattern = os.path.join(TEMP_DIR, "chunk_%03d.mp3")
    cmd = ['ffmpeg', '-y', '-i', input_path, '-f', 'segment', '-segment_time', str(CHUNK_LENGTH), '-c', 'copy', output_pattern]
    run_ffmpeg(cmd)
    return sorted(glob.glob(os.path.join(TEMP_DIR, "chunk_*.mp3")))

# --- Transcription ---
def transcribe_with_groq(chunk_paths):
    full_transcript = ""
    for i, chunk in enumerate(chunk_paths):
        print(f"🚀 Groq Chunk {i+1}/{len(chunk_paths)}...", flush=True)
        with open(chunk, "rb") as file:
            transcription = groq_client.audio.transcriptions.create(
                file=(chunk, os.path.basename(chunk)),
                model="whisper-large-v3", language="ja", response_format="text"
            )
            full_transcript += transcription + "\n"
    return full_transcript

# --- Analysis ---
def analyze_text_with_gemini(transcript_text):
    print("🧠 Analyzing text with Gemini...", flush=True)
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"""
    あなたはスマブラコーチアシスタントです。対話ログを分析し以下を出力せよ。
    [DETAILED_REPORT_START] (現状・課題・改善案・やること) [DETAILED_REPORT_END]
    [JSON_START] {{"student_name": "名前", "date": "YYYY-MM-DD", "next_action": "次やること"}} [JSON_END]
    テキスト: {transcript_text[:900000]}
    """
    response = model.generate_content(prompt)
    text = response.text.strip()
    report = re.search(r'\[DETAILED_REPORT_START\](.*?)\[DETAILED_REPORT_END\]', text, re.DOTALL)
    report_text = report.group(1).strip() if report else "分析失敗"
    js = re.search(r'\[JSON_START\](.*?)\[JSON_END\]', text, re.DOTALL)
    data = json.loads(js.group(1)) if js else {"student_name": "Unknown", "date": datetime.now().strftime('%Y-%m-%d'), "next_action": "None"}
    return data, report_text

# --- Notion Integration ---
def notion_query_student(student_name):
    db_id = sanitize_id(FINAL_CONTROL_DB_ID)
    if not db_id: return None, student_name
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    res = requests.post(url, headers=HEADERS, json={"filter": {"property": "Name", "title": {"contains": student_name}}})
    data = res.json()
    if data.get("results"):
        row = data["results"][0]
        name = row["properties"]["Name"]["title"][0]["plain_text"]
        target = row["properties"]["TargetID"]["rich_text"]
        return (sanitize_id(target[0]["plain_text"]), name) if target else (None, name)
    return None, student_name

def notion_create_page_heavy(db_id, props, all_children):
    res = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json={"parent": {"database_id": db_id}, "properties": props, "children": all_children[:100]})
    page_id = res.json().get('id')
    if page_id and len(all_children) > 100:
        for i in range(100, len(all_children), 100):
            requests.patch(f"https://api.notion.com/v1/blocks/{page_id}/children", headers=HEADERS, json={"children": all_children[i:i+100]})

# --- Drive Integration (リネーム機能強化) ---
def cleanup_drive_file(file_id, rename_to=None):
    folder_name = "processed_coaching_logs"
    q = f"name='{folder_name}' and '{INBOX_FOLDER_ID}' in parents and trashed=false"
    folders = drive_service.files().list(q=q).execute().get('files', [])
    target_folder_id = folders[0]['id'] if folders else drive_service.files().create(body={'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [INBOX_FOLDER_ID]}, fields='id').execute().get('id')
    
    file = drive_service.files().get(fileId=file_id, fields='parents').execute()
    prev_parents = ",".join(file.get('parents', []))
    body = {'name': rename_to} if rename_to else {}
    drive_service.files().update(fileId=file_id, addParents=target_folder_id, removeParents=prev_parents, body=body).execute()
    print(f"➡️ File moved and renamed to: {rename_to}", flush=True)

# --- Main Logic ---
def main():
    results = drive_service.files().list(q=f"'{INBOX_FOLDER_ID}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'").execute()
    files = results.get('files', [])
    if not files:
        print("ℹ️ No files to process.")
        return

    for file in files:
        try:
            print(f"\n📂 Processing: {file['name']}")
            request = drive_service.files().get_media(fileId=file['id'])
            fpath = os.path.join(TEMP_DIR, file['name'])
            with open(fpath, "wb") as f:
                downloader = MediaIoBaseDownload(f, request)
                done = False
                while not done: _, done = downloader.next_chunk()
            
            audios = []
            if file['name'].endswith('.zip'):
                with zipfile.ZipFile(fpath, 'r') as z:
                    z.extractall(TEMP_DIR)
                    for root, _, fs in os.walk(TEMP_DIR):
                        for af in fs:
                            if af.lower().endswith(('.flac', '.mp3', '.m4a', '.wav')): 
                                audios.append(os.path.join(root, af))
            else: audios.append(fpath)

            if not audios: continue
            
            # Pipeline
            mixed = mix_audio_ffmpeg(audios)
            chunks = split_audio_ffmpeg(mixed)
            full_text = transcribe_with_groq(chunks)
            meta, report = analyze_text_with_gemini(full_text)
            
            # Target ID & Name Resolution
            dest_id, official_name = notion_query_student(meta['student_name'])
            if not dest_id: 
                dest_id = FINAL_FALLBACK_DB_ID
                print(f"⚠️ Student not found. Using Fallback.")
            
            # Notion Write
            props = {
                "名前": {"title": [{"text": {"content": f"{meta['date']} {official_name} ログ"}}]}, 
                "日付": {"date": {"start": meta['date']}}
            }
            blocks = [{"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": line[:2000]}}]}} for line in (report + "\n" + full_text).split('\n') if line.strip()]
            notion_create_page_heavy(sanitize_id(dest_id), props, blocks)
            
            # Drive リネーム & 移動
            ext = os.path.splitext(file['name'])[1] or ".zip"
            new_name = f"{meta['date']}_{official_name}{ext}"
            cleanup_drive_file(file['id'], rename_to=new_name)
            
        except Exception as e:
            print(f"❌ Error on {file['name']}: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if os.path.exists(TEMP_DIR): 
                shutil.rmtree(TEMP_DIR)
                os.makedirs(TEMP_DIR)

if __name__ == "__main__":
    main()
