import os
import sys
import time
import json
import logging
import re
import zipfile
import shutil
from datetime import datetime

# ライブラリは run_bot.yml 側で管理するため、Python内での強制インストールは廃止
import requests
import google.generativeai as genai
from pydub import AudioSegment
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# --- 設定値 ---
FINAL_CONTROL_DB_ID = "2b71bc8521e380868094ec506b41f664" 
FINAL_FALLBACK_DB_ID = "2b71bc8521e38018a5c3c4b0c6b6627c" # Inbox ID

# --- 初期化 ---
TEMP_DIR = "downloads"
if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
os.makedirs(TEMP_DIR)

if os.getenv("GCP_SA_KEY"):
    with open("service_account.json", "w") as f:
        f.write(os.getenv("GCP_SA_KEY"))

def sanitize_id(raw_id):
    if not raw_id: return None
    match = re.search(r'([a-fA-F0-9]{32})', str(raw_id).replace("-", ""))
    if match: return match.group(1)
    return None

try:
    NOTION_TOKEN = os.getenv("NOTION_TOKEN")
    HEADERS = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28" 
    }
    
    CONTROL_CENTER_ID = sanitize_id(FINAL_CONTROL_DB_ID)
    FALLBACK_DB_ID = sanitize_id(FINAL_FALLBACK_DB_ID)
    INBOX_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
    
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)
    
except Exception as e:
    print(f"❌ Setup Critical Error: {e}", flush=True)
    exit(1)

# --- Notion API Helpers ---

def notion_query_database(db_id, query_filter):
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    try:
        res = requests.post(url, headers=HEADERS, json=query_filter)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"⚠️ Notion Query Error: {e}")
        return None

def notion_create_page(parent_db_id, properties, children):
    url = "https://api.notion.com/v1/pages"
    payload = {"parent": {"database_id": parent_db_id}, "properties": properties, "children": children}
    try:
        res = requests.post(url, headers=HEADERS, json=payload)
        res.raise_for_status()
        return res.json()
    except Exception as e:
        print(f"❌ Create Page Error: {e}")
        raise e

def get_student_target_id(student_name):
    """Control Centerから生徒を検索し、TargetIDを返す。見つからなければNone"""
    print(f"🔍 Looking up student: '{student_name}'", flush=True)
    search_filter = {"filter": {"property": "Name", "title": {"contains": student_name}}}
    
    data = notion_query_database(CONTROL_CENTER_ID, search_filter)
    if not data: return None
    
    results = data.get("results", [])
    if not results: return None
    
    target_id_prop = results[0]["properties"].get("TargetID", {}).get("rich_text", [])
    if not target_id_prop: return None
    
    return sanitize_id(target_id_prop[0]["plain_text"])

# --- Drive & Gemini Helpers ---

def download_file(file_id, file_name):
    request = drive_service.files().get_media(fileId=file_id)
    file_path = os.path.join(TEMP_DIR, file_name)
    with open(file_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
    return file_path

def extract_audio_from_zip(zip_path):
    extracted_files = []
    extract_dir = os.path.join(TEMP_DIR, "extracted_" + os.path.basename(zip_path))
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_dir)
    for root, dirs, files in os.walk(extract_dir):
        for file in files:
            if file.lower().endswith(('.flac', '.mp3', '.aac', '.wav', '.m4a')):
                extracted_files.append(os.path.join(root, file))
    return extracted_files

def mix_audio_files(file_paths):
    if not file_paths: return None
    print(f"🎛️ Mixing {len(file_paths)} tracks...", flush=True)
    try:
        mixed = AudioSegment.from_file(file_paths[0])
        for path in file_paths[1:]:
            mixed = mixed.overlay(AudioSegment.from_file(path))
        output_path = os.path.join(TEMP_DIR, "mixed_session.mp3")
        mixed.export(output_path, format="mp3")
        return output_path
    except Exception as e:
        print(f"⚠️ Mixing Error: {e}. Using largest file.", flush=True)
        return max(file_paths, key=os.path.getsize)

def get_available_model_name():
    # 2.5 Pro優先 -> 2.0 Pro -> Flash
    try:
        models = list(genai.list_models())
        names = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        for n in names: 
            if 'gemini-2.5-pro' in n: return n
        for n in names: 
            if 'gemini-2.0-pro' in n: return n
        return 'models/gemini-2.0-flash'
    except:
        return 'models/gemini-2.0-flash'

def analyze_audio_auto(file_path):
    model_name_initial = get_available_model_name()
    
    prompt = """
    あなたは**トップ・スマブラアナリスト**です。
    この音声は、**コーチ (Hikari)** と **クライアント (生徒)** の対話ログです。

    【最優先用語】: 「着地狩り」「崖際」「復帰阻止」「間合い」「確定反撃」

    ---
    **[RAW_TRANSCRIPTION_START]**
    会話全体を可能な限り正確に、逐語訳形式で文字起こしせよ。
    **[RAW_TRANSCRIPTION_END]**
    ---

    【分析構造：5要素】
    スマブラの内容および取り組み改善における話題は、以下の5要素に分割せよ。
    * **現状** (Current Status)
    * **課題** (Problem/Issue)
    * **原因** (Root Cause)
    * **改善案** (Proposed Solution)
    * **やること** (Next Action/Commitment)

    【最終出力形式 (JSON)】
    {
      "student_name": "生徒の名前（例: らぎぴ, トロピウス, Unknown）",
      "date": "YYYY-MM-DD (不明ならToday)",
      "summary": "[感情アイコン] - 5要素分析に基づく課題とコミットメントの要約（150字以内）。",
      "next_action": "次のタスク（期限含む）"
    }
    """

    # Quota Fallback Logic included
    current_model = model_name_initial
    for attempt in range(2):
        try:
            print(f"🧠 Analyzing with {current_model}...", flush=True)
            model = genai.GenerativeModel(current_model)
            audio_file = genai.upload_file(file_path)
            while audio_file.state.name == "PROCESSING": time.sleep(2); audio_file = genai.get_file(audio_file.name)
            
            response = model.generate_content([prompt, audio_file])
            text = response.text.strip()
            
            # Cleanup
            try: genai.delete_file(audio_file.name)
            except: pass

            # Parse
            raw = re.search(r'\[RAW_TRANSCRIPTION_START\](.*?)\[RAW_TRANSCRIPTION_END\]', text, re.DOTALL)
            raw_text = raw.group(1).strip() if raw else "Transcript Error"
            
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                if data.get('date') in ['Unknown', 'Today']: data['date'] = datetime.now().strftime('%Y-%m-%d')
                return data, raw_text
            else:
                raise ValueError("JSON Parse Failed")

        except Exception as e:
            if attempt == 0 and "pro" in current_model.lower():
                print("⚠️ Quota/Error on Pro. Switching to Flash.", flush=True)
                current_model = 'gemini-2.0-flash'
                time.sleep(2)
                continue
            raise e

# --- File Cleanup ---
def cleanup_drive_file(file_id):
    folder_name = "processed_coaching_logs"
    try:
        q = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and '{INBOX_FOLDER_ID}' in parents and trashed=false"
        res = drive_service.files().list(q=q, fields='files(id)').execute()
        files = res.get('files', [])
        target_id = files[0]['id'] if files else drive_service.files().create(body={'name': folder_name, 'mimeType': 'application/vnd.google-apps.folder', 'parents': [INBOX_FOLDER_ID]}, fields='id').execute().get('id')
        
        file = drive_service.files().get(fileId=file_id, fields='parents').execute()
        drive_service.files().update(fileId=file_id, addParents=target_id, removeParents=",".join(file.get('parents')), fields='id, parents').execute()
        print("➡️ File moved to processed folder.", flush=True)
    except: pass

# --- Main ---
def main():
    print("--- VERSION: OPTIMIZED & LIGHTWEIGHT (v54.0) ---", flush=True)
    
    if not INBOX_FOLDER_ID: return

    # 1. Drive Check
    try:
        results = drive_service.files().list(
            q=f"'{INBOX_FOLDER_ID}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false",
            fields="files(id, name)", orderBy="createdTime desc"
        ).execute()
    except: return
    
    files = results.get('files', [])
    if not files:
        print("ℹ️ No new files.", flush=True)
        return

    # 2. Manual Mode Pre-Check
    manual_name = os.getenv("MANUAL_STUDENT_NAME")
    manual_target_id = None
    
    # ★高速化: 手動入力がある場合、AIを動かす前にNotionでIDを確定させておく
    if manual_name:
        print(f"✅ Manual Mode: Checking '{manual_name}' in Notion...", flush=True)
        manual_target_id = get_student_target_id(manual_name)
        if not manual_target_id:
            print(f"❌ Error: Manual name '{manual_name}' not found in Control Center. Fallback to Auto.", flush=True)
            manual_name = None # 自動モードに戻す

    # 3. Processing Loop
    for file in files:
        file_id = file['id']
        file_name = file['name']
        print(f"\nProcessing: {file_name}", flush=True)
        
        try:
            # 3.1 Audio Prep
            local_paths = []
            path = download_file(file_id, file_name)
            if file_name.lower().endswith('.zip'): local_paths.extend(extract_audio_from_zip(path))
            else: local_paths.append(path)
            
            if not local_paths: continue
            mixed_path = mix_audio_files(local_paths)

            # 3.2 AI Analysis
            full_analysis, raw_transcript = analyze_audio_auto(mixed_path)
            
            # 3.3 Destination Logic
            final_target_id = None
            student_name = full_analysis['student_name']

            if manual_target_id:
                # 手動モードで特定済みのIDを使用
                final_target_id = manual_target_id
                student_name = manual_name # 名前を強制上書き
                print(f"📝 Using Manual Target ID for: {student_name}", flush=True)
            else:
                # 自動モード: AIの名前から検索
                final_target_id = get_student_target_id(student_name)
            
            # 3.4 Fallback Logic
            destination_id = final_target_id
            log_suffix = ""
            
            if not destination_id:
                print(f"⚠️ Student '{student_name}' not found/invalid. Routing to FALLBACK INBOX.", flush=True)
                destination_id = FALLBACK_DB_ID
                log_suffix = f" (Unknown: {student_name})"
            
            if not destination_id:
                print("❌ Critical: No destination available.", flush=True)
                continue

            # 3.5 Write to Notion
            # Summary
            props_sum = {
                "名前": {"title": [{"text": {"content": f"{full_analysis['date']} ログ{log_suffix}"}}]},
                "日付": {"date": {"start": full_analysis['date']}}
            }
            # Fallback時は生徒名を本文かプロパティに入れる（簡易的にタイトルに付与済み）
            
            children_sum = [
                {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": full_analysis['summary']}}]}},
                {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "Next Action"}}]}},
                {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": full_analysis.get('next_action', 'なし')}}]}}
            ]
            notion_create_page(destination_id, props_sum, children_sum)
            print("✅ Summary created.", flush=True)

            # Transcript
            props_trans = {
                "名前": {"title": [{"text": {"content": f"{full_analysis['date']} 文字起こし{log_suffix}"}}]},
                "日付": {"date": {"start": full_analysis['date']}}
            }
            children_trans = []
            for line in raw_transcript.split('\n'):
                if line.strip():
                    children_trans.append({
                        "object": "block", "type": "paragraph", 
                        "paragraph": {"rich_text": [{"text": {"content": line[:2000]}}]}
                    })
            
            # ブロック数制限対策(簡易)
            if len(children_trans) > 95: 
                children_trans = children_trans[:95]
                children_trans.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": "...(Log Truncated)..."}}]}})

            notion_create_page(destination_id, props_trans, children_trans)
            print("✅ Transcript created.", flush=True)

            # 3.6 Cleanup
            cleanup_drive_file(file_id)

        except Exception as e:
            print(f"❌ Error: {e}", flush=True)
        finally:
            if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
            os.makedirs(TEMP_DIR)

if __name__ == "__main__":
    main()
