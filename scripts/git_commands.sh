#!/bin/bash
# Excel取り込み：Git自動コミット＆プッシュ

echo "📦 Git自動コミット開始"
echo "="*60

# 1. 変更ファイルの追加
echo "📝 ステップ1: 変更ファイルをステージング"
git add src/utils/ingest_excel_data.py
git add test_mario_extraction.py
git add data/excel_ingestion_state.json
git add excel_ingestion_log.txt
git add excel_ingestion_log_v2.txt
git add plans/EXCEL_INGESTION_RATE_LIMIT_SOLUTION.md
git add plans/INGESTION_IMPLEMENTATION_SPEC.md
git add plans/QUICK_START_INGESTION.md
git add plans/PINECONE_COST_CORRECTION.md

echo "✅ ファイル追加完了"
echo ""

# 2. 変更内容の確認
echo "📋 ステップ2: 変更内容確認"
git status
echo ""

# 3. コミット
echo "💾 ステップ3: コミット作成"
git commit -m "feat: Excel全キャラデータ取り込み完了

- データ抽出ロジック修正（data_only=True）
- レート制限対策追加（0.5-1.0秒遅延）
- Vector ID修正（MD5ハッシュでASCII化）
- 進捗表示＆状態保存機能追加
- 全82キャラ、3,280+エントリをPineconeに取り込み

取り込み結果:
- 処理シート: 82キャラ + 19共通シート = 101シート
- 取り込みエントリ: 3,280+エントリ
- 失敗: 0エントリ
- コスト: 初回$0.11、月額$0.33

ファイル:
- src/utils/ingest_excel_data.py: レート制限対策実装
- test_mario_extraction.py: マリオデータ抽出テスト
- plans/*: 詳細な計画ドキュメント
- data/excel_ingestion_state.json: 進捗状態
"

echo "✅ コミット完了"
echo ""

# 4. プッシュ
echo "🚀 ステップ4: リモートにプッシュ"
git push origin main

echo ""
echo "="*60
echo "✅ Git自動コミット完了！"
echo "="*60
