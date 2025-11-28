import os
import time
import json
import logging
import re
import zipfile
import shutil
from datetime import datetime

# Google Libraries
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Audio & Notion
from pydub import AudioSegment
from notion_client import Client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# --- 定数・初期化 ---
TEMP_DIR = "downloads"
if os.path.exists(TEMP_DIR):
    shutil.rmtree(TEMP_DIR)
os.makedirs(TEMP_DIR)

if os.getenv("GCP_SA_KEY"):
    with open("service_account.json", "w") as f:
        f.write(os.getenv("GCP_SA_KEY"))

try:
    notion = Client(auth=os.getenv("NOTION_TOKEN"))
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = service_account.Credentials.from_service_account_file(
        "service_account.json", scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)
    
    INBOX_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
    CONTROL_CENTER_ID = os.getenv("CONTROL_CENTER_ID")
    
except Exception as e:
    print(f"❌ Setup Critical Error: {e}", flush=True)
    exit(1)

# --- Drive操作関数 ---

def get_or_create_processed_folder():
    query = f"'{INBOX_FOLDER_ID}' in parents and name = 'Processed' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = drive_service.files().list(q=query, fields="files(id)").execute()
    files = results.get('files', [])
    if files: return files[0]['id']
    else:
        file_metadata = {'name': 'Processed', 'mimeType': 'application/vnd.google-apps.folder', 'parents': [INBOX_FOLDER_ID]}
        folder = drive_service.files().create(body=file_metadata, fields='id').execute()
        return folder['id']

def move_files_to_processed(file_ids, processed_folder_id):
    for file_id in file_ids:
        try:
            file = drive_service.files().get(fileId=file_id, fields='parents').execute()
            previous_parents = ",".join(file.get('parents'))
            drive_service.files().update(fileId=file_id, addParents=processed_folder_id, removeParents=previous_parents, fields='id, parents').execute()
            print(f"✅ File {file_id} moved to Processed.", flush=True)
        except Exception as e:
            print(f"⚠️ Failed to move file {file_id}: {e}", flush=True)

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

# --- AI & Notion ---

def analyze_audio_with_fallback(file_path):
    # 音声対応モデルのみに限定
    models_to_try = [
        'gemini-1.5-flash',
        'gemini-1.5-flash-001',
        'gemini-1.5-pro'
    ]

    last_error = None
    
    for model_name in models_to_try:
        print(f"🧠 Analyzing with model: {model_name} ...", flush=True)
        try:
            model = genai.GenerativeModel(model_name)
            audio_file = genai.upload_file(file_path)
            
            while audio_file.state.name == "PROCESSING":
                time.sleep(2)
                audio_file = genai.get_file(audio_file.name)
            
            if audio_file.state.name == "FAILED":
                raise ValueError("Gemini Audio Processing Failed")

            prompt = """
            以下の音声はコーチングセッションの録音です。
            以下の情報を抽出し、JSON形式のみを出力してください。Markdown装飾は不要です。
            {
              "student_name": "生徒の名前（Control Centerと一致させる。呼びかけから推測。不明なら'Unknown'）",
              "date": "YYYY-MM-DD",
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
                return json.loads(match.group(0))
            else:
                raise ValueError(f"Failed to parse JSON: {text}")

        except Exception as e:
            print(f"⚠️ Model {model_name} failed: {e}. Trying next...", flush=True)
            last_error = e
            time.sleep(1)
            continue
            
    raise last_error

def main():
    print("--- VERSION: FINAL COMPLETE 3.0 ---", flush=True)
    if not INBOX_FOLDER_ID:
        print("❌ Error: DRIVE_FOLDER_ID is empty!", flush=True)
        return

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
    print(f"Found {len(files)} files in inbox.", flush=True)
    
    if not files:
        print("ℹ️ No new files found. Exiting.", flush=True)
        return

    local_audio_paths = []
    processed_file_ids = []
    
    try:
        for f in files:
            print(f"📥 Downloading: {f['name']}", flush=True)
            path = download_file(f['id'], f['name'])
            processed_file_ids.append(f['id'])
            
            if f['name'].lower().endswith('.zip'):
                extracted = extract_audio_from_zip(path)
                local_audio_paths.extend(extracted)
                print(f"📦 Extracted {len(extracted)} files from zip.", flush=True)
            else:
                local_audio_paths.append(path)
        
        if not local_audio_paths:
            print("⚠️ No valid audio files found inside.", flush=True)
            processed_folder_id = get_or_create_processed_folder()
            move_files_to_processed(processed_file_ids, processed_folder_id)
            return

        mixed_path = mix_audio_files(local_audio_paths)
        
        # 解析実行
        result = analyze_audio_with_fallback(mixed_path)
        print(f"📊 Analysis Result: {result}", flush=True)
        
        # Notion書き込み
        print(f"🔍 Searching Control Center for: {result['student_name']}", flush=True)
        cc_res = notion.databases.query(
            database_id=CONTROL_CENTER_ID,
            filter={"property": "Name", "rich_text": {"equals": result['student_name']}}
        ).get("results")
        
        if cc_res:
            target_id_prop = cc_res[0]["properties"].get("TargetID", {}).get("rich_text", [])
            if target_id_prop:
                target_id = target_id_prop[0]["plain_text"]
                print(f"📝 Writing to Student DB: {target_id}", flush=True)
                
                notion.pages.create(
                    parent={"database_id": target_id},
                    properties={
                        "名前": {"title": [{"text": {"content": f"{result['date']} ログ"}}]},
                        "日付": {"date": {"start": result['date']}}
                    },
                    children=[
                        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": result['summary']}}]}}
                    ]
                )
                print("✅ Successfully updated Notion.", flush=True)
                
                processed_folder_id = get_or_create_processed_folder()
                move_files_to_processed(processed_file_ids, processed_folder_id)
            else:
                print("❌ Error: TargetID is empty in Control Center.", flush=True)
        else:
            print(f"❌ Error: Student '{result['student_name']}' not found in Control Center.", flush=True)

    except Exception as e:
        print(f"❌ Processing Failed: {e}", flush=True)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
