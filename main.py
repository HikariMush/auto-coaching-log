import os
import sys
import subprocess
import time
import json
import logging
import re
import zipfile
import shutil
from datetime import datetime

# --- ライブラリ強制セットアップ ---
try:
    import requests
    import google.generativeai as genai
    from pydub import AudioSegment
except ImportError:
    print("🔄 Installing core libraries...", flush=True)
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "--upgrade", 
        "requests", "google-generativeai>=0.8.3", "pydub",
        "google-api-python-client", "google-auth"
    ])
    import requests
    import google.generativeai as genai
    from pydub import AudioSegment

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# --- 最終設定（ハードコード） ---
# Notification Botで実績のあるControl Center IDを使用
FINAL_CONTROL_DB_ID = "2b71bc8521e380868094ec506b41f664" 

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
    INBOX_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
    
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)
    
except Exception as e:
    print(f"❌ Setup Critical Error: {e}", flush=True)
    exit(1)

# --- Notion API 関数群 (Raw Requests) ---

def notion_query_database(db_id, query_filter):
    """データベースをクエリする (Raw Request)"""
    url = f"https://api.notion.com/v1/databases/{db_id}/query"
    try:
        res = requests.post(url, headers=HEADERS, json=query_filter)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.HTTPError as e:
        print(f"❌ Notion Query Error ({db_id}): Status {e.response.status_code}")
        print(f"   Detail: {e.response.text}")
        raise e

def notion_create_page(parent_db_id, properties, children):
    """新しいページを作成する (Raw Request)"""
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"database_id": parent_db_id},
        "properties": properties,
        "children": children
    }
    try:
        res = requests.post(url, headers=HEADERS, json=payload)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.HTTPError as e:
        print(f"❌ Notion Create Page Error: Status {e.response.status_code}")
        print(f"   Detail: {e.response.text}")
        raise e

# --- Audio/Drive/Gemini Helpers (Integration) ---

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
    print(f"🎛️ Mixing {len(file_paths)} audio tracks...", flush=True)
    try:
        mixed = AudioSegment.from_file(file_paths[0])
        for path in file_paths[1:]:
            track = AudioSegment.from_file(path)
            mixed = mixed.overlay(track)
        output_path = os.path.join(TEMP_DIR, "mixed_session.mp3")
        mixed.export(output_path, format="mp3")
        return output_path
    except Exception as e:
        print(f"⚠️ Mixing Error: {e}. Using largest file instead.", flush=True)
        return max(file_paths, key=os.path.getsize)

def get_available_model_name():
    models = list(genai.list_models())
    available_names = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
    for name in available_names:
        if 'gemini-2.0-flash' in name and 'exp' not in name: return name
    for name in available_names:
        if 'gemini-2.5-flash' in name: return name
    for name in available_names:
        if 'gemini-2.0-flash' in name: return name
    for name in available_names:
        if 'flash' in name: return name
    return 'models/gemini-2.0-flash'

def analyze_audio_auto(file_path):
    model_name = get_available_model_name()
    model = genai.GenerativeModel(model_name)
    audio_file = genai.upload_file(file_path)
    
    while audio_file.state.name == "PROCESSING":
        time.sleep(2)
        audio_file = genai.get_file(audio_file.name)
    if audio_file.state.name == "FAILED": raise ValueError("Audio Failed")
    
    prompt = """
    【生徒名の特定ルール】
    1. 呼びかけから生徒名を推測してください。
    2. それ以外の場合も、聞こえたままの音（カタカナやニックネーム）を入力してください。
    
    {
      "student_name": "生徒の名前（例: でっていう, 田中）",
      "date": "YYYY-MM-DD (不明ならToday)",
      "summary": "セッション要約（300文字以内）",
      "next_action": "次回の宿題"
    }
    """
    response = model.generate_content([prompt, audio_file])
    try: genai.delete_file(audio_file.name)
    except: pass
    
    text = response.text.strip()
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match: 
        data = json.loads(match.group(0))
        if data.get('date') in ['Unknown', 'Today']:
            data['date'] = datetime.now().strftime('%Y-%m-%d')
        return data
    else: 
        raise ValueError("JSON Parse Failed")

# --- メイン処理 ---
def main():
    print("--- VERSION: FINAL PRODUCTION BUILD (v39.0) ---", flush=True)
    
    if not INBOX_FOLDER_ID:
        print("❌ Error: DRIVE_FOLDER_ID is missing!", flush=True)
        return

    # 1. Drive Search (Find unprocessed files)
    try:
        results = drive_service.files().list(
            q=f"'{INBOX_FOLDER_ID}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false",
            fields="files(id, name, createdTime)",
            orderBy="createdTime desc"
        ).execute()
    except Exception as e:
        print(f"❌ Drive Search Error: {e}", flush=True)
        return
    
    files = results.get('files', [])
    
    if not files:
        print("ℹ️ No new files found. Exiting.", flush=True)
        return

    # 2. Manual Input Check
    manual_name = os.getenv("MANUAL_STUDENT_NAME")

    # 3. Main Processing Loop
    for file in files:
        file_id = file['id']
        file_name = file['name']
        
        try:
            print(f"\nProcessing File: {file_name}", flush=True)
            
            # 3.1. Audio Processing (Download, Mix, Analyze)
            local_audio_paths = []
            
            # --- Download/Extract Logic ---
            path = download_file(file_id, file_name)
            if file_name.lower().endswith('.zip'):
                local_audio_paths.extend(extract_audio_from_zip(path))
            else:
                local_audio_paths.append(path)
            
            if not local_audio_paths:
                print("⚠️ No valid audio tracks found after extraction. Skipping.", flush=True)
                continue
            
            mixed_path = mix_audio_files(local_audio_paths)
            
            # --- Result Generation ---
            full_analysis = analyze_audio_auto(mixed_path)
            
            if manual_name:
                # MANUAL PATH: Use manual name, keep AI summary
                final_student_name = manual_name
                print(f"✅ MANUAL MODE: Overriding name to '{final_student_name}'.", flush=True)
            else:
                # FULL AUTO PATH: Use AI's extracted name
                final_student_name = full_analysis['student_name']
                print(f"ℹ️ AUTO MODE: Using AI-extracted name '{final_student_name}'.", flush=True)

            # --- 4. Notion Search and Write ---
            # Search filter is now robust against minor errors using 'contains'
            search_filter = {
                "filter": {
                    "property": "Name",
                    "title": { "contains": final_student_name } 
                }
            }
            
            cc_res_data = notion_query_database(CONTROL_CENTER_ID, search_filter)
            results_list = cc_res_data.get("results", [])
            
            if not results_list:
                print(f"❌ Error: Student '{final_student_name}' not found in Control Center. Skipping write.", flush=True)
                continue 

            # 5. Extract Target ID and Write
            target_id_prop = results_list[0]["properties"].get("TargetID", {}).get("rich_text", [])
            
            if target_id_prop:
                final_target_id = sanitize_id(target_id_prop[0]["plain_text"])
                
                if final_target_id:
                    print(f"📝 Writing log to Target DB ID: {final_target_id}", flush=True)
                    
                    # 4. ページ作成 (Raw Request)
                    properties = {
                        "名前": {"title": [{"text": {"content": f"{full_analysis['date']} ログ"}}]},
                        "日付": {"date": {"start": full_analysis['date']}}
                    }
                    children = [
                        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": full_analysis['summary']}}]}},
                        {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "Next Action"}}]}},
                        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": full_analysis.get('next_action', 'なし')}}]}}
                    ]
                    
                    notion_create_page(final_target_id, properties, children)
                    
                    print(f"✅ Successfully updated Notion for {final_student_name}.", flush=True)
                    
                    # Clean up file
                    processed_folder_id = get_or_create_processed_folder()
                    move_files_to_processed([file_id], processed_folder_id)
                else:
                     print(f"❌ Error: TargetID in Control Center for {final_student_name} is invalid.", flush=True)
            
        except Exception as e:
             print(f"❌ UNHANDLED CRASH IN LOOP: {e}", flush=True)
        finally:
            if os.path.exists(TEMP_DIR): shutil.rmtree(TEMP_DIR)
            os.makedirs(TEMP_DIR) 

if __name__ == "__main__":
    main()
