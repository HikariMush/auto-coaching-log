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
CHUNK_LENGTH = 900  # 15分 (Groq制限回避)

# --- Setup ---
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
    creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=['https://www.googleapis.com/auth/drive'])
    drive_service = build('drive', 'v3', credentials=creds)
    INBOX_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
except Exception as e:
    print(f"❌ Init Error: {e}"); sys.exit(1)

def sanitize_id(raw_id):
    if not raw_id: return None
    match = re.search(r'([a-fA-F0-9]{32})', str(raw_id).replace("-", ""))
    return match.group(1) if match else None

# --- Layer 1: FFmpeg Audio Pipeline ---
def mix_audio_ffmpeg(file_paths):
    print(f"🎛️ Mixing/Converting {len(file_paths)} tracks...", flush=True)
    output_path = os.path.abspath(os.path.join(TEMP_DIR, "mixed_full.mp3"))
    inputs = []
    for f in file_paths: inputs.extend(['-i', f])
    
    # 複数FLAC等を統合し、Groqが処理可能なMP3に強制エンコード
    filter_part = ['-filter_complex', f'amix=inputs={len(file_paths)}:duration=longest'] if len(file_paths) > 1 else []
    cmd = ['ffmpeg', '-y'] + inputs + filter_part + ['-ac', '1', '-b:a', '64k', output_path]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_path

def split_audio_ffmpeg(input_path):
    print("🔪 Splitting into MP3 chunks...", flush=True)
    output_pattern = os.path.join(TEMP_DIR, "chunk_%03d.mp3")
    cmd = ['ffmpeg', '-y', '-i', input_path, '-f', 'segment', '-segment_time', str(CHUNK_LENGTH), '-ac', '1', '-b:a', '64k', output_pattern]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return sorted(glob.glob(os.path.join(TEMP_DIR, "chunk_*.mp3")))

# --- Layer 2: Groq Transcription ---
def transcribe_with_groq(chunk_paths):
    full_transcript = ""
    for chunk in chunk_paths:
        if not chunk.endswith(".mp3"): continue
        print(f"🚀 Groq Transcribing: {os.path.basename(chunk)}...", flush=True)
        with open(chunk, "rb") as f:
            res = groq_client.audio.transcriptions.create(
                file=(os.path.basename(chunk), f),
                model="whisper-large-v3", language="ja", response_format="text"
            )
            full_transcript += res + "\n"
    return full_transcript

# --- Layer 3: Gemini Analysis (SZ 最重要要件を完全復元) ---
def analyze_text_with_gemini(transcript_text):
    print("🧠 Analyzing text with Gemini (Deep Analysis Mode)...", flush=True)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = f"""
    あなたは**トップ・スマブラアナリスト**です。
    コーチ(Hikari)とクライアントの対話ログ（テキスト）を分析し、以下の形式で出力してください。

    ---
    **[RAW_TRANSCRIPTION_START]**
    詳細な時系列ログを作成せよ。フィラーを削り、誰が何について話したか正確に記述すること。
    **[RAW_TRANSCRIPTION_END]**
    ---
    **[DETAILED_REPORT_START]**
    扱われた主要トピックごとに、以下の5要素を用いて詳細に分解せよ。
    * **現状** (Current Status)
    * **課題** (Problem)
    * **原因** (Root Cause)
    * **改善案** (Proposed Solution)
    * **やること** (Next Action)
    **[DETAILED_REPORT_END]**
    ---
    **[JSON_START]**
    {{
      "student_name": "生徒名（不明ならUnknown）",
      "date": "YYYY-MM-DD",
      "next_action": "最も重要な次回のアクション（1行）"
    }}
    **[JSON_END]**

    【文字起こしデータ】
    {transcript_text[:900000]}
    """
    
    response = model.generate_content(prompt)
    text = response.text.strip()
    
    # パース処理
    def extract(tag_start, tag_end, src):
        match = re.search(f'{re.escape(tag_start)}(.*?){re.escape(tag_end)}', src, re.DOTALL)
        return match.group(1).strip() if match else ""

    raw_log = extract("[RAW_TRANSCRIPTION_START]", "[RAW_TRANSCRIPTION_END]", text)
    report = extract("[DETAILED_REPORT_START]", "[DETAILED_REPORT_END]", text)
    json_str = extract("[JSON_START]", "[JSON_END]", text)
    
    try:
        data = json.loads(json_str)
    except:
        data = {{"student_name": "Unknown", "date": datetime.now().strftime('%Y-%m-%d'), "next_action": "解析失敗"}}
    
    return data, report, raw_log

# --- Layer 4: Notion & Drive Integration ---
def notion_query_student(student_name):
    db_id = sanitize_id(FINAL_CONTROL_DB_ID)
    if not db_id: return None, student_name
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    res = requests.post(url, headers=HEADERS, json={{"filter": {{"property": "Name", "title": {{"contains": student_name}}}}}})
    res_data = res.json()
    if res_data.get("results"):
        row = res_data["results"][0]
        name = row["properties"]["Name"]["title"][0]["plain_text"]
        target = row["properties"]["TargetID"]["rich_text"]
        return (sanitize_id(target[0]["plain_text"]), name) if target else (None, name)
    return None, student_name

def notion_create_page_heavy(db_id, props, all_children):
    res = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json={{"parent": {{"database_id": db_id}}, "properties": props, "children": all_children[:100]}})
    page_data = res.json()
    page_id = page_data.get('id')
    if page_id and len(all_children) > 100:
        for i in range(100, len(all_children), 100):
            requests.patch(f"https://api.notion.com/v1/blocks/{{page_id}}/children", headers=HEADERS, json={{"children": all_children[i:i+100]}})
    return page_id

def cleanup_drive_file(file_id, rename_to):
    # フォルダ検索/作成とリネーム移動
    f_q = f"name='processed_coaching_logs' and '{{INBOX_FOLDER_ID}}' in parents"
    folders = drive_service.files().list(q=f_q).execute().get('files', [])
    target_f_id = folders[0]['id'] if folders else drive_service.files().create(body={{'name': 'processed_coaching_logs', 'mimeType': 'application/vnd.google-apps.folder', 'parents': [INBOX_FOLDER_ID]}}, fields='id').execute().get('id')
    
    prev_parents = ",".join(drive_service.files().get(fileId=file_id, fields='parents').execute().get('parents', []))
    drive_service.files().update(fileId=file_id, addParents=target_f_id, removeParents=prev_parents, body={{'name': rename_to}}).execute()
    print(f"✅ Drive updated: {{rename_to}}")

# --- Main Logic ---
def main():
    print("--- SZ AUTO LOGGER ULTIMATE (v74.0) ---", flush=True)
    results = drive_service.files().list(q=f"'{{INBOX_FOLDER_ID}}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'").execute()
    files = results.get('files', [])
    
    for file in files:
        try:
            print(f"\n📂 Processing: {{file['name']}}")
            fpath = os.path.join(TEMP_DIR, file['name'])
            with open(fpath, "wb") as f:
                MediaIoBaseDownload(f, drive_service.files().get_media(fileId=file['id'])).next_chunk()
            
            # ソース抽出
            audio_sources = []
            if file['name'].endswith('.zip'):
                with zipfile.ZipFile(fpath, 'r') as z:
                    z.extractall(TEMP_DIR)
                    for root, _, fs in os.walk(TEMP_DIR):
                        for af in fs:
                            if af.lower().endswith(('.flac', '.mp3', '.m4a', '.wav')) and 'mixed' not in af and 'chunk' not in af:
                                audio_sources.append(os.path.join(root, af))
            else:
                audio_sources.append(fpath)

            if not audio_sources: continue
            
            # Pipeline
            mixed_mp3 = mix_audio_ffmpeg(audio_sources)
            chunk_list = split_audio_ffmpeg(mixed_mp3)
            full_text_raw = transcribe_with_groq(chunk_list)
            
            # Analysis
            meta, report, time_log = analyze_text_with_gemini(full_text_raw)
            
            # Target Resolve
            dest_id, official_name = notion_query_student(meta.get('student_name', 'Unknown'))
            if not dest_id: dest_id = FINAL_FALLBACK_DB_ID
            
            # Notion Write
            props = {
                "名前": {{"title": [{{"text": {{"content": f"{{meta['date']}} {{official_name}} ログ"}}}}]}}, 
                "日付": {{"date": {{"start": meta['date']}}}}
            }
            # コンテンツ構築 (分析レポート + 時系列ログ)
            content_text = f"### 📊 詳細分析レポート\n\n{{report}}\n\n---\n### 📝 時系列ログ\n\n{{time_log}}"
            blocks = [{{"object": "block", "type": "paragraph", "paragraph": {{"rich_text": [{{"text": {{"content": line[:1900]}}}}]}}}} for line in content_text.split('\n') if line.strip()]
            
            notion_create_page_heavy(sanitize_id(dest_id), props, blocks)
            
            # Drive Cleanup
            ext = os.path.splitext(file['name'])[1] or ".zip"
            new_name = f"{{meta.get('date', 'date-err')}}_{{official_name}}{{ext}}"
            cleanup_drive_file(file['id'], rename_to=new_name)

        except Exception as e:
            print(f"❌ Error: {{e}}")
            import traceback; traceback.print_exc()
        finally:
            if os.path.exists(TEMP_DIR):
                shutil.rmtree(TEMP_DIR); os.makedirs(TEMP_DIR)

if __name__ == "__main__":
    main()
