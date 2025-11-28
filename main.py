import os
import sys
import subprocess

# 1. 必要なライブラリを入れる
try:
    import notion_client
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "notion-client"])
    import notion_client

from notion_client import Client

def main():
    print("=== 🕵️ NOTION DATABASE SCANNER STARTED ===", flush=True)
    
    # Secretsからトークンを取得
    token = os.getenv("NOTION_TOKEN")
    if not token:
        print("❌ Error: NOTION_TOKEN is missing in GitHub Secrets.", flush=True)
        return

    # Notionに接続
    try:
        notion = Client(auth=token)
        me = notion.users.me()
        print(f"🤖 Bot Name: {me['name']}", flush=True)
        print("✅ Token is valid. Scanning accessible databases...", flush=True)
    except Exception as e:
        print(f"❌ Connection Failed: {e}", flush=True)
        return

    # 全検索 (Search)
    try:
        # データベースだけを検索
        response = notion.search(filter={"value": "database", "property": "object"}).get("results")
        
        if not response:
            print("\n⚠️ No databases found!", flush=True)
            print("考えられる原因:")
            print("1. Botがまだどのページにも招待されていない")
            print("   -> Notion画面右上の「...」>「Connect to」でBotを追加してください")
            return

        print(f"\n🔍 Found {len(response)} databases:", flush=True)
        print("="*60, flush=True)
        
        for db in response:
            # タイトル取得
            title = "Untitled"
            if db.get("title") and len(db["title"]) > 0:
                title = db["title"][0]["plain_text"]
            
            db_id = db['id'].replace("-", "") # ハイフンなしID
            
            print(f"📂 Name : {title}", flush=True)
            print(f"🔑 ID   : {db_id}", flush=True)  # ★これが正解のID
            print(f"🔗 URL  : {db['url']}", flush=True)
            print("-" * 60, flush=True)

        print("\n✅ Scan Complete. Copy the 'ID' above.", flush=True)

    except Exception as e:
        print(f"❌ Search Error: {e}", flush=True)

if __name__ == "__main__":
    main()
