import sys
import subprocess
import os
import time
import json
import shutil
import glob
import re
import traceback
import random
import copy
import difflib # ★追加: あいまい検索用
from datetime import datetime, timedelta, timezone

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
from googleapiclient.errors import HttpError
import patoolib

# --- Configuration ---
FINAL_CONTROL_DB_ID = "2b71bc8521e380868094ec506b41f664"
FINAL_FALLBACK_DB_ID = "2e01bc8521e380ffaf28c2ab9376b00d"
TEMP_DIR = "temp_workspace"
CHUNK_LENGTH = 900  # 15 min

# Global Variables
RESOLVED_MODEL_ID = None
BOT_EMAIL = None
STUDENT_REGISTRY = {} # ★生徒名簿キャッシュ { "name": "page_id" }

# --- Helper: Verbose Error Printer ---
def log_error(context, error_obj):
    if isinstance(error_obj, HttpError) and "storageQuotaExceeded" in str(error_obj):
        print(f"⚠️ [Quota Limit] Could not upload artifact ({context}). Skipping.", flush=True)
    else:
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
        try:
            key_data = json.loads(sa_key)
            BOT_EMAIL = key_data.get("client_email", "Unknown")
            print(f"\n==========================================")
            print(f"🤖 BOT EMAIL: {BOT_EMAIL}")
            print(f"👉 Ensure this email is an 'Editor' of the folder!")
            print(f"==========================================\n", flush=True)
        except: pass
    else:
        print("❌ ENV Error: GCP_SA_KEY is missing.")
        sys.exit(1)

setup_env()

try:
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    
    print("💎 Detecting Best Available Model...", flush=True)
    
    PRIORITY_TARGETS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    for target in PRIORITY_TARGETS:
        print(f"👉 Testing: [{target}]...", flush=True)
        try:
            gemini_client.models.generate_content(model=target, contents="Hello")
            print(f"✅ SUCCESS! Using Model: [{target}]", flush=True)
            RESOLVED_MODEL_ID = target
            break
        except Exception: continue
                
    if not RESOLVED_MODEL_ID:
        RESOLVED_MODEL_ID = "gemini-1.5-flash"
        print(f"⚠️ All checks failed. Forcing Fallback to: {RESOLVED_MODEL_ID}")

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

# --- ★ New Logic: Student Registry & Fuzzy Match ---

def load_student_registry():
    """
    Control DBから生徒一覧を一括取得してキャッシュする
    """
    global STUDENT_REGISTRY
    print("📋 Loading Student Registry from Notion...", flush=True)
    db_id = sanitize_id(FINAL_CONTROL_DB_ID)
    if not db_id: return

    has_more = True
    next_cursor = None
    count = 0

    while has_more:
        payload = {"page_size": 100}
        if next_cursor: payload["start_cursor"] = next_cursor
        
        try:
            res = requests.post(f"https://api.notion.com/v1/databases/{db_id}/query", headers=HEADERS, json=payload)
            if res.status_code != 200: break
            data = res.json()
            
            for row in data.get("results", []):
                # Nameプロパティの取得
                try:
                    name_list = row["properties"]["Name"]["title"]
                    if not name_list: continue
                    name = name_list[0]["plain_text"]
                    
                    # TargetID (生徒別DBのID) の取得
                    tid_list = row["properties"]["TargetID"]["rich_text"]
                    tid = sanitize_id(tid_list[0]["plain_text"]) if tid_list else None
                    
                    if name and tid:
                        STUDENT_REGISTRY[name] = tid
                        count += 1
                except: continue
            
            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")
        except Exception as e:
            print(f"⚠️ Registry Load Error: {e}")
            break
            
    print(f"✅ Loaded {count} students into registry.", flush=True)

def find_best_student_match(query_name):
    """
    あいまい検索で最も近い生徒を探す
    """
    if not query_name or not STUDENT_REGISTRY:
        return None, query_name

    # 1. 完全一致チェック
    if query_name in STUDENT_REGISTRY:
        return STUDENT_REGISTRY[query_name], query_name

    # 2. あいまい検索 (類似度0.4以上)
    # difflib.get_close_matches はリストを返す
    candidates = list(STUDENT_REGISTRY.keys())
    matches = difflib.get_close_matches(query_name, candidates, n=1, cutoff=0.4)
    
    if matches:
        best_name = matches[0]
        print(f"🎯 Fuzzy Match: '{query_name}' -> '{best_name}'", flush=True)
        return STUDENT_REGISTRY[best_name], best_name
    
    print(f"⚠️ No match found for '{query_name}'.", flush=True)
    return None, query_name

# --- 2. Logic: Metadata Helpers ---

def sanitize_filename(filename):
    return filename.replace("/", "_").replace("\\", "_")

def get_jst_now():
    return datetime.now(timezone(timedelta(hours=9)))

def extract_date_smart(filename, drive_created_time_iso):
    match = re.search(r'(\d{4}-\d{2}-\d{2})_(\d{1,2}-\d{1,2}-\d{1,2})', filename)
    if match:
        d_part = match.group(1)
        t_part = match.group(2).replace('-', ':')
        t_parts = t_part.split(':')
        t_formatted = f"{int(t_parts[0]):02}:{int(t_parts[1]):02}:{int(t_parts[2]):02}"
        return f"{d_part} {t_formatted}", d_part
    
    if drive_created_time_iso:
        try:
            dt = datetime.fromisoformat(drive_created_time_iso.replace('Z', '+00:00'))
            dt_jst = dt.astimezone(timezone(timedelta(hours=9)))
            return dt_jst.strftime('%Y-%m-%d %H:%M:%S'), dt_jst.strftime('%Y-%m-%d')
        except: pass

    now_jst = get_jst_now()
    return now_jst.strftime('%Y-%m-%d %H:%M:%S'), now_jst.strftime('%Y-%m-%d')

def detect_student_candidate_raw(file_list, original_archive_name):
    strong_candidates = []
    weak_candidates = []
    ignore_files = ["raw.dat", "info.txt", "ds_store", "thumbs.db", "desktop.ini", "readme", "license"]
    ignore_names = ["hikari", "craig", "entrymonster", "bot", "ssb"]

    print("🔎 Scanning internal files for student ID hint...", flush=True)
    for f in file_list:
        basename = os.path.basename(f).lower()
        if any(ign in basename for ign in ignore_files): continue
        
        name_part = os.path.splitext(basename)[0]
        craig_match = re.match(r'^\d+-(.+)', name_part)
        
        candidate = craig_match.group(1) if craig_match else name_part
            
        if any(ign in candidate for ign in ignore_names): continue
        if len(candidate) < 2: continue

        if craig_match: strong_candidates.append(candidate)
        else: weak_candidates.append(candidate)

    final = strong_candidates if strong_candidates else weak_candidates
    
    if not final:
        base = os.path.basename(original_archive_name)
        name_cleaned = re.sub(r'\.zip|\.flac|\.mp3|\.wav', '', base, flags=re.IGNORECASE)
        name_cleaned = re.sub(r'\d{4}-\d{2}-\d{2}', '', name_cleaned)
        if len(name_cleaned) > 2: final = [name_cleaned]

    if final:
        hint = ", ".join(sorted(list(set(final))))
        print(f"💡 Found Student Hint: {hint}", flush=True)
        return hint
    return None

# --- 3. Audio Pipeline ---

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
    valid_files = [f for f in file_paths if f.lower().endswith(('.mp3', '.wav', '.flac', '.m4a', '.aac'))]
    if not valid_files: raise Exception("No audio files.")
    for f in valid_files: inputs.extend(['-i', f])
    filter_part = ['-filter_complex', f'amix=inputs={len(valid_files)}:duration=longest'] if len(valid_files) > 1 else []
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

# --- 4. Intelligence Analysis ---

def analyze_text_with_gemini(transcript_text, date_hint, raw_name_hint):
    print(f"🧠 Gemini Analyzing using [{RESOLVED_MODEL_ID}]...", flush=True)
    
    hint_context = f"録音日時: {date_hint}"
    if raw_name_hint:
        hint_context += f"\n【重要】ファイル名ヒント: '{raw_name_hint}'"
    
    prompt = f"""
    あなたは世界最高峰のスマブラ（Super Smash Bros.）アナリストです。
    
    【重要: 生徒名の特定】
    以下のヒントと会話内容から、生徒の名前を特定してください。
    
    {hint_context}

    * ヒント（例: nattsu9463）がある場合、それは**ほぼ確実に生徒名**です。
    * もしヒントが無くても、会話で「〇〇さん」と呼ばれていればそれを採用してください。
    * どうしても不明な場合のみ "Unknown" としてください。

    ---
    会話ログを精読し、以下の3つのセクションを出力すること。

    **【Section 1: トピック別・詳細分析レポート】**
    主要なトピックを抽出し、以下5要素で記述。
    * ① 現状 (Status)
    * ② 課題 (Problem)
    * ③ 原因 (Root Cause)
    * ④ 改善案 (Solution)
    * ⑤ やること (Next Action): 1行

    **【Section 2: 時系列ログ】**
    箇条書きで詳細に。

    **【Section 3: メタデータJSON】**
    {{
      "student_name": "決定した生徒名",
      "date": "YYYY-MM-DD",
      "next_action": "アクション1つ"
    }}

    ---
    **[DETAILED_REPORT_START]**
    (Section 1)
    **[DETAILED_REPORT_END]**

    **[RAW_LOG_START]**
    (Section 2)
    **[RAW_LOG_END]**

    **[JSON_START]**
    (Section 3)
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
            if "429" in err_str or "quota" in err_str or "overloaded" in err_str:
                wait = 60 * (attempt + 1)
                print(f"⏳ Gemini Busy ({RESOLVED_MODEL_ID}). Waiting {wait}s...", flush=True)
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

# --- 5. Asset Management ---

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
        date_val = props.get("日付", {}).get("date", {}).get("start", "Unknown")
        error_note = {"object": "block", "type": "callout", "callout": {"rich_text": [{"text": {"content": f"⚠️ Date Prop Missing. Date: {date_val}"}}]}}
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

def upload_file_to_drive(local_path, folder_id, rename_to, mime_type):
    print(f"📤 Uploading {rename_to}...", flush=True)
    try:
        media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True, chunksize=100*1024*1024)
        drive_service.files().create(
            body={'name': rename_to, 'parents': [folder_id]}, 
            media_body=media, 
            fields='id',
            supportsAllDrives=True
        ).execute()
        print("✅ Upload Complete.", flush=True)
    except Exception as e:
        log_error(f"Upload Failed for {rename_to}", e)

def move_original_file(file_id, folder_id):
    if folder_id == INBOX_FOLDER_ID:
        print("⚠️ Skipping Move: Destination is Inbox.", flush=True)
        return
    try:
        prev_parents = drive_service.files().get(fileId=file_id, fields='parents').execute().get('parents', [])
        prev_str = ",".join(prev_parents)
        drive_service.files().update(
            fileId=file_id, 
            addParents=folder_id, 
            removeParents=prev_str,
            supportsAllDrives=True
        ).execute()
        print(f"📦 Archived original file to folder [{folder_id}].", flush=True)
    except Exception as e:
        log_error(f"Move Original File Failed (ID: {file_id})", e)
        print(f"👉 TIP: Add this email to folder permissions: {BOT_EMAIL}", flush=True)

# --- Main ---
def main():
    print("--- SZ AUTO LOGGER ULTIMATE (v114.0 - Fuzzy Matcher) ---", flush=True)
    
    # ★処理開始前に全生徒リストをロード
    load_student_registry()
    
    try:
        files = drive_service.files().list(
            q=f"'{INBOX_FOLDER_ID}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'",
            fields="files(id, name, createdTime)"
        ).execute().get('files', [])
    except Exception: return

    if not files: print("ℹ️ No files."); return

    for file in files:
        try:
            print(f"\n📂 Processing: {file['name']}")
            safe_name = sanitize_filename(file['name'])
            fpath = os.path.join(TEMP_DIR, safe_name)
            
            # Download
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
            candidate_raw_name = None

            if safe_name.endswith('.zip'):
                try:
                    patoolib.extract_archive(fpath, outdir=TEMP_DIR)
                    extracted_files = []
                    for r, _, fs in os.walk(TEMP_DIR):
                        for af in fs:
                            full_p = os.path.join(r, af)
                            extracted_files.append(full_p)
                            if af.lower().endswith(('.flac', '.mp3', '.m4a', '.wav')) and 'final_mix' not in af and 'chunk' not in af:
                                srcs.append(full_p)
                    
                    candidate_raw_name = detect_student_candidate_raw(extracted_files, file['name'])

                except Exception as e:
                    log_error(f"Archive Extraction Failed", e)
                    continue
            else: srcs.append(fpath)
            
            if not srcs: print("ℹ️ No audio files found."); continue
            
            # Processing
            precise_datetime, date_only = extract_date_smart(file['name'], file.get('createdTime'))
            mixed = mix_audio_ffmpeg(srcs)
            chunks = split_audio_ffmpeg(mixed)
            full_text = transcribe_with_groq(chunks)
            meta, report, logs = analyze_text_with_gemini(full_text, precise_datetime, candidate_raw_name)
            
            # ★【変更】あいまい検索で正式名称とIDを特定
            did, oname = find_best_student_match(meta['student_name'])
            
            # Content Construction
            content = f"### 📊 SZメソッド詳細分析\n\n{report}\n\n---\n### 📝 時系列ログ\n\n{logs}"
            blocks = []
            for line in content.split('\n'):
                if line.strip():
                    blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": line[:1900]}}]}})
            
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            blocks.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "📜 全文文字起こし"}}]}})
            for i in range(0, len(full_text), 1900):
                chunk_text = full_text[i:i+1900]
                blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": chunk_text}}]}})
            
            # 正式名称を使ってタイトル生成
            props = {
                "名前": {"title": [{"text": {"content": f"{precise_datetime} {oname} 通話ログ"}}]}, 
                "日付": {"date": {"start": date_only}}
            }

            print("💾 Saving to Fallback DB (All Data)...")
            notion_create_page_heavy(sanitize_id(FINAL_FALLBACK_DB_ID), copy.deepcopy(props), copy.deepcopy(blocks))
            
            if did and did != FINAL_FALLBACK_DB_ID:
                print(f"👤 Saving to Student DB ({oname})...")
                notion_create_page_heavy(sanitize_id(did), copy.deepcopy(props), copy.deepcopy(blocks))
            
            # Artifacts
            processed_folder_id = ensure_processed_folder()
            safe_filename_time = precise_datetime.replace(':', '-').replace(' ', '_')
            
            upload_file_to_drive(mixed, processed_folder_id, f"{safe_filename_time}_{oname}_Full.mp3", 'audio/mpeg')
            
            txt_path = os.path.join(TEMP_DIR, "transcript.txt")
            with open(txt_path, "w") as f: f.write(full_text)
            upload_file_to_drive(txt_path, processed_folder_id, f"{safe_filename_time}_{oname}_Transcript.txt", 'text/plain')
            
            move_original_file(file['id'], processed_folder_id)

        except Exception as e:
            log_error(f"Processing Failed for {file['name']}", e)
            continue
        finally:
            if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR); os.makedirs(TEMP_DIR)

if __name__ == "__main__": main()
