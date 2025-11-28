import os
import sys
import subprocess
import logging

# --- ライブラリセットアップ ---
try:
    import notion_client
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "notion-client"])
    import notion_client

from notion_client import Client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def main():
    print("=== 🌟 V19.0: THE TRUTH EXTRACTOR (Ultimate ID Finder) 🌟 ===", flush=True)
    
    token = os.getenv("NOTION_TOKEN")
    if not token:
        print("❌ Error: NOTION_TOKEN is missing.", flush=True)
        return

    # 1. 接続確認
    try:
        notion = Client(auth=token)
        me = notion.users.me()
        print(f"🤖 Bot Name: {me['name']} (Token Verified)", flush=True)
    except Exception as e:
        print(f"❌ Connection Failed. Check NOTION_TOKEN: {e}", flush=True)
        return

    # 2. ページネーションを使った全検索
    print("\n🔍 Deep Search: Scanning ALL accessible objects (Overcoming 100-item limit)...", flush=True)
    has_more = True
    next_cursor = None
    total_objects = 0
    db_candidates = []

    try:
        while has_more:
            # ページとデータベースを全て検索 (APIエラー回避のためフィルタなし)
            response = notion.search(start_cursor=next_cursor, page_size=100)
            results = response.get("results", [])
            total_objects += len(results)
            
            for obj in results:
                # データベースのみを選別
                if obj["object"] == "database":
                    title_list = obj.get("title", [])
                    title = title_list[0]["plain_text"] if title_list else "Untitled"
                    db_id = obj['id'].replace("-", "") # ハイフンなしID
                    
                    db_candidates.append({
                        "id": db_id,
                        "title": title,
                        "url": obj['url']
                    })
            
            has_more = response.get("has_more")
            next_cursor = response.get("next_cursor")
            
        print(f"\nℹ️ Total {total_objects} objects scanned. Found {len(db_candidates)} databases.", flush=True)
        print("="*60, flush=True)
        
        if not db_candidates:
            print("❌ Critical Error: No databases found at all. Check connection.", flush=True)
            return

        for db in db_candidates:
            print(f"📂 Name : {db['title']}", flush=True)
            print(f"🔑 ID   : {db['id']}", flush=True) 
            print(f"🔗 URL  : {db['url']}", flush=True)
            print("-" * 60, flush=True)

        print("\n✅ Scan Complete. 上記のリストから「Control Center」の名前のデータベースIDをコピーしてください。", flush=True)

    except Exception as e:
        print(f"❌ Search Error (Pagination Failed): {e}", flush=True)

if __name__ == "__main__":
    main()
