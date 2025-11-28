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
# (中略 - インストールコードは変更なし)

try:
    import requests
    import google.generativeai as genai
    from pydub import AudioSegment
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
except ImportError:
    # 実際にはここにインストールコードがあるが、透明性のために省略
    pass

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
    # Notion API用ヘッダー (Raw Request)
    NOTION_TOKEN = os.getenv("NOTION_TOKEN")
    HEADERS = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    CONTROL_CENTER_ID = sanitize_id(FINAL_CONTROL_DB_ID)
    INBOX_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
    
    # Gemini & Drive Setup
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
    # print("\n[DEBUG: PAYLOAD SENT]", flush=True) # デバッグログは省略
    # print(json.dumps(payload, indent=2), flush=True)
    
    try:
        res = requests.post(url, headers=HEADERS, json=payload)
        res.raise_for_status()
        return res.json()
    except requests.exceptions.HTTPError as e:
        print(f"❌ Notion Create Page Error: Status {e.response.status_code}")
        print(f"   Detail: {e.response.text}")
        raise e

# --- Audio/Drive/Gemini Helpers (Integration) ---

# download_file, extract_audio_from_zip, mix_audio_files は変更なし（省略）

def get_available_model_name():
    try:
        models = list(genai.list_models())
        available_names = [m.name for m in models if 'generateContent' in m.supported_generation_methods]
        
        # Syntax Error修正後のループ
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

# analyze_audio_auto は変更なし（省略）


# --- メイン処理 ---
def main():
    print("--- VERSION: FINAL TARGET ID CHECK (v35.0) ---", flush=True)
    
    if not os.getenv("DRIVE_FOLDER_ID"):
        print("❌ Error: DRIVE_FOLDER_ID is missing!", flush=True)
        return

    # 1. ファイル処理 (簡略化された実行パス)
    # ★FIX: 検索キーを「でっていう(test)」に変更
    STUDENT_NAME_TO_TEST = "でっていう(test)" 
    
    result = {
        'student_name': STUDENT_NAME_TO_TEST, 
        'date': '2025-11-29', 
        'summary': '【' + STUDENT_NAME_TO_TEST + 'さんのログ】着地狩りに関するコーチングセッションの動作検証。', 
        'next_action': 'TargetIDへの書き込み成功を確認する。'
    }

    
    # --- 2. Notion検索 (Control Center) ---
    print(f"ℹ️ Control Center ID used: {CONTROL_CENTER_ID}", flush=True)
    
    # ★FIX: 検索フィルターを新しい生徒名に変更
    search_filter = {
        "filter": {
            "property": "Name",
            "title": { "contains": STUDENT_NAME_TO_TEST } 
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
            final_target_id = sanitize_id(target_id_prop[0]["plain_text"])
            
            if final_target_id:
                print(f"📝 Target DB ID FOUND: {final_target_id[:6]}...", flush=True)
                
                # 4. ページ作成 (Raw Request)
                properties = {
                    "名前": {"title": [{"text": {"content": f"{result['date']} ログ (TEST)"}}]},
                    "日付": {"date": {"start": result['date']}}
                }
                children = [
                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": result['summary']}}]}},
                    {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": "Next Action"}}]}},
                    {"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"text": {"content": result.get('next_action', 'なし')}}]}}
                ]
                
                # ここでNotionへのページ作成が実行されます
                notion_create_page(final_target_id, properties, children)
                
                print(f"✅ SUCCESSFULLY WROTE LOG for {STUDENT_NAME_TO_TEST}.", flush=True)
                print(f"   Notionの '{STUDENT_NAME_TO_TEST}' さんのデータベースを確認してください。", flush=True)

            else:
                 print(f"❌ Error: TargetID in Control Center for {STUDENT_NAME_TO_TEST} is invalid/empty.", flush=True)
        else:
            print(f"❌ Error: TargetID property is empty/missing in Control Center for {STUDENT_NAME_TO_TEST}.", flush=True)
    else:
        print(f"❌ Error: Student '{STUDENT_NAME_TO_TEST}' not found in Control Center. (Name mismatch confirmed)", flush=True)

if __name__ == "__main__":
    main()
