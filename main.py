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

# --- 最終設定 ---
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

# (notion_create_page は省略)

# --- メイン処理 ---
def main():
    print("--- VERSION: TARGET ID READ TEST (v30.0) ---", flush=True)
    
    # 簡略化された実行パス（ここでは実際のファイル処理は省略）
    result = {'student_name': 'でっていう', 'date': '2025-11-28', 'summary': '着地狩りについてコーチングを行うセッション。', 'next_action': '次回の練習メニュー確認'}

    # 1. Control CenterのRead (成功するはず)
    search_filter = {"filter": {"property": "Name", "title": {"contains": result['student_name']}}}
    try:
        cc_res_data = notion_query_database(CONTROL_CENTER_ID, search_filter)
    except Exception as e:
        print("❌ CRITICAL FAILURE: Control Center Query failed. (This should not happen.)", flush=True)
        return

    # 2. Target IDの抽出
    results_list = cc_res_data.get("results", [])
    if not results_list:
        print("❌ CRITICAL: Student not found in Control Center.", flush=True)
        return

    target_id_prop = results_list[0]["properties"].get("TargetID", {}).get("rich_text", [])
    final_target_id = sanitize_id(target_id_prop[0]["plain_text"])
    
    print(f"\n[DEBUG] Extracted Target ID: {final_target_id}", flush=True)
    
    # 3. ★★★ 問題の Target ID に対して Read Query を実行 ★★★
    try:
        print("🔍 Testing problematic Target ID for existence...", flush=True)
        # 最もシンプルなクエリを実行 (フィルターなし)
        target_db_res = notion_query_database(final_target_id, {}) 
        
        print("✅ SUCCESS: Target Database is READABLE.", flush=True)
        print(f"ℹ️ Total rows found in target DB: {len(target_db_res.get('results', []))}", flush=True)
        
        # 成功の場合、最終的な書き込みロジックを実行
        # (ここでは簡略化し、成功したことを報告)
        print("\n🏆 PROJECT COMPLETE: Target ID verified. System is ready for write operation.")

    except Exception as e:
        # Read Queryが失敗した場合は、404の原因が確定
        print(f"❌ CRITICAL FAILURE: Target Database Read Failed. Error: {e}", flush=True)
        print("-> CONCLUSION: Target ID is NOT a valid/accessible database object. Please update Control Center data.", flush=True)

if __name__ == "__main__":
    main()
