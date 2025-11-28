import os
import time
import json
import logging
import re
import zipfile
import shutil
from datetime import datetime
from dotenv import load_dotenv

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
    shutil.rmtree(TEMP_DIR) # クリーンスタート
os.makedirs(TEMP_DIR)

# GitHub SecretsからJSONキーを復元
if os.getenv("GCP_SA_KEY"):
    with open("service_account.json", "w") as f:
        f.write(os.getenv("GCP_SA_KEY"))

try:
    notion = Client(auth=os.getenv("NOTION_TOKEN"))
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    model = genai.GenerativeModel('gemini-1.5-pro')
    
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = service_account.Credentials.from_service_account_file(
        "service_account.json", scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)
    
    INBOX_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
    CONTROL_CENTER_ID = os.getenv("CONTROL_CENTER_ID")
    
except Exception as e:
    logging.error(f"Setup Error: {e}")
    exit(1)

# --- Drive操作関数 ---

def get_or_create_processed_folder():
    """処理済みフォルダのIDを取得、なければ作成"""
    query = f"'{INBOX_FOLDER_ID}' in parents and name = 'Processed' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = drive_service.files().list(q=query, fields="files(id)").execute()
    files = results.get('files', [])
    
    if files:
        return files[0]['id']
    else:
        file_metadata = {
            'name': 'Processed',
            'mimeType': 'application/vnd.google-apps.folder',
            'parents': [INBOX_FOLDER_ID]
        }
        folder = drive_service.files().create(body=file_metadata, fields='id').execute()
        return folder['id']

def move_files_to_processed(file_ids, processed_folder_id):
    """ファイルをProcessedフォルダに移動"""
    for file_id in file_ids:
        try:
            file = drive_service.files().get(fileId=file_id, fields='parents').execute()
            previous_parents = ",".join(file.get('parents'))
            drive_service.files().update(
                fileId=file_id,
                addParents=processed_folder_id,
                removeParents=previous_parents,
                fields='id, parents'
            ).execute()
            logging.info(f"Moved file {file_id} to Processed folder.")
        except Exception as e:
            logging.warning(f"Failed to move file {file_id}: {e}")

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
    """ZIPを解凍し、中の音声ファイルパスのリストを返す"""
    extracted_files = []
    extract_dir = os.path.join(TEMP_DIR, "extracted_" + os.path.basename(zip_path))
    
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_dir)
        
    for root, dirs, files in os.walk(extract_dir):
        for file in files:
            # 音声ファイルっぽい拡張子ならリストに追加
            if file.lower().endswith(('.flac', '.mp3', '.aac', '.wav', '.m4a')):
                extracted_files.append(os.path.join(root, file))
    
    return extracted_files

def mix_audio_files(file_paths):
    if not file_paths: return None
    logging.info(f"Mixing {len(file_paths)} audio tracks...")
    
    try:
        mixed = AudioSegment.from_file(file_paths[0])
        for path in file_paths[1:]:
            track = AudioSegment.from_file(path)
            mixed = mixed.overlay(track)
        
        output_path = os.path.join(TEMP_DIR, "mixed_session.mp3")
        mixed.export(output_path, format="mp3")
        return output_path
    except Exception as e:
        logging.error(f"Mixing Error: {e}")
        # ミックスに失敗したら、安全策として「一番大きいファイル」を単体で返す（何もしないよりマシ）
        longest_file = max(file_paths, key=os.path.getsize)
        return longest_file

# --- AI & Notion ---

def analyze_audio(file_path):
    logging.info("Analyzing with Gemini...")
    audio_file = genai.upload_file(file_path)
    
    # 待機処理
    while audio_file.state.name == "PROCESSING":
        time.sleep(5)
        audio_file = genai.get_file(audio_file.name)
    
    if audio_file.state.name == "FAILED":
        raise ValueError("Gemini Audio Processing Failed")

    prompt = """
    以下の音声はコーチングセッションの録音です。
    以下の情報を抽出し、JSON形式のみを出力してください。
    
    {
      "student_name": "生徒の名前（呼びかけから推測。Control Centerと一致させる。不明なら'Unknown'）",
      "date": "YYYY-MM-DD",
      "summary": "セッション要約（300文字以内）",
      "next_action": "次回の宿題"
    }
    """
    try:
        response = model.generate_content([prompt, audio_file])
        genai.delete_file(audio_file.name)
        
        text = response.text.strip()
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match: return json.loads(match.group(0))
        else: raise ValueError(f"Failed to parse JSON: {text}")
    except Exception as e:
        # エラー時もファイル削除を試みる
        try: genai.delete_file(audio_file.name)
        except: pass
        raise e

def main():
    # 1. Inboxにあるファイルを取得
    results = drive_service.files().list(
        q=f"'{INBOX_FOLDER_ID}' in parents and mimeType != 'application/vnd.google-apps.folder' and trashed = false",
        fields="files(id, name, createdTime)",
        orderBy="createdTime desc"
    ).execute()
    
    files = results.get('files', [])
    
    if not files:
        logging.info("No new files found.")
        return

    local_audio_paths = [] # 解凍済み音声ファイルのリスト
    processed_file_ids = [] # 移動対象の元のファイルIDリスト
    
    try:
        # 全ファイルをダウンロード & ZIPなら解凍
        for f in files:
            logging.info(f"Downloading: {f['name']}")
            path = download_file(f['id'], f['name'])
            processed_file_ids.append(f['id'])
            
            if f['name'].lower().endswith('.zip'):
                extracted = extract_audio_from_zip(path)
                local_audio_paths.extend(extracted)
                logging.info(f"Extracted {len(extracted)} files from zip.")
            else:
                local_audio_paths.append(path)
        
        if not local_audio_paths:
            logging.warning("No audio files found inside the downloads.")
            return

        # 合成
        mixed_path = mix_audio_files(local_audio_paths)
        
        # 解析
        result = analyze_audio(mixed_path)
        
        logging.info(f"Analysis Result: {result}")
        
        # Notion書き込み
        cc_res = notion.databases.query(
            database_id=CONTROL_CENTER_ID,
            filter={"property": "Name", "rich_text": {"equals": result['student_name']}}
        ).get("results")
        
        if cc_res:
            target_id_prop = cc_res[0]["properties"].get("TargetID", {}).get("rich_text", [])
            if target_id_prop:
                target_id = target_id_prop[0]["plain_text"]
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
                logging.info("✅ Successfully updated Notion.")
                
                # 成功したら移動
                processed_folder_id = get_or_create_processed_folder()
                move_files_to_processed(processed_file_ids, processed_folder_id)
                
            else:
                logging.error("TargetID is empty in Control Center.")
        else:
            logging.error(f"Student {result['student_name']} not found in Control Center.")

    except Exception as e:
        logging.error(f"Processing Failed: {e}")
        # エラー時は移動しない（リトライさせる）

if __name__ == "__main__":
    main()
