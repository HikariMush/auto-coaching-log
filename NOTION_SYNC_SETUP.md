# Smash Theory DB → Pinecone 同期セットアップ

## 📊 現状確認

| 項目 | 状態 | 説明 |
|------|------|------|
| `notion_sync.py` | ✅ 実装済み | 完全な Notion → Pinecone パイプライン |
| `.env` ファイル | ❌ 未作成 | API キー設定が必要 |
| Pinecone 同期 | ❓ 未確認 | 環境設定後に実行 |

---

## 🚀 実行手順（4ステップ）

### ステップ 1: 環境ファイルの準備

```bash
# .env ファイルを作成
cp .env.example .env

# テキストエディタで編集
nano .env  # または code .env
```

### ステップ 2: 必要な環境変数を設定

`.env` に以下を記入（既存のキーを上書き）:

```bash
# Google Gemini API キー
GEMINI_API_KEY=your_gemini_api_key_here

# Pinecone 設定
PINECONE_API_KEY=your_pinecone_api_key_here
PINECONE_INDEX_NAME=smash-zettel

# Notion 設定
NOTION_TOKEN=your_notion_integration_token_here
THEORY_DB_ID=2e21bc8521e38029b8b1d5c4b49731eb

# Discord Bot Token（別ファイルで使用）
DISCORD_BOT_TOKEN=your_discord_bot_token_here
```

### ステップ 3: 環境変数を確認

```bash
python -c "
import os
from dotenv import load_dotenv
load_dotenv()

print('✅ 環境変数チェック:')
for key in ['GEMINI_API_KEY', 'PINECONE_API_KEY', 'NOTION_TOKEN']:
    val = os.getenv(key)
    if val:
        print(f'  ✅ {key}: 設定済み')
    else:
        print(f'  ❌ {key}: 未設定')
"
```

### ステップ 4: Notion → Pinecone 同期を実行

```bash
# 1回目の同期（すべてのTheoryページを抽出）
python -m src.utils.notion_sync
```

**出力例:**
```
============================================================
🔗 Notion → Pinecone Sync
============================================================

1️⃣ Fetching Notion pages...
   Found 42 pages

2️⃣ Embedding and upserting to Pinecone...
  [2.4%] ✅ ガード硬直
  [4.8%] ✅ シールド削り値
  ...
  [100.0%] ✅ 転倒

☁️ Upserting 42 vectors to Pinecone...
  ✅ Batch 1/1

============================================================
✅ Sync complete: 42/42 pages synchronized
============================================================
```

---

## ⏰ 定期的な同期（オプション）

### オプション A: 手動で定期実行

毎日実行:
```bash
0 * * * * cd /workspaces/auto-coaching-log && python -m src.utils.notion_sync
```

crontab に登録:
```bash
crontab -e
# 上記行を追加
```

### オプション B: GitHub Actions で自動実行

`.github/workflows/sync-notion.yml` を作成:

```yaml
name: Daily Notion Sync
on:
  schedule:
    - cron: '0 2 * * *'  # 毎日 2 AM (UTC)
  workflow_dispatch:

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Sync Notion to Pinecone
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          PINECONE_API_KEY: ${{ secrets.PINECONE_API_KEY }}
          NOTION_TOKEN: ${{ secrets.NOTION_TOKEN }}
          THEORY_DB_ID: 2e21bc8521e38029b8b1d5c4b49731eb
        run: python -m src.utils.notion_sync
      
      - name: Commit changes
        run: |
          git add -A
          git commit -m "chore: Daily Notion sync" || true
          git push || true
```

### オプション C: Google Cloud Tasks で定期実行

Cloud Tasks UI で:
1. New Queue: `notion-sync-queue`
2. Schedule: Hourly (推奨)
3. HTTP Target: `https://your-cloud-run-url/sync-notion`

---

## 🔍 同期状態の確認

### Pinecone に保存されているか確認

```bash
python -c "
from pinecone import Pinecone
import os
from dotenv import load_dotenv

load_dotenv()
pc = Pinecone(api_key=os.getenv('PINECONE_API_KEY'))
index = pc.Index('smash-zettel')

# インデックス統計を表示
stats = index.describe_index_stats()
print(f'📊 Pinecone インデックス統計:')
print(f'  総ベクトル数: {stats.total_vector_count}')
print(f'  ディメンション: {stats.dimension}')

# サンプルベクトルを検索
results = index.query(
    vector=[0.1] * 768,  # ダミーベクトル
    top_k=3,
    include_metadata=True
)

print(f'\\n✅ 最近同期されたTheory:')
for match in results.matches:
    print(f'  • {match.metadata.get(\"title\", \"Unknown\")}')
    print(f'    source: {match.metadata.get(\"source\")}')
    print(f'    synced_at: {match.metadata.get(\"synced_at\")}')
"
```

---

## 🐛 トラブルシューティング

### エラー 1: NOTION_TOKEN が無効

**症状**: `Failed to fetch Notion pages: 401`

**解決**:
1. Notion で [Integrations](https://www.notion.so/my-integrations) にアクセス
2. 新しいインテグレーション作成 or 既存を確認
3. Secret Token をコピー → `.env` に貼り付け
4. Theory DB にインテグレーション権限を付与

### エラー 2: PINECONE_API_KEY が無効

**症状**: `Failed to upsert vectors: 401`

**解決**:
1. [Pinecone コンソール](https://console.pinecone.io) にアクセス
2. API キーを確認 → `.env` に貼り付け
3. インデックス名が `smash-zettel` か確認

### エラー 3: GEMINI_API_KEY が無効

**症状**: `Failed to embed content: 403`

**解決**:
1. [Google AI Studio](https://makersuite.google.com/app/apikey) にアクセス
2. API キーをコピー → `.env` に貼り付け
3. billing が有効か確認

### エラー 4: 同期が遅い

**症状**: 42ページで 5 分以上かかる

**原因**: Notion API rate limit (5 RPS)

**対策**:
- 通常動作（問題なし）
- バッチ処理を減らす場合は `optimize_coach.py` で調整

---

## 📈 期待される結果

**同期前:**
```
Pinecone インデックス: 空 (raw_data のみ)
Theory DB: 42ページ（Notion に存在）
Bot の知識ベース: 部分的
```

**同期後:**
```
Pinecone インデックス: 42+ ベクトル
  ├─ raw_data: ~50 ベクトル
  └─ Notion Theory: 42 ベクトル ✅
Bot の知識ベース: 完全
```

**検証方法:**
```bash
# Bot を起動して試す
python src/main.py

# Discord で以下を実行
/ask "ガード硬直について教えて"
# → Theory DB からの回答が含まれる
```

---

## 🎯 次のステップ

1. ✅ `.env` を設定
2. ✅ `python -m src.utils.notion_sync` を実行
3. ✅ Pinecone で確認
4. ✅ `python src/main.py` でボットを起動
5. ✅ `/ask` で Theory DB 知識を活用確認

---

## 📚 参考ドキュメント

- [OPTIMIZATION_FLOW_GUIDE.md](OPTIMIZATION_FLOW_GUIDE.md) - Step 2 参照
- [USER_CORRECTION_TO_OPTIMIZATION.md](USER_CORRECTION_TO_OPTIMIZATION.md) - Phase 1 参照
- [src/utils/notion_sync.py](src/utils/notion_sync.py) - 実装詳細

---

✨ **Smash Theory DB を Pinecone に同期して、ボットの知識ベースを完成させましょう！**
