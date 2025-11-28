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
    import google.generativeai as genai
    import importlib.metadata
    ver = importlib.metadata.version("google-generativeai")
    if ver < "0.8.3": raise ImportError
    import notion_client
except Exception:
    print("🔄 Installing libraries...", flush=True)
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "--upgrade", 
        "google-generativeai>=0.8.3", 
        "notion-client", 
        "pydub"
    ])
    import google.generativeai as genai

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from pydub import AudioSegment
from notion_client import Client, APIResponseError

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# --- 定数・初期化 ---
TEMP_DIR = "downloads"
if os.path.exists(TEMP_DIR):
    shutil.rmtree(TEMP_DIR)
os.makedirs(TEMP_DIR)

if os.getenv("GCP_SA_KEY"):
    with open("service_account.json", "w") as f:
        f.write(os.getenv("GCP_SA_KEY"))

# IDクリーニング
def sanitize_id(raw_id):
    if not raw_id: return None
    match = re.search(r'([a-fA-F0-9]{32})', str(raw_id).replace("-", ""))
    if match: return match.group(1)
    return None

try:
    INBOX_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
    CONTROL_CENTER_ID = sanitize_id(os.getenv("CONTROL_CENTER_ID"))
    
    notion = Client(auth=os.getenv("NOTION_TOKEN"))
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = service_account.Credentials.from_service_account_file(
        "service_account.json", scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)
    
except Exception as e:
    print(f"❌ Setup Critical Error: {e}", flush=True)
    exit(1)

# --- ★重要：Notion接続診断機能 ---
def check_database_connection():
    print(f"🔍 Diagnosing Control Center ID: {CONTROL_CENTER_ID[:4]}...{CONTROL_CENTER_ID[-4:]}", flush=True)
    
    if not CONTROL_CENTER_ID:
        print("❌ Error: Control Center ID is invalid.", flush=True)
        return False

    try:
        # まずデータベースとして取得できるか試す
        db = notion.databases.retrieve(database_id=CONTROL_CENTER_ID)
        print(f"✅ Connection OK! Database Name: {db['title'][0]['plain_text'] if db['title'] else 'Untitled'}", flush=True)
        return True
    except APIResponseError as e:
        if e.code == "object_not_found":
            print("❌ Error: ID not found. (Check permissions? Did you invite the bot?)", flush=True)
        elif e.status == 400:
            print("❌ Error: This ID is not a Database. It might be a Page ID.", flush=True)
            print("👉 Fix: Open Notion, click the '...' next to the database title (not the page corner), 'Copy link', and extract that ID.", flush=True)
        else:
            print(f"❌ Connection Error: {e}", flush=True)
        return False

# --- 通常関数 ---

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

def get_available_model_name():
    try:
        models = list(genai.list_models())
        available_names = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        # 優先順位: 2.0 -> 1.5
        for name in available_names:
            if 'gemini-2.0-flash' in name and 'exp' not in name: return name
        for name in available_names:
            if 'gemini-2.5-flash' in name: return name
        for name in available_names:
            if 'gemini-2.0-flash' in name: return name
        for name in available_names:
            if 'flash' in name: return name
        return available_names[0]
    except:
        return 'models/gemini-2.0-flash'

def analyze_audio_auto(file_path):
    model_name = get_available_model_name()
    print(f"🧠 Analyzing with model: {model_name} ...", flush=True)
    try:
        model = genai.GenerativeModel(model_name)
        audio_file = genai.upload_file(file_path)
        
        while audio_file.state.name == "PROCESSING":
            time.sleep(2)
            audio_file = genai.get_file(audio_file.name)
        
        if audio_file.state.name == "FAILED": raise ValueError("Audio Failed")

        # ★プロンプト改善：不明でも聞こえた名前を出すように指示
        prompt = """
        以下の音声はコーチングセッションの録音です。
        以下の情報を抽出し、JSON形式のみを出力してください。Markdown装飾は不要です。
        
        【生徒名の抽出ルール】
        1. 会話中の呼びかけ（「〇〇さん」）から名前を特定してください。
        2. もし登録名と一致するか不明でも、聞こえたままの音（カタカナやニックネーム）を入力してください。
        3. 絶対に 'Unknown' にせず、候補を挙げてください。
        
        {
          "student_name": "生徒の名前（例: Tetu, デッティー, 田中）",
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
        if match: return json.loads(match.group(0))
        else: raise ValueError("JSON Parse Failed")
    except Exception as e:
        print(f"❌ Analysis Failed: {e}", flush=True)
        raise e

def main():
    print("--- VERSION: DIAGNOSTIC & RELAXED PROMPT (v10.0) ---", flush=True)
    
    # 1. 起動時診断
    if not check_database_connection():
        print("⛔ System stopped due to Notion ID error.", flush=True)
        # IDエラーでも処理済み移動はしない（リトライのため）
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
        print("ℹ️ No new files found.", flush=True)
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
            print("⚠️ No valid audio files found.", flush=True)
            processed_folder_id = get_or_create_processed_folder()
            move_files_to_processed(processed_file_ids, processed_folder_id)
            return

        mixed_path = mix_audio_files(local_audio_paths)
        result = analyze_audio_auto(mixed_path)
        print(f"📊 Analysis Result: {result}", flush=True)
        
        if result['student_name'] == 'Unknown':
            print("⚠️ Student Name is Unknown. Skipping Notion search to avoid error.", flush=True)
            # Unknownなら移動せず終了（次回リトライ、または手動確認用）
            return

        print(f"🔍 Searching Control Center for: {result['student_name']}", flush=True)
        
        # ライブラリの正規メソッドを使用（診断が通っていれば動くはず）
        cc_res = notion.databases.query(
            database_id=CONTROL_CENTER_ID,
            filter={
                "property": "Name",
                "rich_text": {"equals": result['student_name']}
            }
        )
        
        results_list = cc_res.get("results", [])
        
        if results_list:
            target_id_prop = results_list[0]["properties"].get("TargetID", {}).get("rich_text", [])
            if target_id_prop:
                target_id = sanitize_id(target_id_prop[0]["plain_text"])
                print(f"📝 Writing to Student DB: {target_id}", flush=True)
                
                notion.pages.create(
                    parent={"database_id": target_id},
                    properties={
                        "名前": {"title": [{"text": {"content": f"{result['date']} ログ"}}]},
                        "日付": {"date": {"start": result['date']}}
                    },
                    children=[
                        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": result['summary']}}]}},
                        {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "Next Action"}}]}},
                        {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": result.get('next_action', 'なし')}}]}}
                    ]
                )
                print("✅ Successfully updated Notion.", flush=True)
                
                processed_folder_id = get_or_create_processed_folder()
                move_files_to_processed(processed_file_ids, processed_folder_id)
            else:
                print("❌ Error: TargetID is empty in Control Center.", flush=True)
        else:
            print(f"❌ Error: Student '{result['student_name']}' not found in Control Center.", flush=True)
            print("ℹ️ Hint: Check if the name in Notion matches exactly (Case sensitive / Kanji / Katakana).", flush=True)

    except Exception as e:
        print(f"❌ Processing Failed: {e}", flush=True)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
