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
    import notion_client
    import importlib.metadata
except ImportError:
    print("🔄 Installing core libraries...", flush=True)
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "--upgrade", 
        "google-generativeai", 
        "notion-client", 
        "pydub",
        "google-api-python-client", 
        "google-auth"
    ])
    import google.generativeai as genai
    from notion_client import Client
    from pydub import AudioSegment

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from notion_client import Client
from pydub import AudioSegment


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# --- 設定と初期化 ---
# ★重要: 通知Botで実績のあるIDに固定
FINAL_CONTROL_DB_ID = "2b71bc8521e380868094ec506b41f664"

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
    # 環境変数からロード
    CONTROL_CENTER_ID = sanitize_id(FINAL_CONTROL_DB_ID)
    
    notion = Client(auth=os.getenv("NOTION_TOKEN"))
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)
    
except Exception as e:
    print(f"❌ Setup Critical Error: {e}", flush=True)
    exit(1)

# --- テスト対象関数 (簡略化) ---
def main():
    print("--- VERSION: FINAL ID TEST (v22.0) ---", flush=True)
    
    # ★NameError修正済み
    print(f"ℹ️ Target Database ID: {FINAL_CONTROL_DB_ID}", flush=True) 
    
    if not os.getenv("DRIVE_FOLDER_ID"):
        print("❌ Error: DRIVE_FOLDER_ID is missing!", flush=True)
        return

    # 1. Notion API IDテスト
    try:
        # V22.0: フィルター無し、最もシンプルなデータベースクエリを実行
        # これが成功すれば、IDと権限はOK。
        cc_res = notion.request(
            path=f"databases/{CONTROL_CENTER_ID}/query",
            method="POST",
            body={} # 空のボディで、フィルターなしの全件取得を試みる
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
