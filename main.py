import sys
import subprocess
import os
import time
import json
import shutil
import glob
import re
import traceback
from datetime import datetime

# --- 0. SDK & Tools ---
def install_package(package):
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
    except: pass

install_package("google-genai")
install_package("groq")
install_package("patool")

# --- Libraries ---
import requests
from google import genai 
from google.genai import types
from groq import Groq
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
import patoolib

# --- Configuration ---
FINAL_CONTROL_DB_ID = "2b71bc8521e380868094ec506b41f664"
FINAL_FALLBACK_DB_ID = "2e01bc8521e380ffaf28c2ab9376b00d"
TEMP_DIR = "temp_workspace"
CHUNK_LENGTH = 900  # 15 min

# Global Variables
RESOLVED_MODEL_ID = None
BOT_EMAIL = None # ★追加

# --- Helper: Verbose Error Printer ---
def log_error(context, error_obj):
    print(f"\n❌ [ERROR] {context}", flush=True)
    print(f"   Details: {str(error_obj)}", flush=True)
    print("-" * 30, flush=True)

# --- 1. Initialization (Setup) ---
def setup_env():
    global RESOLVED_MODEL_ID, BOT_EMAIL
    if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR)
    
    sa_key = os.getenv("GCP_SA_KEY")
    if sa_key:
        with open("service_account.json", "w") as f:
            f.write(sa_key)
        
        # ★【新機能】自己紹介機能
        try:
            key_data = json.loads(sa_key)
            BOT_EMAIL = key_data.get("client_email", "Unknown")
            print(f"\n==========================================")
            print(f"🤖 BOT EMAIL: {BOT_EMAIL}")
            print(f"👉 Please add this email as 'Editor' to your Drive Folder!")
            print(f"==========================================\n", flush=True)
        except:
            print("⚠️ Could not parse Service Account Email.")
    else:
        print("❌ ENV Error: GCP_SA_KEY is missing.")
        sys.exit(1)

setup_env()

try:
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    
    print("💎 Detecting Best Available Model...", flush=True)
    PRIORITY_TARGETS = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-2.0-flash-lite"]
    for target in PRIORITY_TARGETS:
        print(f"👉 Testing: [{target}]...", flush=True)
        try:
            gemini_client.models.generate_content(model=target, contents="Hello")
            print(f"✅ SUCCESS! Using Model: [{target}]", flush=True)
            RESOLVED_MODEL_ID = target
            break
        except Exception: continue
                
    if not RESOLVED_MODEL_ID:
        RESOLVED_MODEL_ID = "gemini-2.0-flash-lite"
        print(f"⚠️ Fallback to: {RESOLVED_MODEL_ID}")

    NOTION_TOKEN = os.getenv("NOTION_TOKEN")
    if not NOTION_TOKEN: raise Exception("NOTION_TOKEN missing")
    
    HEADERS = {"Authorization": f"Bearer {NOTION_TOKEN}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}
    creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=['https://www.googleapis.com/auth/drive'])
    drive_service = build('drive', 'v3', credentials=creds)
    INBOX_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
    if not INBOX_FOLDER_ID: raise Exception("DRIVE_FOLDER_ID missing")
    
except Exception as e:
    log_error("Initialization Failed", e)
    sys.exit(1)

def sanitize_id(raw_id):
    if not raw_id: return None
    match = re.search(r'([a-fA-F0-9]{32})', str(raw_id).replace("-", ""))
    return match.group(1) if match else None

# --- 2. Audio Pipeline ---

def run_ffmpeg_command(cmd, task_name):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"\n❌ FFmpeg Error during '{task_name}':\n{e.stderr}", flush=True)
        raise e

def mix_audio_ffmpeg(file_paths):
    print(f"🎛️ Mixing {len(file_paths)} tracks...", flush=True)
    output_path = os.path.abspath(os.path.join(TEMP_DIR, "final_mix.mp3"))
    inputs = []
    for f in file_paths: inputs.extend(['-i', f])
    filter_part = ['-filter_complex', f'amix=inputs={len(file_paths)}:duration=longest'] if len(file_paths) > 1 else []
    cmd = ['ffmpeg', '-y'] + inputs + filter_part + ['-ac', '1', '-b:a', '64k', output_path]
    run_ffmpeg_command(cmd, "Mixing Audio")
    return output_path

def split_audio_ffmpeg(input_path):
    print("🔪 Splitting...", flush=True)
    output_pattern = os.path.join(TEMP_DIR, "chunk_%03d.mp3")
    cmd = ['ffmpeg', '-y', '-i', input_path, '-f', 'segment', '-segment_time', str(CHUNK_LENGTH), '-ac', '1', '-b:a', '64k', output_pattern]
    run_ffmpeg_command(cmd, "Splitting Audio")
    return sorted(glob.glob(os.path.join(TEMP_DIR, "chunk_*.mp3")))

def transcribe_with_groq(chunk_paths):
    full_transcript = ""
    for chunk in chunk_paths:
        if not chunk.endswith(".mp3"): continue
        print(f"🚀 Groq Transcribing: {os.path.basename(chunk)}", flush=True)
        max_retries = 50
        for attempt in range(max_retries):
            try:
                with open(chunk, "rb") as file:
                    res = groq_client.audio.transcriptions.create(
                        file=(os.path.basename(chunk), file),
                        model="whisper-large-v3", language="ja", response_format="text"
                    )
                full_transcript += res + "\n"
                break 
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "rate limit" in err_str:
                    wait = 70
                    print(f"⏳ Groq Limit. Waiting {wait}s... ({attempt+1}/{max_retries})", flush=True)
                    time.sleep(wait)
                else: 
                    log_error("Groq Transcription Failed", e)
                    raise e
        else: raise Exception("❌ Groq Rate Limit persists. Aborting.")
    return full_transcript

# --- 3. Intelligence Analysis ---

def analyze_text_with_gemini(transcript_text):
    print(f"🧠 Gemini Analyzing using [{RESOLVED_MODEL_ID}]...", flush=True)
    prompt = f"""
    あなたは世界最高峰のスマブラ（Super Smash Bros.）アナリストであり、論理的かつ冷徹なコーチング記録官です。
    渡された対話ログを精読し、以下の3つのセクションを厳密なフォーマットで出力してください。

    **【Section 1: トピック別・詳細分析レポート】**
    会話の中で扱われた「主要なトピック（例：崖上がり狩り、ライン管理、復帰阻止）」をすべて抽出し、
    **トピックごとに**以下の5要素を埋めて記述すること。

    * **① 現状 (Status):** プレイヤーが現在行っている行動、癖、認識している状況。
    * **② 課題 (Problem):** その行動によって発生している具体的なデメリット。
    * **③ 原因 (Root Cause):** なぜその課題が発生しているのか（知識不足、操作ミス、判断ミス等）。
    * **④ 改善案 (Solution):** 具体的にどう行動を変えるべきか（技の変更、タイミング、意識配分）。
    * **⑤ やること (Next Action):** 次回のプレイで即座に実行すべき、具体的アクション（1行）。

    **【Section 2: 時系列ログ】**
    セッションの流れを時系列（Time-Series）で詳細に箇条書きにすること。

    **【Section 3: メタデータJSON】**
    以下のJSONのみを出力すること。
    {{
      "student_name": "生徒の名前（不明ならUnknown）",
      "date": "YYYY-MM-DD",
      "next_action": "最も優先度の高いアクション1つ"
    }}

    ---
    **[DETAILED_REPORT_START]**
    (ここにSection 1を出力)
    **[DETAILED_REPORT_END]**

    **[RAW_LOG_START]**
    (ここにSection 2を出力)
    **[RAW_LOG_END]**

    **[JSON_START]**
    (ここにSection 3を出力)
    **[JSON_END]**
    ---

    【入力テキスト】
    {transcript_text}
    """
    max_retries = 10
    for attempt in range(max_retries):
        try:
            response = gemini_client.models.generate_content(model=RESOLVED_MODEL_ID, contents=prompt)
            text = response.text.strip()
            break 
        except Exception as e:
            err_str = str(e).lower()
            if "429" in err_str or "quota" in err_str:
                wait = 60 * (attempt + 1)
                print(f"⏳ Gemini Busy. Waiting {wait}s...", flush=True)
                time.sleep(wait)
            else:
                log_error("Gemini Analysis Failed", e)
                return {"student_name": "AnalysisError", "date": datetime.now().strftime('%Y-%m-%d')}, f"Analysis Error: {e}", transcript_text[:2000]
    else: return {"student_name": "QuotaError", "date": datetime.now().strftime('%Y-%m-%d')}, "Quota Limit Exceeded", transcript_text[:2000]
    
    def extract(s, e, src):
        m = re.search(f'{re.escape(s)}(.*?){re.escape(e)}', src, re.DOTALL)
        return m.group(1).strip() if m else ""

    report = extract("[DETAILED_REPORT_START]", "[DETAILED_REPORT_END]", text)
    time_log = extract("[RAW_LOG_START]", "[RAW_LOG_END]", text)
    json_str = extract("[JSON_START]", "[JSON_END]", text)
    try: data = json.loads(json_str)
    except: data = {"student_name": "Unknown", "date": datetime.now().strftime('%Y-%m-%d'), "next_action": "Check Logs"}
    return data, report, time_log

# --- 4. Asset Management ---

def notion_query_student(name):
    db_id = sanitize_id(FINAL_CONTROL_DB_ID)
    if not db_id: return None, name
    try:
        res = requests.post(f"https://api.notion.com/v1/databases/{db_id}/query", headers=HEADERS, json={"filter": {"property": "Name", "title": {"contains": name}}})
        if res.status_code == 200 and res.json().get("results"):
            row = res.json()["results"][0]
            n = row["properties"]["Name"]["title"][0]["plain_text"]
            tid = row["properties"]["TargetID"]["rich_text"]
            return (sanitize_id(tid[0]["plain_text"]), n) if tid else (None, n)
    except Exception: pass
    return None, name

def notion_create_page_heavy(db_id, props, children):
    print(f"📤 Posting to Notion DB: {db_id}...", flush=True)
    res = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json={"parent": {"database_id": db_id}, "properties": props, "children": children[:100]})
    if res.status_code != 200:
        print(f"⚠️ Initial Post Failed ({res.status_code}). Retrying with SAFE MODE...", flush=True)
        safe_props = {}
        for key, val in props.items():
            if "title" in val: safe_props[key] = val; break
        if not safe_props:
             content_text = props.get("名前", {}).get("title", [{}])[0].get("text", {}).get("content", "Log")
             safe_props = {"Name": {"title": [{"text": {"content": content_text}}]}}
        date_info = props.get("日付", {}).get("date", {}).get("start", "Unknown Date")
        error_note = {"object": "block", "type": "callout", "callout": {"rich_text": [{"text": {"content": f"⚠️ Date Property Missing. Date: {date_info}"}}]}}
        children.insert(0, error_note)
        res = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json={"parent": {"database_id": db_id}, "properties": safe_props, "children": children[:100]})
        if res.status_code != 200:
            print(f"❌ NOTION SAFE MODE FAILED: {res.status_code}\n{res.text}", flush=True)
            return
    response_data = res.json()
    pid = response_data.get('id')
    print(f"🔗 Notion Page Created: {response_data.get('url')}", flush=True)
    if pid and len(children) > 100:
        for i in range(100, len(children), 100):
            requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS, json={"children": children[i:i+100]})

def ensure_processed_folder():
    try:
        q = f"name='processed_coaching_logs' and '{INBOX_FOLDER_ID}' in parents"
        folders = drive_service.files().list(q=q).execute().get('files', [])
        if folders: return folders[0]['id']
        folder = drive_service.files().create(body={'name': 'processed_coaching_logs', 'mimeType': 'application/vnd.google-apps.folder', 'parents': [INBOX_FOLDER_ID]}, fields='id').execute()
        return folder.get('id')
    except Exception as e:
        log_error("Failed to Get/Create Processed Folder", e)
        return INBOX_FOLDER_ID

def upload_mix_to_drive(local_path, folder_id, rename_to):
    print(f"📤 Uploading MP3: {rename_to}...", flush=True)
    try:
        media = MediaFileUpload(local_path, mimetype='audio/mpeg', resumable=True, chunksize=100*1024*1024)
        drive_service.files().create(body={'name': rename_to, 'parents': [folder_id]}, media_body=media, fields='id').execute()
        print("✅ Upload Complete.", flush=True)
    except Exception as e:
        log_error("Audio Upload Failed", e)

def move_original_file(file_id, folder_id):
    if folder_id == INBOX_FOLDER_ID:
        print("⚠️ Skipping Move: Destination is Inbox.", flush=True)
        return
    try:
        prev_parents = drive_service.files().get(fileId=file_id, fields='parents').execute().get('parents', [])
        prev_str = ",".join(prev_parents)
        drive_service.files().update(fileId=file_id, addParents=folder_id, removeParents=prev_str).execute()
        print(f"📦 Archived original file to folder [{folder_id}].", flush=True)
    except Exception as e:
        log_error(f"Move Original File Failed (ID: {file_id})", e)
        print(f"👉 TIP: Add this email to folder permissions: {BOT_EMAIL}", flush=True)

# --- Main ---
def main():
    print("--- SZ AUTO LOGGER ULTIMATE (v101.0 - Identity Reveal) ---", flush=True)
    try:
        files = drive_service.files().list(q=f"'{INBOX_FOLDER_ID}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'").execute().get('files', [])
    except Exception: return

    if not files: print("ℹ️ No files."); return

    for file in files:
        try:
            print(f"\n📂 Processing: {file['name']}")
            fpath = os.path.join(TEMP_DIR, file['name'])
            
            max_dl_retries = 3
            for dl_attempt in range(max_dl_retries):
                try:
                    with open(fpath, "wb") as f:
                        request = drive_service.files().get_media(fileId=file['id'])
                        downloader = MediaIoBaseDownload(f, request, chunksize=100*1024*1024)
                        done = False
                        while done is False:
                            status, done = downloader.next_chunk()
                            print(f"   ⬇️ Downloading... {int(status.progress() * 100)}%", end="\r", flush=True)
                    print("\n✅ Download Complete.")
                    break 
                except Exception as e:
                    print(f"\n⚠️ Download Interrupted: {e}. Retrying...", flush=True)
                    time.sleep(5)
            else:
                print("❌ Download Failed. Skipping.")
                continue

            srcs = []
            if file['name'].endswith('.zip'):
                try:
                    patoolib.extract_archive(fpath, outdir=TEMP_DIR)
                    for r, _, fs in os.walk(TEMP_DIR):
                        for af in fs:
                            if af.lower().endswith(('.flac', '.mp3', '.m4a', '.wav')) and 'final_mix' not in af and 'chunk' not in af:
                                srcs.append(os.path.join(r, af))
                except Exception as e:
                    log_error(f"Archive Extraction Failed", e)
                    continue
            else: srcs.append(fpath)
            
            if not srcs: print("ℹ️ No audio files found."); continue
            
            mixed = mix_audio_ffmpeg(srcs)
            chunks = split_audio_ffmpeg(mixed)
            full_text = transcribe_with_groq(chunks)
            meta, report, logs = analyze_text_with_gemini(full_text)
            
            did, oname = notion_query_student(meta['student_name'])
            if not did: 
                print("ℹ️ Student not found. Using Fallback DB.")
                did = FINAL_FALLBACK_DB_ID
            
            props = {"名前": {"title": [{"text": {"content": f"{meta['date']} {oname} ログ"}}]}, "日付": {"date": {"start": meta['date']}}}
            content = f"### 📊 SZメソッド詳細分析\n\n{report}\n\n---\n### 📝 時系列ログ\n\n{logs}"
            blocks = []
            for line in content.split('\n'):
                if line.strip():
                    blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": line[:1900]}}]}})
            
            notion_create_page_heavy(sanitize_id(did), props, blocks)
            
            processed_folder_id = ensure_processed_folder()
            upload_mix_to_drive(mixed, processed_folder_id, f"{meta['date']}_{oname}_Full.mp3")
            move_original_file(file['id'], processed_folder_id)

        except Exception as e:
            log_error(f"Processing Failed for {file['name']}", e)
            continue
        finally:
            if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR); os.makedirs(TEMP_DIR)

if __name__ == "__main__": main()
