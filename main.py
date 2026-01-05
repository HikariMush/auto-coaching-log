import sys
import subprocess
import os
import time
import json
import shutil
import glob
import re
from datetime import datetime

# --- 0. SDK更新 ---
try:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "google-genai"])
    subprocess.check_call([sys.executable, "-m", "pip", "install", "groq"])
except: pass

# --- Libraries ---
import requests
from google import genai 
from google.genai import types
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

# グローバル変数
RESOLVED_MODEL_ID = None

# --- 1. 初期化 & 徹底診断 (Setup & Deep Scan) ---
def setup_env():
    if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
    os.makedirs(TEMP_DIR)
    if os.getenv("GCP_SA_KEY"):
        with open("service_account.json", "w") as f:
            f.write(os.getenv("GCP_SA_KEY"))

setup_env()

try:
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    
    print("📋 Listing ALL available models for your API Key...", flush=True)
    
    # ★【現実直視】APIキーで見えている全モデルをリストアップする
    try:
        all_models = list(gemini_client.models.list())
        model_names = [m.name for m in all_models]
        # models/ を除去して見やすく
        clean_names = [n.replace('models/', '') for n in model_names]
        print(f"👀 Your Key sees: {clean_names}", flush=True)
        
        # 優先順位リスト (1.5 Flash -> 1.5 Pro -> 1.0 Pro)
        PRIORITY_LIST = [
            "gemini-1.5-flash", 
            "gemini-1.5-flash-001",
            "gemini-1.5-flash-002",
            "gemini-1.5-flash-latest",
            "gemini-1.5-pro",
            "gemini-1.5-pro-001",
            "gemini-1.0-pro", # 最終手段
            "gemini-pro"
        ]
        
        target = None
        for p in PRIORITY_LIST:
            # リストの中に部分一致するものがあるか探す
            if any(p in available for available in clean_names):
                target = p
                print(f"✅ Best Match Found: [{target}]", flush=True)
                break
        
        if target:
            RESOLVED_MODEL_ID = target
        else:
            # リスト取得に失敗したり空だった場合のバックアップ（2.0系など）
            print("⚠️ No standard models found in list. Trying direct connection...", flush=True)
            RESOLVED_MODEL_ID = "gemini-1.5-flash" # 強行突破
            
    except Exception as e:
        print(f"⚠️ Failed to list models: {e}")
        print("👉 Defaulting to 'gemini-1.5-flash' and praying...")
        RESOLVED_MODEL_ID = "gemini-1.5-flash"

    # 確定したモデルで接続テスト
    print(f"🩺 Final Connectivity Test: [{RESOLVED_MODEL_ID}]", flush=True)
    try:
        gemini_client.models.generate_content(
            model=RESOLVED_MODEL_ID,
            contents="Hello"
        )
        print("✅ Connection Confirmed.", flush=True)
    except Exception as e:
        err = str(e).lower()
        if "429" in err or "quota" in err:
            print("❌ Quota Exceeded (Free Tier limit).")
            # 429でもモデル自体は合ってるので続行させる（待機ロジックへ）
        elif "404" in err:
             print("❌ 404 Not Found. This Project CANNOT use this model.")
             print("💡 ACTION: Create a NEW API Key in a NEW Project at Google AI Studio.")
             sys.exit(1)
        else:
            print(f"⚠️ Warning: {e}")

    NOTION_TOKEN = os.getenv("NOTION_TOKEN")
    HEADERS = {"Authorization": f"Bearer {NOTION_TOKEN}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}
    creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=['https://www.googleapis.com/auth/drive'])
    drive_service = build('drive', 'v3', credentials=creds)
    INBOX_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
    
except Exception as e:
    print(f"❌ Init Error: {e}"); sys.exit(1)

def sanitize_id(raw_id):
    if not raw_id: return None
    match = re.search(r'([a-fA-F0-9]{32})', str(raw_id).replace("-", ""))
    return match.group(1) if match else None

# --- 2. 音声パイプライン ---

def mix_audio_ffmpeg(file_paths):
    print(f"🎛️ Mixing {len(file_paths)} tracks...", flush=True)
    output_path = os.path.abspath(os.path.join(TEMP_DIR, "final_mix.mp3"))
    inputs = []
    for f in file_paths: inputs.extend(['-i', f])
    filter_part = ['-filter_complex', f'amix=inputs={len(file_paths)}:duration=longest'] if len(file_paths) > 1 else []
    cmd = ['ffmpeg', '-y'] + inputs + filter_part + ['-ac', '1', '-b:a', '64k', output_path]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output_path

def split_audio_ffmpeg(input_path):
    print("🔪 Splitting...", flush=True)
    output_pattern = os.path.join(TEMP_DIR, "chunk_%03d.mp3")
    cmd = ['ffmpeg', '-y', '-i', input_path, '-f', 'segment', '-segment_time', str(CHUNK_LENGTH), '-ac', '1', '-b:a', '64k', output_pattern]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
                else: raise e
        else: raise Exception("❌ Rate Limit persists. Aborting.")
    return full_transcript

# --- 3. 知能分析 (Analysis) ---

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
    
    max_retries = 15 # 待機回数を増量
    for attempt in range(max_retries):
        try:
            response = gemini_client.models.generate_content(
                model=RESOLVED_MODEL_ID,
                contents=prompt
            )
            text = response.text.strip()
            break 
            
        except Exception as e:
            err_str = str(e).lower()
            # 429/Quotaエラーなら待機
            if "429" in err_str or "quota" in err_str or "resource_exhausted" in err_str:
                wait = 60 * (attempt + 1)
                print(f"⏳ Gemini Quota Limit ({RESOLVED_MODEL_ID}). Waiting {wait}s... ({attempt+1}/{max_retries})", flush=True)
                time.sleep(wait)
            # 503 Service Unavailable も一時的なので待機
            elif "503" in err_str or "service unavailable" in err_str:
                 wait = 30
                 print(f"⏳ Service Busy (503). Waiting {wait}s...", flush=True)
                 time.sleep(wait)
            else:
                print(f"⚠️ Gemini Analysis Failed: {e}")
                return {"student_name": "AnalysisError", "date": datetime.now().strftime('%Y-%m-%d')}, f"Analysis Error: {e}", transcript_text[:2000]
    else:
        print("❌ Gemini Quota: Gave up after retries.")
        return {"student_name": "QuotaError", "date": datetime.now().strftime('%Y-%m-%d')}, "Quota Limit Exceeded", transcript_text[:2000]
    
    def extract(s, e, src):
        m = re.search(f'{re.escape(s)}(.*?){re.escape(e)}', src, re.DOTALL)
        return m.group(1).strip() if m else ""

    report = extract("[DETAILED_REPORT_START]", "[DETAILED_REPORT_END]", text)
    time_log = extract("[RAW_LOG_START]", "[RAW_LOG_END]", text)
    json_str = extract("[JSON_START]", "[JSON_END]", text)
    
    try: data = json.loads(json_str)
    except: data = {"student_name": "Unknown", "date": datetime.now().strftime('%Y-%m-%d'), "next_action": "Check Logs"}
    return data, report, time_log

# --- 4. 資産化 ---

def notion_query_student(name):
    db_id = sanitize_id(FINAL_CONTROL_DB_ID)
    if not db_id: return None, name
    res = requests.post(f"https://api.notion.com/v1/databases/{db_id}/query", headers=HEADERS, json={"filter": {"property": "Name", "title": {"contains": name}}})
    d = res.json()
    if d.get("results"):
        row = d["results"][0]
        n = row["properties"]["Name"]["title"][0]["plain_text"]
        tid = row["properties"]["TargetID"]["rich_text"]
        return (sanitize_id(tid[0]["plain_text"]), n) if tid else (None, n)
    return None, name

def notion_create_page_heavy(db_id, props, children):
    res = requests.post("https://api.notion.com/v1/pages", headers=HEADERS, json={"parent": {"database_id": db_id}, "properties": props, "children": children[:100]})
    pid = res.json().get('id')
    if pid and len(children) > 100:
        for i in range(100, len(children), 100):
            requests.patch(f"https://api.notion.com/v1/blocks/{pid}/children", headers=HEADERS, json={"children": children[i:i+100]})

def cleanup_drive_file(file_id, rename_to):
    q = f"name='processed_coaching_logs' and '{INBOX_FOLDER_ID}' in parents"
    folders = drive_service.files().list(q=q).execute().get('files', [])
    fid = folders[0]['id'] if folders else drive_service.files().create(body={'name': 'processed_coaching_logs', 'mimeType': 'application/vnd.google-apps.folder', 'parents': [INBOX_FOLDER_ID]}, fields='id').execute().get('id')
    
    prev = ",".join(drive_service.files().get(fileId=file_id, fields='parents').execute().get('parents', []))
    drive_service.files().update(fileId=file_id, addParents=fid, removeParents=prev, body={'name': rename_to}).execute()
    print(f"✅ Drive updated: {rename_to}")

# --- Main ---
def main():
    print("--- SZ AUTO LOGGER ULTIMATE (v89.0 - Reality Check) ---", flush=True)
    files = drive_service.files().list(q=f"'{INBOX_FOLDER_ID}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'").execute().get('files', [])
    if not files: print("ℹ️ No files."); return

    for file in files:
        try:
            print(f"\n📂 Processing: {file['name']}")
            fpath = os.path.join(TEMP_DIR, file['name'])
            with open(fpath, "wb") as f:
                MediaIoBaseDownload(f, drive_service.files().get_media(fileId=file['id'])).next_chunk()
            
            srcs = []
            if file['name'].endswith('.zip'):
                with zipfile.ZipFile(fpath, 'r') as z:
                    z.extractall(TEMP_DIR)
                    for r, _, fs in os.walk(TEMP_DIR):
                        for af in fs:
                            if af.lower().endswith(('.flac', '.mp3', '.m4a', '.wav')) and 'final_mix' not in af and 'chunk' not in af:
                                srcs.append(os.path.join(r, af))
            else: srcs.append(fpath)
            
            if not srcs: continue
            
            mixed = mix_audio_ffmpeg(srcs)
            chunks = split_audio_ffmpeg(mixed)
            full_text = transcribe_with_groq(chunks)
            meta, report, logs = analyze_text_with_gemini(full_text)
            
            did, oname = notion_query_student(meta['student_name'])
            if not did: did = FINAL_FALLBACK_DB_ID
            
            props = {"名前": {"title": [{"text": {"content": f"{meta['date']} {oname} ログ"}}]}, "日付": {"date": {"start": meta['date']}}}
            content = f"### 📊 SZメソッド詳細分析\n\n{report}\n\n---\n### 📝 時系列ログ\n\n{logs}"
            blocks = []
            for line in content.split('\n'):
                if line.strip():
                    blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": line[:1900]}}]}})
            
            notion_create_page_heavy(sanitize_id(did), props, blocks)
            
            ext = os.path.splitext(file['name'])[1] or ".zip"
            cleanup_drive_file(file['id'], f"{meta['date']}_{oname}{ext}")

        except Exception as e:
            print(f"❌ CRITICAL ERROR on {file['name']}: {e}")
            import traceback; traceback.print_exc()
            print("⛔ システムを緊急停止します。")
            sys.exit(1)
        finally:
            if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR); os.makedirs(TEMP_DIR)

if __name__ == "__main__": main()
