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
    print("=== 🕵️ NOTION DATABASE SCANNER (v2) STARTED ===", flush=True)
    
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
        print("✅ Token is valid. Scanning ALL accessible objects...", flush=True)
    except Exception as e:
        print(f"❌ Connection Failed: {e}", flush=True)
        return

    # 全検索 (フィルタなし)
    try:
        # APIに「全部くれ」と命令
        response = notion.search().get("results")
        
        if not response:
            print("\n⚠️ No objects found!", flush=True)
            print("Botがどのページにも招待されていません。Notion右上の「...」>「Connect to」を確認してください。")
            return

        db_count = 0
        print(f"\n🔍 Filtering Databases from {len(response)} objects:", flush=True)
        print("="*60, flush=True)
        
        for obj in response:
            # ここでデータベースだけを選別
            if obj["object"] == "database":
                db_count += 1
                # タイトル取得
                title_list = obj.get("title", [])
                title = title_list[0]["plain_text"] if title_list else "Untitled"
                
                db_id = obj['id'].replace("-", "") # ハイフンなしID
                
                print(f"📂 Name : {title}", flush=True)
                print(f"🔑 ID   : {db_id}", flush=True)  # ★これが正解のID
                print(f"🔗 URL  : {obj['url']}", flush=True)
                print("-" * 60, flush=True)

        if db_count == 0:
            print("⚠️ ページは見つかりましたが、データベースが見つかりません。")
            print("   Control Centerは「ページ」ではなく「データベース」ですか？")
        else:
            print(f"\n✅ Scan Complete. Found {db_count} databases.", flush=True)
            print("上記の 'ID' (32桁) をコピーして保存してください。", flush=True)

    except Exception as e:
        print(f"❌ Search Error: {e}", flush=True)

if __name__ == "__main__":
    main()
