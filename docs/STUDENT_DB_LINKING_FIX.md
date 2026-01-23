# 生徒DBとの紐づけ問題の修正

## 問題の概要

コーチングログの要約はコーチ側のFallback DBには正常に保存されるが、生徒DBには保存されない問題が発生していた。

## 原因分析

### 問題の根本原因

[`main.py`](../main.py)の825-835行で、Fallback DB（コーチ側）と生徒DBに**同じプロパティ構造**を使用していた：

```python
props = {
    "名前": {"title": [...]},  # 日本語プロパティ
    "日付": {"date": {...}}
}

# 両方のDBに同じpropsを使用
notion_create_page_heavy(FINAL_FALLBACK_DB_ID, props, ...)  # OK
notion_create_page_heavy(did, props, ...)  # NG - プロパティ名が違う
```

しかし、生徒DBとFallback DBは**異なるプロパティ構造**を持つ：

| データベース | Title プロパティ | Date プロパティ |
|------------|----------------|----------------|
| Fallback DB (コーチ側) | `名前` (日本語) | `日付` (日本語) |
| Student DB (生徒側) | `Name` (英語) | `Date` (英語) |

このため、生徒DBへの保存時にプロパティ名が一致せず、Notion APIがエラーを返していた。

### データフロー

```
録音ファイル (Craig録音)
    ↓
Google Drive 取得
    ↓
音声処理 (FFmpeg + Groq Whisper)
    ↓
Gemini 分析 → 生徒名抽出
    ↓
生徒レジストリ検索 (FINAL_CONTROL_DB)
    ↓
┌─────────────────────┬──────────────────────┐
│ Fallback DB 保存    │ 生徒DB 保存          │
│ ✅ 日本語props使用  │ ❌ 日本語props使用   │
│ → 成功              │ → プロパティ不一致   │
└─────────────────────┴──────────────────────┘
```

## 実装した修正

### 1. プロパティ構造の分離 (Line 825-841)

```python
# コーチ側のFallback DB用プロパティ（日本語）
fallback_props = {
    "名前": {"title": [{"text": {"content": f"{precise_datetime} {oname} 通話ログ"}}]}, 
    "日付": {"date": {"start": date_only}}
}

print("💾 Saving to Fallback DB (All Data)...")
notion_create_page_heavy(sanitize_id(FINAL_FALLBACK_DB_ID), copy.deepcopy(fallback_props), copy.deepcopy(final_blocks))

# 生徒DB用プロパティ（英語 - Notion DB標準）
if did and did != FINAL_FALLBACK_DB_ID:
    student_props = {
        "Name": {"title": [{"text": {"content": f"{precise_datetime} {oname} 通話ログ"}}]}, 
        "Date": {"date": {"start": date_only}}
    }
    print(f"👤 Saving to Student DB ({oname})...")
    notion_create_page_heavy(sanitize_id(did), copy.deepcopy(student_props), copy.deepcopy(final_blocks))
```

### 2. セーフモード処理の改善 (Line 633-657)

エラー時のフォールバック処理を両言語のプロパティに対応：

```python
def notion_create_page_heavy(db_id, props, children):
    # ...初回POST試行...
    if res.status_code != 200:
        print(f"⚠️ Initial Post Failed ({res.status_code}). Retrying with SAFE MODE...", flush=True)
        print(f"   Error Details: {res.text}", flush=True)
        
        # 日本語プロパティ（コーチDB）と英語プロパティ（生徒DB）の両方に対応
        content_text = props.get("名前", props.get("Name", {})).get("title", [{}])[0].get("text", {}).get("content", "Log")
        safe_props = {"Name": {"title": [{"text": {"content": content_text}}]}}
        
        # 日付も両方のプロパティに対応
        date_val = props.get("日付", props.get("Date", {})).get("date", {}).get("start", "Unknown")
        # ...セーフモードで再試行...
```

## 期待される動作

### 修正前

```
📂 Processing: 2026-01-23_craig_recording.zip
🧠 Gemini Analyzing... → 生徒名: "キャム kiyamu"
🎯 Fuzzy Match: 'kiyamu' -> 'キャム kiyamu'
💾 Saving to Fallback DB (All Data)...
✅ Notion Page Created: https://notion.so/...
👤 Saving to Student DB (キャム kiyamu)...
⚠️ Initial Post Failed (400). Retrying with SAFE MODE...
❌ NOTION SAFE MODE FAILED: 400
   → 生徒DBには保存されない
```

### 修正後

```
📂 Processing: 2026-01-23_craig_recording.zip
🧠 Gemini Analyzing... → 生徒名: "キャム kiyamu"
🎯 Fuzzy Match: 'kiyamu' -> 'キャム kiyamu'
💾 Saving to Fallback DB (All Data)...
✅ Notion Page Created: https://notion.so/...
👤 Saving to Student DB (キャム kiyamu)...
✅ Notion Page Created: https://notion.so/...
   → 生徒DBにも正常に保存される ✅
```

## テスト方法

### 手動テスト

1. Craig録音ファイル（生徒Discord IDを含む）をGoogle Driveのinboxフォルダに配置
2. `python main.py` を実行
3. ログを確認：
   - "💾 Saving to Fallback DB" → 成功
   - "👤 Saving to Student DB" → 成功（以前は失敗していた）
4. Notionで両方のDBを確認

### 確認ポイント

- [ ] Fallback DBに要約が保存されている
- [ ] 生徒DBにも同じ要約が保存されている
- [ ] 生徒DBのページに「Name」「Date」プロパティが正しく設定されている
- [ ] ページ内容（分析、課題、Mermaidフローチャート等）が完全である

## 関連ファイル

- [`main.py`](../main.py) - メイン処理ファイル（修正済み）
- Line 36: `FINAL_CONTROL_DB_ID` - 生徒マスターDB ID
- Line 37: `FINAL_FALLBACK_DB_ID` - コーチ側Fallback DB ID
- Line 209-242: `load_student_registry()` - レジストリ読み込み
- Line 244-251: `find_best_student_match()` - Fuzzyマッチング
- Line 633-657: `notion_create_page_heavy()` - Notion保存処理（修正済み）
- Line 825-841: プロパティ構造分離（修正済み）

## 追加の改善提案

### 1. プロパティ名の動的検出

現在はハードコードされたプロパティ名を使用していますが、Notion APIの`/databases/{id}`エンドポイントで実際のプロパティを取得すると、より堅牢になります。

### 2. ログの詳細化

生徒DB保存の成功/失敗をより明確に記録し、デバッグを容易にします。

### 3. リトライロジック

一時的なネットワークエラーに対応するため、指数バックオフを使用したリトライ機構を追加します。

## 変更履歴

- **2026-01-23**: 初回修正 - プロパティ構造の分離とセーフモード改善
