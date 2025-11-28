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
    import notion_client
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "notion-client"])
    import notion_client

# 必要な外部ライブラリをインポート
try:
    import google.generativeai as genai
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from pydub import AudioSegment
    from notion_client import Client
    from googleapiclient.http import MediaIoBaseDownload
except ImportError as e:
    print(f"❌ Critical Import Error: {e}")
    # 依存関係が不足しているため、外部で解決させる
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "google-generativeai notion-client pydub google-api-python-client google-auth google-auth-httplib2"])
    from notion_client import Client # 再度インポートを試みる (実行時には再起動されるため問題なし)


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# --- 設定と初期化 ---
FINAL_CONTROL_CENTER_ID = "2b71bc8521e380f99a16f512232eeb11" # ★修正：このIDで最終テスト
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
    CONTROL_CENTER_ID = sanitize_id(FINAL_CONTROL_CENTER_ID) # ★最終的に使用するID
    
    notion = Client(auth=os.getenv("NOTION_TOKEN"))
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)
    
except Exception as e:
    print(f"❌ Setup Critical Error: {e}", flush=True)
    exit(1)

# --- テスト対象関数 (簡略化) ---
def download_file(file_id, file_name):
    # [ダウンロードロジック]
    request = drive_service.files().get_media(fileId=file_id)
    file_path = os.path.join(TEMP_DIR, file_name)
    with open(file_path, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
    return file_path

def main():
    print("--- VERSION: FINAL ID TEST (v21.1) ---", flush=True)
    # ★NameError修正済み
    print(f"ℹ️ Target Database ID: {FINAL_CONTROL_CENTER_ID}", flush=True) 
    
    if not os.getenv("DRIVE_FOLDER_ID"):
        print("❌ Error: DRIVE_FOLDER_ID is missing!", flush=True)
        return

    # 1. Notion API IDテスト
    try:
        # フィルター無し、最もシンプルなデータベースクエリ（body={}}）を実行
        cc_res = notion.request(
            path=f"databases/{CONTROL_CENTER_ID}/query",
            method="POST",
            body={} 
        )
        
        # ここまで到達すれば、IDは有効
        print("✅ SUCCESS: Database ID is VALID for unfiltered query!", flush=True)
        results_list = cc_res.get("results", [])
        print(f"ℹ️ Found {len(results_list)} rows in the database.", flush=True)
        
        print("--- TEST COMPLETE: ID IS VALID ---", flush=True)
        
    except Exception as e:
        print(f"❌ CRASH: ID Test Failed: {e}", flush=True)
        print("--- TEST COMPLETE: ID IS INVALID ---", flush=True)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
