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

# --- ライブラリ環境修復/初期化 ---
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

# --- 最終設定（外部変数はSecretsから取得） ---
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
    # Notion API用ヘッダー (Raw Request)
    NOTION_TOKEN = os.getenv("NOTION_TOKEN")
    HEADERS = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28" 
    }
    
    CONTROL_CENTER_ID = sanitize_id(FINAL_CONTROL_DB_ID)
    INBOX_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
    
    # Gemini & Drive Setup (省略)
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    SCOPES = ['https://www.googleapis.com/auth/drive']
    creds = service_account.Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=creds)
    
except Exception as e:
    print(f"❌ Setup Critical Error: {e}", flush=True)
    exit(1)

# --- Notion API 関数群 (Raw Requests) ---

def notion_query_database(db_id, query_filter):
    """データベースをクエリする"""
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
    # ★ DEBUG: ペイロードをログに出力
    print("\n[DEBUG: PAYLOAD SENT]", flush=True)
    print(json.dumps(payload, indent=2), flush=True)
    
    try:
        res = requests.post(url, headers=HEADERS, json=payload)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.HTTPError as e:
        print(f"❌ Notion Create Page Error: Status {e.response.status_code}")
        print(f"   Detail: {e.response.text}") # エラー詳細を出力
        raise e

# --- メイン処理 ---
def main():
    print("--- VERSION: FINAL DATA INTEGRATION (v33.0) ---", flush=True)
    
    if not INBOX_FOLDER_ID:
        print("❌ Error: DRIVE_FOLDER_ID is missing!", flush=True)
        return

    # 1. ファイル処理 (簡略化された実行パス - データを「でっていう(test)」に修正)
    result = {
        'student_name': 'でっていう(test)', 
        'date': '2025-11-28', 
        'summary': '着地狩りについてコーチングを行うセッション。', 
        'next_action': '次回の練習メニュー確認'
    }

    
    # --- 2. Notion検索 (Control Center) ---
    print(f"ℹ️ Control Center ID used: {CONTROL_CENTER_ID}", flush=True)
    
    # ★ 検索フィルターを「でっていう(test)」に修正
    search_filter = {
        "filter": {
            "property": "Name",
            "title": { "contains": result['student_name'] } 
        }
    }
    
    try:
        cc_res_data = notion_query_database(CONTROL_CENTER_ID, search_filter)
    except Exception as e:
        print(f"❌ CRITICAL FAILURE: Control Center Query failed. Error: {e}", flush=True)
        return

    # --- 3. 生徒データの抽出 ---
    results_list = cc_res_data.get("results", [])
    
    if results_list:
        target_id_prop = results_list[0]["properties"].get("TargetID", {}).get("rich_text", [])
        if target_id_prop:
            # ★ ユーザー提供のIDを使用: 2b91bc8521e381f7bcb4f3743dbc0327
            final_target_id = sanitize_id(target_id_prop[0]["plain_text"])

            if final_target_id:
                print(f"📝 Writing log to Target DB ID: {final_target_id}", flush=True)
                
                # 4. ページ作成 (Raw Request)
                properties = {
                    "名前": {"title": [{"text": {"content": f"{result['date']} ログ"}}]},
                    "日付": {"date": {"start": result['date']}}
                }
                children = [
                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": result['summary']}}]}},
                    {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "Next Action"}}]}},
                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": result.get('next_action', 'なし')}}]}}
                ]
                
                # ここでクラッシュする場合、Target IDデータそのものの問題が確定する
                notion_create_page(final_target_id, properties, children)
                
                print("✅ Successfully updated Notion.", flush=True)
            else:
                 print("❌ Error: TargetID in Notion is invalid.", flush=True)
        else:
            print("❌ Error: TargetID is empty in Control Center.", flush=True)
    else:
        print(f"❌ Error: Student '{result['student_name']}' not found in DB.", flush=True)

if __name__ == "__main__":
    main()
