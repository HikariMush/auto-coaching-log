import os
import sys
import subprocess
import time
import json
import logging
import re
import requests # requestsを必ずインポート

# --- ライブラリ環境修復/初期化 (簡略化) ---
try:
    import requests
    # 必要なライブラリのimportは省略
except ImportError:
    # インストールコードは省略
    import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# --- 最終設定（Notion IDのみ定義） ---
FINAL_CONTROL_DB_ID = "2b71bc8521e380868094ec506b41f664" 

def sanitize_id(raw_id):
    if not raw_id: return None
    match = re.search(r'([a-fA-F0-9]{32})', str(raw_id).replace("-", ""))
    if match: return match.group(1)
    return None

try:
    # Notion API用ヘッダー
    NOTION_TOKEN = os.getenv("NOTION_TOKEN")
    HEADERS = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28" 
    }
    CONTROL_CENTER_ID = sanitize_id(FINAL_CONTROL_DB_ID)
    
except Exception as e:
    print(f"❌ Setup Critical Error: {e}", flush=True)
    exit(1)

# --- Notion API 関数群 (Raw Requests) ---

def notion_query_database(db_id, query_filter={}):
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

# --- メイン処理 ---
def main():
    print("--- VERSION: CONTROL CENTER NAME EXTRACTION (v32.0) ---", flush=True)
    
    # 1. Control Centerの全件クエリを実行 (Filterなし = 全件取得)
    try:
        # 全件取得（フィルターなし）
        cc_res_data = notion_query_database(CONTROL_CENTER_ID, {}) 
    except Exception as e:
        print(f"❌ CRITICAL FAILURE: Control Center Query failed. Error: {e}", flush=True)
        return

    # 2. 生徒名の抽出
    results_list = cc_res_data.get("results", [])
    
    if results_list:
        student_names = []
        for result in results_list:
            # 'Name'プロパティから生徒名を抽出（NotionのTitleプロパティ）
            name_prop = result["properties"].get("Name", {}).get("title", [])
            if name_prop and name_prop[0].get("plain_text"):
                student_names.append(name_prop[0]["plain_text"])
        
        print("\n✅ Control Center Names List Dumped:", flush=True)
        print(json.dumps(student_names, ensure_ascii=False, indent=2), flush=True)
    else:
        print("❌ Error: Control Center returned no entries.", flush=True)

if __name__ == "__main__":
    main()
