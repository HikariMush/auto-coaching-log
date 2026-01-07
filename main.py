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
import difflib
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
STUDENT_REGISTRY = {}

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

# --- Logic: Registry & Fuzzy Match ---

def load_student_registry():
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
                try:
                    name_list = row["properties"]["Name"]["title"]
                    if not name_list: continue
                    name = name_list[0]["plain_text"]
                    tid_list = row["properties"]["TargetID"]["rich_text"]
                    tid = sanitize_id(tid_list[0]["plain_text"]) if tid_list else None
                    if name and tid:
                        STUDENT_REGISTRY[name] = tid
                        count += 1
                except: continue
            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")
        except Exception as e: break
    print(f"✅ Loaded {count} students into registry.", flush=True)

def find_best_student_match(query_name):
    if not query_name or not STUDENT_REGISTRY: return None, query_name
    if query_name in STUDENT_REGISTRY: return STUDENT_REGISTRY[query_name], query_name
    matches = difflib.get_close_matches(query_name, list(STUDENT_REGISTRY.keys()), n=1, cutoff=0.4)
    if matches:
        print(f"🎯 Fuzzy Match: '{query_name}' -> '{matches[0]}'", flush=True)
        return STUDENT_REGISTRY[matches[0]], matches[0]
    return None, query_name

# --- Logic: Metadata Helpers ---

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

# --- 4. Intelligence Analysis (Expert Mode) ---

def analyze_text_with_gemini(transcript_text, date_hint, raw_name_hint):
    print(f"🧠 Gemini Analyzing using [{RESOLVED_MODEL_ID}]...", flush=True)
    
    hint_context = f"録音日時: {date_hint}"
    if raw_name_hint:
        hint_context += f"\n【重要】ファイル名ヒント: '{raw_name_hint}' (これを最優先で生徒名として採用せよ)"
    
    # ★プロンプト強化：レイアウトは維持しつつ、分析精度を極限まで高める
    prompt = f"""
    あなたは世界最高峰のスマブラ（Super Smash Bros.）アナリストであり、プレイヤーの勝利に執着する冷徹な戦略家です。
    曖昧な励ましや社交辞令は一切排除し、フレームデータ、リスクリターン、人読み（癖読み）の観点から深く鋭い指摘を行ってください。

    【メタデータ情報】
    {hint_context}

    ---
    **【重要：出力レイアウト規則】**
    * Notionで見やすい階層構造を作ること。表形式(Markdown Table)やHTMLタグは禁止。
    * **構造:**
        * トピック名: `##` (H2)
        * 詳細項目: `- **項目名:** 内容` (箇条書き＋太字)
    * **余白:** 項目やセクションの間には必ず「空行」を入れること。

    **【Section 1: 詳細分析レポート】**
    会話データから主要な改善ポイント（例：崖狩り、着地狩り、ライン管理、復帰阻止など）を抽出し、
    各トピックについて以下の**5つの観点**を必ず網羅して記述せよ。省略は許されない。

    ## [トピック名]

    - **① 現状 (Status):** プレイヤーが現在行っている具体的な挙動、癖、認識のズレ。

    - **② 課題 (Problem):** その挙動が引き起こすリスク（不利フレーム、撃墜拒否ミス、ライン喪失など）。

    - **③ 原因 (Root Cause):** なぜその課題が起きるのか（知識不足、手癖、リスク管理の甘さ、相手の行動確認不足など）。

    - **④ 改善案 (Solution):** 具体的な修正アクション（％帯による技選択、視線の配り方、意識配分）。

    - **⑤ やること (Next Action):** 即座に実行可能な、短く明確な指示。

    (トピックが複数ある場合は、空行を入れてこれを繰り返す)

    **【Section 2: 課題セット】**
    Section 1の内容を元に、生徒が試合中や練習中に反復確認するための**「超簡潔なアクションリスト」**を作成せよ。
    これはこのシステムの根幹を担うため、必ず生成せよ。
    * **形式:** `### [状況/分類]` で見出しを作り、その下に `[トリガー] → [アクション]` を列挙。
    * **文法:** 文章禁止。単語と矢印のみ。

    * **出力例:**
    ### 復帰阻止展開
    - ルート確認 → 空前置き
    - 崖下待機 → メテオ合わせ

    ### 着地狩り
    - N回避確認 → 最大リターン
    - 暴れ読み → ガード待機

    **【Section 3: 時系列ログ】**
    セッション全体の流れを時系列で箇条書きにせよ。重要な気づきの瞬間を逃さないこと。

    **【Section 4: メタデータJSON】**
    以下のJSONのみを出力すること。
    {{
      "student_name": "生徒名",
      "date": "YYYY-MM-DD",
      "next_action": "最も優先度の高いアクション1つ"
    }}

    ---
    **出力ブロック（システム制御用タグ）：**

    **[DETAILED_REPORT_START]**
    (Section 1 と Section 2 の内容)
    **[DETAILED_REPORT_END]**

    **[RAW_LOG_START]**
    (Section 3 の内容)
    **[RAW_LOG_END]**

    **[JSON_START]**
    (Section 4 のJSON)
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

    def extract_safe(s, e, src):
        m = re.search(f'{re.escape(s)}(.*?){re.escape(e)}', src, re.DOTALL)
        return m.group(1).strip() if m else None

    report = extract_safe("[DETAILED_REPORT_START]", "[DETAILED_REPORT_END]", text)
    time_log = extract_safe("[RAW_LOG_START]", "[RAW_LOG_END]", text)
    json_str = extract_safe("[JSON_START]", "[JSON_END]", text)

    if not report:
        print("⚠️ Warning: Missing REPORT tags. Fallback...", flush=True)
        if "[RAW_LOG_START]" in text:
            report = text.split("[RAW_LOG_START]")[0].replace("[DETAILED_REPORT_START]", "").strip()
        else:
            report = text

    if not time_log: time_log = "Log tags missing."

    try: 
        if json_str: data = json.loads(json_str)
        else: raise ValueError("No JSON block")
    except: 
        try:
            json_candidate = re.search(r'\{.*"student_name".*\}', text, re.DOTALL)
            if json_candidate: data = json.loads(json_candidate.group(0))
            else: data = {"student_name": "Unknown", "date": datetime.now().strftime('%Y-%m-%d'), "next_action": "Check Logs"}
        except:
            data = {"student_name": "Unknown", "date": datetime.now().strftime('%Y-%m-%d'), "next_action": "Check Logs"}
            
    return data, report, time_log

def text_to_notion_blocks(text):
    """
    Markdownを行ごとに解析し、Notionブロックに変換。
    """
    blocks = []
    lines = text.split('\n')
    
    for line in lines:
        if not line.strip():
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": []} # Empty paragraph for spacing
            })
            continue
        
        if line.startswith('|') or line.startswith('+-'):
             continue 

        # 太字(**)はNotion APIでサポートされるため、削除せずそのまま渡す
        clean_content = line[:1900] 
        
        if line.startswith('### '):
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": clean_content[4:]}}]}
            })
        elif line.startswith('## '):
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": clean_content[3:]}}]}
            })
        elif line.startswith('# '):
            blocks.append({
                "object": "block",
                "type": "heading_1",
                "heading_1": {"rich_text": [{"type": "text", "text": {"content": clean_content[2:]}}]}
            })
        elif line.startswith('- ') or line.startswith('* '):
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": clean_content[2:]}}]}
            })
        else:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": clean_content}}]}
            })
            
    return blocks

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
    print("--- SZ AUTO LOGGER ULTIMATE (v121.0 - Analyst Hardened) ---", flush=True)
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
            
            # Analysis
            meta, report, logs = analyze_text_with_gemini(full_text, precise_datetime, candidate_raw_name)
            
            # DB Matching
            did, oname = find_best_student_match(meta['student_name'])
            
            # Content
            content = f"### 📊 SZメソッド詳細分析\n\n{report}\n\n---\n\n### 📝 時系列ログ\n\n{logs}"
            
            # Convert to Blocks
            blocks = text_to_notion_blocks(content)
            
            # Divider for Transcript
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            blocks.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "📜 全文文字起こし"}}]}})
            
            for i in range(0, len(full_text), 1900):
                chunk_text = full_text[i:i+1900]
                blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": chunk_text}}]}})
            
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
