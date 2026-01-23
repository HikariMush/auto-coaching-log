#!/usr/bin/env python3
"""
SmashZettel-Bot: One-Click Notion → Pinecone Sync Setup

This script handles complete setup and execution:
1. Check environment variables
2. Create .env if missing
3. Validate Notion/Pinecone connectivity
4. Run sync
5. Verify results
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv


def print_header(title):
    """Print a section header"""
    print(f"\n{'='*70}")
    print(f"🔗 {title}")
    print(f"{'='*70}\n")


def check_env_file():
    """Check and create .env if needed"""
    print_header("Step 1: Environment File Setup")
    
    env_path = Path('.env')
    example_path = Path('.env.example')
    
    if env_path.exists():
        print("✅ .env ファイルが存在します")
        return True
    
    if not example_path.exists():
        print("❌ .env.example が見つかりません")
        print("   このスクリプトは auto-coaching-log ディレクトリで実行してください")
        return False
    
    print("📝 .env ファイルを作成します...")
    try:
        env_content = example_path.read_text()
        env_path.write_text(env_content)
        print("✅ .env ファイルを作成しました")
        print("   → 以下のキーを .env に設定してください:")
        print("      GEMINI_API_KEY")
        print("      PINECONE_API_KEY")
        print("      NOTION_TOKEN")
        print("      THEORY_DB_ID (デフォルト: 2e21bc8521e38029b8b1d5c4b49731eb)")
        print("\n   コマンド: nano .env")
        return True
    except Exception as e:
        print(f"❌ .env 作成に失敗: {e}")
        return False


def validate_env_vars():
    """Validate required environment variables"""
    print_header("Step 2: Environment Variables Validation")
    
    load_dotenv()
    
    required = {
        'GEMINI_API_KEY': 'Google Gemini API キー',
        'PINECONE_API_KEY': 'Pinecone API キー',
        'NOTION_TOKEN': 'Notion インテグレーション トークン',
    }
    
    optional = {
        'THEORY_DB_ID': 'Notion Theory DB ID (デフォルト: 2e21bc8521e38029b8b1d5c4b49731eb)',
    }
    
    missing = []
    
    print("必須設定:")
    for key, desc in required.items():
        val = os.getenv(key)
        if val:
            display = val[:15] + '...' if len(val) > 15 else val
            print(f"  ✅ {key}: {display}")
        else:
            print(f"  ❌ {key}: 未設定")
            missing.append(key)
    
    print("\n任意設定:")
    for key, desc in optional.items():
        val = os.getenv(key)
        if val:
            print(f"  ✅ {key}: {val}")
        else:
            print(f"  ⚠️  {key}: 未設定 (デフォルト値を使用)")
    
    if missing:
        print(f"\n❌ 以下の環境変数が未設定です:")
        for key in missing:
            print(f"   • {key}")
        print("\n   .env を編集して、必要なキーを追加してください:")
        print("   $ nano .env")
        return False
    
    print("\n✅ 全ての環境変数が設定されています")
    return True


def test_connectivity():
    """Test connectivity to Notion and Pinecone"""
    print_header("Step 3: Connectivity Test")
    
    try:
        import requests
        print("  Notion API テスト中...")
        
        notion_token = os.getenv('NOTION_TOKEN')
        headers = {
            "Authorization": f"Bearer {notion_token}",
            "Notion-Version": "2022-06-28",
        }
        
        # Test Notion connectivity
        response = requests.get(
            "https://api.notion.com/v1/users/me",
            headers=headers,
            timeout=5
        )
        
        if response.status_code == 200:
            print("  ✅ Notion API: 接続成功")
        else:
            print(f"  ❌ Notion API: {response.status_code}")
            return False
        
    except Exception as e:
        print(f"  ❌ Notion API テスト失敗: {e}")
        return False
    
    try:
        print("  Pinecone API テスト中...")
        from pinecone import Pinecone
        
        pc = Pinecone(api_key=os.getenv('PINECONE_API_KEY'))
        pc.list_indexes()
        print("  ✅ Pinecone API: 接続成功")
        
    except Exception as e:
        print(f"  ❌ Pinecone API テスト失敗: {e}")
        return False
    
    try:
        print("  Gemini API テスト中...")
        from google import genai
        
        genai.configure(api_key=os.getenv('GEMINI_API_KEY'))
        result = genai.embed_content(
            model="models/embedding-001",
            content="test"
        )
        print("  ✅ Gemini API: 接続成功")
        
    except Exception as e:
        print(f"  ❌ Gemini API テスト失敗: {e}")
        return False
    
    print("\n✅ 全ての API に正常に接続できます")
    return True


def run_sync():
    """Run the actual Notion → Pinecone sync"""
    print_header("Step 4: Notion → Pinecone Sync")
    
    try:
        from src.utils.notion_sync import sync_notion_to_pinecone
        
        result = sync_notion_to_pinecone(verbose=True)
        
        if result['status'] == 'success':
            print(f"\n✅ 同期完了:")
            print(f"   • 取得ページ数: {result['pages_fetched']}")
            print(f"   • 同期ページ数: {result['pages_synced']}")
            return True
        else:
            print(f"\n❌ 同期失敗: {result.get('errors', 'Unknown error')}")
            return False
            
    except Exception as e:
        print(f"❌ 同期実行エラー: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_results():
    """Verify that sync was successful"""
    print_header("Step 5: Verification")
    
    try:
        from pinecone import Pinecone
        
        pc = Pinecone(api_key=os.getenv('PINECONE_API_KEY'))
        index = pc.Index('smash-zettel')
        
        stats = index.describe_index_stats()
        print(f"Pinecone インデックス統計:")
        print(f"  • 総ベクトル数: {stats.total_vector_count}")
        print(f"  • ディメンション: {stats.dimension}")
        
        if stats.total_vector_count > 40:  # At least Notion pages
            print("\n✅ Notion Theory ページが Pinecone に保存されています")
            
            # Show sample vectors
            results = index.query(
                vector=[0.1] * 768,
                top_k=3,
                include_metadata=True
            )
            
            if results.matches:
                print("\n📚 サンプル (最近同期されたTheory):")
                for match in results.matches:
                    title = match.metadata.get('title', 'Unknown')
                    source = match.metadata.get('source', '?')
                    print(f"   • {title} (source: {source})")
            
            return True
        else:
            print(f"\n⚠️  ベクトル数が少なくなっています: {stats.total_vector_count}")
            print("   → 同期が完了していない可能性があります")
            return False
            
    except Exception as e:
        print(f"❌ 検証エラー: {e}")
        return False


def main():
    """Main execution"""
    print("\n" + "="*70)
    print("🚀 SmashZettel-Bot: Notion → Pinecone Sync Setup")
    print("="*70)
    
    # Step 1: Environment file
    if not check_env_file():
        print("\n❌ セットアップが中断されました")
        print("   → .env ファイルを作成して、API キーを設定してください")
        sys.exit(1)
    
    # Step 2: Validate environment variables
    if not validate_env_vars():
        print("\n❌ 環境変数が不足しています")
        print("   → .env を編集して、必要なキーを追加してください")
        sys.exit(1)
    
    # Step 3: Test connectivity
    if not test_connectivity():
        print("\n❌ API への接続に失敗しました")
        print("   → 環境変数が正しいか確認してください")
        sys.exit(1)
    
    # Step 4: Run sync
    print("\n⚠️  これから Notion → Pinecone の同期を開始します")
    print("   (5-10 分かかる場合があります)")
    response = input("\n続行しますか？ (y/n): ").strip().lower()
    
    if response != 'y':
        print("キャンセルしました")
        sys.exit(0)
    
    if not run_sync():
        print("\n❌ 同期に失敗しました")
        sys.exit(1)
    
    # Step 5: Verify
    if not verify_results():
        print("\n⚠️  検証に失敗しました")
        print("   → エラーメッセージを確認して、トラブルシューティングしてください")
        sys.exit(1)
    
    print("\n" + "="*70)
    print("✅ 完了: Smash Theory DB が Pinecone に同期されました！")
    print("="*70)
    print("\n🎯 次のステップ:")
    print("   1. ボットを起動: $ python src/main.py")
    print("   2. Discord で /ask コマンドを試す")
    print("   3. Theory DB からの回答を確認")
    print("\n📚 詳細はこちら: NOTION_SYNC_SETUP.md")


if __name__ == '__main__':
    main()
