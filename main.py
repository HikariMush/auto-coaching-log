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

# --- 【最終テストID】実績はあるがAPIに拒否されているIDを固定 ---
FINAL_CONTROL_CENTER_ID = "2b71bc8521e380f99a16f512232eeb11" # 貴殿が使用しているID

# --- ライブラリ環境修復（省略） ---
# (中略：ライブラリ設定、初期化、ヘルパー関数はv20.0と同じ)
# ...
from notion_client import Client
# ...
# --- 初期化・設定（省略） ---
# ...

def main():
    print("--- VERSION: FINAL ID TEST (v21.0) ---", flush=True)
    print(f"ℹ️ Target Database ID: {CONTROL_CENTER_ID}", flush=True)
    
    if not INBOX_FOLDER_ID:
        print("❌ Error: DRIVE_FOLDER_ID is empty!", flush=True)
        return

    # (中略：ファイルのダウンロードと解析ロジックはv20.0と同じ)
    # ...
    
    try:
        # この部分は省略し、IDテストに特化します
        # ここに解析結果のダミーデータを挿入し、Notionアクセスのみテスト
        result = {'student_name': 'でっていう', 'date': '2025-11-28', 'summary': 'テスト実行', 'next_action': 'なし'}
        
        print(f"🔍 Executing simplest query on ID: {CONTROL_CENTER_ID}", flush=True)
        
        # V21.0: 最もシンプルな、フィルター無しのデータベースクエリを実行
        cc_res = notion.request(
            path=f"databases/{CONTROL_CENTER_ID}/query",
            method="POST",
            body={} # 空のボディで、フィルターなしの全件取得を試みる
        )
        
        # ここまで到達すれば、IDは有効
        print("✅ SUCCESS: Database ID is valid!", flush=True)
        results_list = cc_res.get("results", [])
        print(f"ℹ️ Found {len(results_list)} rows in the database.", flush=True)
        
        # 成功した場合、既存の処理に戻る（ここではログ出力のみ）
        print("--- TEST COMPLETE: ID IS VALID ---", flush=True)
        
    except Exception as e:
        print(f"❌ ID Test Failed: {e}", flush=True)
        print("--- TEST COMPLETE: ID IS INVALID ---", flush=True)
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
