# プロジェクト構造リファクタリング計画

## 現状の問題点

### 1. ファイル名の混乱
- `main.py` - コーチングログ自動処理（Google Drive監視）
- `src/main.py` - Discord Bot（/askコマンド等）
- `discord_bot.py` - 別のDiscord Bot実装？

→ **同じような名前で異なる機能**を持つファイルが複数存在し、混乱を招いている

### 2. 自動実行の頻度
- 現在：1日2回（0:00、12:00 UTC = JST 9:00、21:00）
- 問題：Craig録音がDriveに入っても、最大12時間待機が必要
- 要望：録音が入るたびに順次処理したい

### 3. ワークフロー名の不明確さ
- `run_bot.yml` - 実際にはコーチングログ処理
- `discord_server.yml` - Discord Bot（無効化済み）
- `manage_data.yml` - データ管理

## リファクタリング提案

### Phase 1: ファイル名の整理

#### 変更内容

| 現在のファイル | 新しいファイル | 機能 |
|--------------|--------------|-----|
| `main.py` | `coaching_log_processor.py` | コーチングログの自動処理 |
| `discord_bot.py` | `discord_bot_legacy.py` | レガシーBot（非推奨） |
| `src/main.py` | `src/discord_bot.py` | メインのDiscord Bot |

#### ディレクトリ構造（リファクタリング後）

```
.
├── coaching_log_processor.py   # コーチングログ自動処理（旧 main.py）
├── discord_bot_legacy.py       # レガシーBot（旧 discord_bot.py）
├── requirements.txt
├── README.md
├── .github/
│   └── workflows/
│       ├── auto_coaching_log.yml       # コーチングログ処理（旧 run_bot.yml）
│       ├── discord_bot.yml             # Discord Bot（旧 discord_server.yml）
│       └── data_management.yml         # データ管理（旧 manage_data.yml）
├── src/
│   ├── discord_bot.py          # Discord Bot メイン（旧 src/main.py）
│   ├── brain/                  # AI推論エンジン
│   └── utils/                  # ユーティリティ
└── scripts/                    # 各種スクリプト
```

### Phase 2: 自動実行頻度の改善

#### オプションA: cron頻度を上げる（推奨）

```yaml
schedule:
  - cron: '0 */2 * * *'  # 2時間ごと（1日12回）
  # または
  - cron: '*/30 * * * *'  # 30分ごと（1日48回）
```

**メリット**:
- 実装が簡単
- 最大待機時間が短縮（2時間 or 30分）

**デメリット**:
- GitHub Actions実行回数が増加（無料枠: 月2000分）
- 処理時間が長い場合、並列実行のリスク

#### オプションB: Google Drive Webhook（将来的）

Google Drive APIの変更通知機能を使用：

```python
# watch APIでフォルダを監視
drive_service.files().watch(
    fileId=INBOX_FOLDER_ID,
    body={
        'type': 'web_hook',
        'address': 'https://your-webhook-endpoint.com/drive-notify'
    }
)
```

**メリット**:
- 完全なリアルタイム処理
- 無駄な実行が減る

**デメリット**:
- Webhookエンドポイントのホスティングが必要
- 実装が複雑

#### オプションC: GitHub Actions + Repository Dispatch

外部トリガーでワークフローを起動：

```bash
# 録音終了時に外部から実行
curl -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/repos/HikariMush/auto-coaching-log/dispatches \
  -d '{"event_type":"new_recording"}'
```

**推奨案**: まずは**オプションA（2時間ごと）**を実装し、様子を見る。

### Phase 3: 依存関係の整理

#### 各ファイルの依存関係

**`coaching_log_processor.py` (旧 main.py)**
- 依存: Google Drive API、Groq、Gemini、Notion API、FFmpeg
- 機能: 録音ファイルの取得、音声処理、文字起こし、分析、Notion保存
- 実行方法: `python coaching_log_processor.py`

**`src/discord_bot.py` (旧 src/main.py)**
- 依存: Discord.py、DSPy、Pinecone、Gemini
- 機能: /askコマンド、/teachコマンド
- 実行方法: `python -m src.discord_bot`

**`discord_bot_legacy.py` (旧 discord_bot.py)**
- 確認が必要：現在の用途は？
- 判断: 使用していない場合は削除候補

## 実装ステップ

### Step 1: ファイルリネーム（破壊的変更なし）

```bash
# 1. コーチングログ処理のリネーム
git mv main.py coaching_log_processor.py

# 2. レガシーBotのリネーム（使用状況を確認後）
git mv discord_bot.py discord_bot_legacy.py

# 3. Discord Botのリネーム
git mv src/main.py src/discord_bot.py
```

### Step 2: import文の更新

各ファイルで以下を確認・修正：
- `from src.main import ...` → `from src.discord_bot import ...`
- ドキュメント内の参照も更新

### Step 3: ワークフロー更新

```bash
# ワークフローファイルのリネームと内容修正
git mv .github/workflows/run_bot.yml .github/workflows/auto_coaching_log.yml
git mv .github/workflows/discord_server.yml .github/workflows/discord_bot.yml
git mv .github/workflows/manage_data.yml .github/workflows/data_management.yml
```

### Step 4: 実行コマンドの修正

**auto_coaching_log.yml**:
```yaml
# Before
run: python main.py

# After
run: python coaching_log_processor.py
```

**auto_coaching_log.ymlのcron設定**:
```yaml
schedule:
  - cron: '0 */2 * * *'  # 2時間ごと
```

### Step 5: ドキュメント更新

- README.md の更新
- 各種ドキュメント内の参照を修正
- 新しいファイル構造の図を追加

## 実装順序

1. ✅ **計画作成**（このドキュメント）
2. ⬜ **discord_bot.pyの用途確認**（削除すべきか判断）
3. ⬜ **ファイルリネーム実行**
4. ⬜ **import文とパス修正**
5. ⬜ **ワークフロー修正**
6. ⬜ **自動実行頻度変更（2時間ごと）**
7. ⬜ **動作確認**
8. ⬜ **ドキュメント更新**

## リスク管理

### リスク1: 既存のワークフローが動かなくなる
- **対策**: ブランチで作業し、PRでレビュー後にマージ
- **復旧方法**: `git revert` で元に戻す

### リスク2: cronの頻度を上げすぎてGitHub Actions無料枠を使い切る
- **対策**: 
  - 最初は2時間ごとから開始
  - Actions使用時間を監視
  - 必要に応じて調整

### リスク3: 並列実行による競合
- **対策**: ワークフローに`concurrency`設定を追加
  ```yaml
  concurrency:
    group: coaching-log-processing
    cancel-in-progress: false  # 前の実行を待つ
  ```

## 期待される効果

### ファイル名の明確化
- ✅ 各ファイルの役割が名前から理解できる
- ✅ 新規参加者の学習コストが下がる
- ✅ メンテナンスが容易になる

### 自動実行の改善
- ✅ 録音後の待機時間が最大12時間→2時間に短縮
- ✅ より迅速なフィードバック提供が可能
- ✅ 手動実行の手間が削減

## 次のステップ

このリファクタリング計画について承認を得た後、Step 2から実装を開始します。

質問：
1. `discord_bot.py` は現在使用していますか？削除しても問題ないですか？
2. 自動実行の頻度は2時間ごとで良いですか？（30分ごとも可能）
3. 今すぐ実装を開始して良いですか？
