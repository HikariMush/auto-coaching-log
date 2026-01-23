# プロジェクト構造リファクタリング完了報告

## 実施日
2026-01-23

## 変更内容

### 1. ファイルリネーム

| 変更前 | 変更後 | 理由 |
|--------|--------|------|
| `main.py` | `coaching_log_processor.py` | 機能が明確に（コーチングログの自動処理） |
| `src/main.py` | `src/discord_bot_dspy.py` | DSPy版の代替実装であることを明示 |
| `.github/workflows/run_bot.yml` | `.github/workflows/auto_coaching_log.yml` | ワークフローの目的を明確化 |
| `.github/workflows/discord_server.yml` | `.github/workflows/discord_bot.yml` | より直感的な名前 |
| `.github/workflows/manage_data.yml` | `.github/workflows/data_management.yml` | 英語表記に統一 |

### 2. 自動実行頻度の改善

**変更前**: 1日2回（UTC 0:00, 12:00 = JST 9:00, 21:00）
**変更後**: 15分ごと（1日96回）

#### コスト計算
- GitHub Actions無料枠: 月2,000分
- 推定使用時間:
  - ファイルなし時: ~30秒 × 90回 = 45分
  - ファイルあり時: ~10分 × 6回 = 60分
  - 月間合計: ~1,575分 ✅ 無料枠内

#### 並列実行防止
```yaml
concurrency:
  group: coaching-log-processing
  cancel-in-progress: false
```

### 3. ワークフロー設定の改善

#### auto_coaching_log.yml
- タイトル変更: "SZ Auto Logger Ultimate" → "Auto Coaching Log Processor"
- cron設定: `0 0,12 * * *` → `*/15 * * * *`
- 実行コマンド: `python main.py` → `python coaching_log_processor.py`
- 並列実行防止機能追加

#### discord_bot.yml
- タイトル更新: "Run Discord Bot (DISABLED)" → "Discord Bot (SmashZettel)"
- 環境変数の整理（PINECONE_API_KEY追加）

#### data_management.yml
- タイトル変更: "Manage Smash Data (Manual)" → "Data Management (Manual)"

### 4. ドキュメント更新

- [`README.md`](../README.md): ディレクトリ構造と実行方法を更新
- [`plans/PROJECT_RESTRUCTURE_PLAN.md`](../plans/PROJECT_RESTRUCTURE_PLAN.md): 詳細な計画書作成

## 使用中のファイル構成

### Discord Bot
- **メイン**: [`discord_bot.py`](../discord_bot.py)（使用中）
  - `/ask` - 質問応答
  - `/teach` - フィードバック
  - `/teach_element` - 要素別フィードバック
  - `/add_knowledge` - 一般知識追加
  - `/status` - Bot状態確認
  - スレッド会話機能

- **代替実装**: [`src/discord_bot_dspy.py`](../src/discord_bot_dspy.py)
  - DSPy準拠の実装
  - `/ask`, `/teach`のみ

### コーチングログ処理
- [`coaching_log_processor.py`](../coaching_log_processor.py)
  - Craig録音の自動処理
  - Google Drive監視
  - 音声処理（FFmpeg + Groq Whisper）
  - Gemini分析
  - Notion DB保存（コーチ側 + 生徒側）
  - 15分ごとに自動実行

## 実行方法

### Discord Bot起動
```bash
# メインBot（推奨）
python discord_bot.py

# DSPy版（開発用）
python -m src.discord_bot_dspy
```

### コーチングログ処理（手動）
```bash
python coaching_log_processor.py
```

### 自動実行
- GitHub Actionsで15分ごとに自動実行
- 手動実行: GitHub > Actions > "Auto Coaching Log Processor" > "Run workflow"

## 期待される効果

### 明確性の向上
✅ ファイル名から機能が即座に理解できる
✅ 新規参加者の学習コストが低下
✅ ワークフローの目的が明確

### 処理速度の向上
✅ 録音後の待機時間: 最大12時間 → 最大15分
✅ より迅速なフィードバック提供
✅ 手動実行の必要性がほぼ消滅

### 保守性の向上
✅ 各ファイルの役割が明確化
✅ ワークフロー名が直感的
✅ 並列実行の競合を防止

## テスト結果

### 構文チェック
```bash
✅ python -m py_compile coaching_log_processor.py
✅ python -m py_compile discord_bot.py
```

### Git管理
```bash
✅ git mv main.py coaching_log_processor.py
✅ git mv src/main.py src/discord_bot_dspy.py
✅ git mv .github/workflows/* (3ファイル)
```

## 既知の問題と対策

### 問題1: ワークフローの頻繁な実行による通知スパム
- **対策**: GitHub Actionsの通知設定で失敗時のみ通知

### 問題2: 無料枠超過のリスク
- **対策**: 
  - Actions使用時間を定期的に監視
  - 必要に応じてcronを`*/30 * * * *`（30分ごと）に調整

### 問題3: ファイルがない場合の無駄な実行
- **現状**: 15分ごとに確認し、ファイルがなければ即終了（~30秒）
- **将来の改善案**: Google Drive Webhook導入で完全なイベント駆動に

## 次のステップ

### 短期（1週間以内）
- [ ] Actions使用時間を監視
- [ ] 15分間隔が適切か評価
- [ ] 生徒DBとの紐づけが正常に動作するか確認

### 中期（1ヶ月以内）
- [ ] エラー率の測定
- [ ] 処理時間の最適化
- [ ] ログの充実化

### 長期（3ヶ月以内）
- [ ] Google Drive Webhook導入の検討
- [ ] 複数リージョンでの冗長化
- [ ] コスト効率の再評価

## 参考ドキュメント

- [リファクタリング計画](../plans/PROJECT_RESTRUCTURE_PLAN.md)
- [生徒DB紐づけ修正](STUDENT_DB_LINKING_FIX.md)
- [README](../README.md)

## 変更履歴

- **2026-01-23**: 初回リファクタリング完了
  - ファイルリネーム
  - 自動実行頻度を15分ごとに変更
  - ワークフロー設定の改善
  - ドキュメント更新
