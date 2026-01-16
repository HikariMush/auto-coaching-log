import os
import requests
import time
from concurrent.futures import ThreadPoolExecutor

# --- Config ---
# 消去対象のDB (ゴミが入ってしまったTheory DB)
TARGET_THEORY_DB_ID = "2e21bc8521e38029b8b1d5c4b49731eb" 
NOTION_TOKEN = os.getenv("NOTION_TOKEN")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def get_all_pages():
    """DB内の全ページのIDを取得"""
    pages = []
    has_more = True
    start_cursor = None
    
    print("🔍 Fetching pages to delete...", flush=True)
    
    while has_more:
        payload = {"page_size": 100}
        if start_cursor: payload["start_cursor"] = start_cursor
        
        try:
            res = requests.post(f"https://api.notion.com/v1/databases/{TARGET_THEORY_DB_ID}/query", headers=HEADERS, json=payload)
            data = res.json()
            results = data.get("results", [])
            pages.extend([p["id"] for p in results])
            
            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")
            print(f"   Found {len(pages)} pages so far...", end="\r", flush=True)
            
        except Exception as e:
            print(f"❌ Error fetching pages: {e}")
            break
            
    print(f"\n✅ Total pages found: {len(pages)}")
    return pages

def archive_page(page_id):
    """ページをアーカイブ（削除）する"""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {"archived": True}
    
    try:
        res = requests.patch(url, headers=HEADERS, json=payload)
        if res.status_code == 200:
            return True
        else:
            print(f"⚠️ Failed to archive {page_id}: {res.status_code}")
            return False
    except Exception:
        return False

def main():
    print("--- 🗑️ Notion Database Cleaner ---")
    print(f"Target DB: {TARGET_THEORY_DB_ID}")
    
    # 全件取得
    page_ids = get_all_pages()
    
    if not page_ids:
        print("🎉 Database is already empty!")
        return

    print(f"⚠️ DELETING {len(page_ids)} PAGES via API...")
    print("   (This helps you clear the garbage data automatically)")
    time.sleep(3) # 誤爆防止の猶予

    # 高速化のために並列処理 (Notion API Rate Limitに注意しつつ)
    # 3スレッドくらいが安全圏
    count = 0
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = executor.map(archive_page, page_ids)
        
        for res in results:
            if res: count += 1
            if count % 10 == 0:
                print(f"   Deleted {count}/{len(page_ids)} pages...", end="\r")

    print(f"\n✅ Cleanup Complete! Deleted {count} pages.")
    print("👉 Next Steps:")
    print("   1. run 'python reset_logs.py' (to uncheck source logs)")
    print("   2. run 'python generalize.py' (to rebuild clean data)")

if __name__ == "__main__":
    main()
