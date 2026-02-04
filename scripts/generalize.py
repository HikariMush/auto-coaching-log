import os
import sys
import time
import json
import requests
import re
from google import genai
from google.genai import types

# --- Environment Variable Validation ---
def validate_environment():
    """環境変数をチェックし、不足している場合はエラーを出力して終了"""
    required_vars = ["NOTION_TOKEN", "GEMINI_API_KEY"]
    missing_vars = []
    
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print("❌ CRITICAL ERROR: Missing required environment variables!", flush=True)
        for var in missing_vars:
            print(f"   - {var}", flush=True)
        print("\n📝 Please set these variables in your .env file or GitHub Actions secrets:", flush=True)
        print("   NOTION_TOKEN: Your Notion integration token")
        print("   GEMINI_API_KEY: Your Google Gemini API key")
        sys.exit(1)

# Run validation at script start
validate_environment()

# --- Config ---
SOURCE_LOG_DB_ID = "2e01bc8521e380ffaf28c2ab9376b00d"
TARGET_THEORY_DB_ID = "2e21bc8521e38029b8b1d5c4b49731eb"

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# --- Dynamic Model Resolver ---
def resolve_best_model():
    client = genai.Client(api_key=GEMINI_API_KEY)
    print("💎 Querying Google API for the absolute latest models...", flush=True)

    try:
        # 1. APIから利用可能な全モデルを動的に取得
        all_models = list(client.models.list())
        candidates = []
        
        for m in all_models:
            # モデルIDの抽出 (例: models/gemini-1.5-pro -> gemini-1.5-pro)
            name = m.name.replace("models/", "")
            
            # 生成モデルのみを対象にする (embeddingやvision単体モデルを除外)
            if "gemini" in name and "vision" not in name and "embedding" not in name:
                candidates.append(name)

        # 2. 最強モデルを決めるためのスコアリングロジック
        def model_score(name):
            score = 0
            # バージョン判定 (数字が大きいほど偉い)
            version_match = re.search(r"(\d+\.\d+)", name)
            if version_match:
                version = float(version_match.group(1))
                score += version * 1000  # 2.5 -> 2500, 2.0 -> 2000
            
            # グレード判定
            if "ultra" in name: score += 300
            elif "pro" in name: score += 200
            elif "flash" in name: score += 100
            
            # 最新・実験的モデルの優先 (Expは最新機能が入っていることが多い)
            if "exp" in name: score += 50
            if "thinking" in name: score += 20 # 思考プロセス付きならさらに加点
            
            # 安定版(001, 002等)より最新の日付付きを優先したい場合などはここで調整
            # ここではシンプルにバージョンとPro/Flash基準とする
            return score

        # スコアが高い順にソート
        candidates.sort(key=model_score, reverse=True)
        
        print(f"📋 Detected Candidates (Top 5): {candidates[:5]}", flush=True)

        # 3. 上から順に疎通テスト (Rate Limitなどで使えないやつはスキップ)
        for model in candidates:
            try:
                client.models.generate_content(
                    model=model, 
                    contents="Test",
                    config=types.GenerateContentConfig(response_mime_type="text/plain")
                )
                print(f"✅ ACTIVATED STRONGEST MODEL: {model}", flush=True)
                return model
            except Exception as e:
                # 権限がない、廃止された、RateLimitなどの場合は次へ
                continue

    except Exception as e:
        print(f"❌ Failed to list models dynamically: {e}")
    
    # 万が一全滅した場合の最後の砦 (ここには来ないはずだが念の為)
    print("⚠️ Dynamic resolution failed. Fallback to hardcoded safe model.")
    return "gemini-1.5-pro"

ACTIVE_MODEL_ID = None

# --- Notion API Helpers ---
def get_page_content(page_id):
    all_text = ""
    has_more = True
    start_cursor = None
    while has_more:
        url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"
        if start_cursor: url += f"&start_cursor={start_cursor}"
        try:
            res = requests.get(url, headers=HEADERS)
            if res.status_code != 200: break
            data = res.json()
            for block in data.get("results", []):
                btype = block.get("type")
                if not btype or "rich_text" not in block.get(btype, {}): continue
                text_list = block[btype].get("rich_text", [])
                line = "".join([t.get("text", {}).get("content", "") for t in text_list])
                if line: all_text += line + "\n"
            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")
        except: break
    return all_text

def mark_log_as_processed(page_id):
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {"properties": {"AI処理済み": {"checkbox": True}}}
    try:
        requests.patch(url, headers=HEADERS, json=payload)
        print(f"   ☑️ Marked as processed: {page_id}")
    except Exception as e:
        print(f"   ⚠️ Failed to mark processed: {e}")

def text_to_blocks(text):
    blocks = []
    lines = text.split('\n')
    for line in lines:
        if not line.strip(): continue
        ct = line.replace('**', '')[:1900]
        if line.startswith('### '):
            blocks.append({"object":"block", "type":"heading_3", "heading_3":{"rich_text":[{"text":{"content":ct[4:]}}]}})
        elif line.startswith('## '):
            blocks.append({"object":"block", "type":"heading_2", "heading_2":{"rich_text":[{"text":{"content":ct[3:]}}]}})
        elif line.startswith('- '):
            blocks.append({"object":"block", "type":"bulleted_list_item", "bulleted_list_item":{"rich_text":[{"text":{"content":ct[2:]}}]}})
        else:
            blocks.append({"object":"block", "type":"paragraph", "paragraph":{"rich_text":[{"text":{"content":ct}}]}})
    return blocks

# --- Gemini Logic ---
def generate_theories(log_text):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""
    あなたはスマブラのコーチングログ分析AIです。
    入力されたログから「理論(Theory)」を抽出し、構造化データに変換してください。
    
    【分析ルール】
    1. **Scope判定**: 
       - その理論は「全キャラ共通の一般論」か、「特定のキャラ対」か？
       - 値は必ず **"全般"** または **"キャラ対"** のいずれかにすること。
    
    2. **Category (複数可)**:
       - 該当するカテゴリをリスト形式で全て抽出せよ。
       - 選択肢: 復帰阻止, 復帰, 崖上がり, 崖狩り, 立ち回り, 思考, メンタル, 撃墜, 撃墜拒否, コンボ, その他

    3. **キャラクター抽出**:
       - Player Char: 使用キャラ（不明/全般なら "全般"）。
       - Target Char: 対策対象（Scopeが"全般"なら空欄）。
       - 名称は「スマブラSPの日本語正式名称」。

    Format (JSON Array):
    [
      {{
        "theory_name": "タイトル (30文字以内)",
        "scope": "全般" | "キャラ対", 
        "categories": ["復帰阻止", "撃墜"], 
        "player_char": "クラウド",
        "target_char": "ネス",
        "importance": "S",
        "tags": ["ジャンプ読み", "空前"],
        "abstract": "3行要約",
        "detail": "### 解説\\n詳細な理論。", 
        "source_context": "元ログからの引用"
      }}
    ]

    Log Content:
    {log_text[:25000]}
    """
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            res = client.models.generate_content(
                model=ACTIVE_MODEL_ID, 
                contents=prompt, 
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            return json.loads(res.text)
        except Exception as e:
            if "429" in str(e) or "Resource exhausted" in str(e):
                print(f"⚠️ Rate Limit hit ({ACTIVE_MODEL_ID}). Waiting 30s...", flush=True)
                time.sleep(30)
                continue
            else:
                print(f"Gemini Error: {e}")
                return []
    return []

# --- Save Logic ---
def save_theory(theory, log_id):
    target_char = theory.get("target_char", "")
    if target_char == "全般": target_char = None 
    
    raw_cats = theory.get("categories", [])
    if isinstance(raw_cats, str): raw_cats = [raw_cats]
    
    props = {
        "Theory Name": {"title": [{"text": {"content": theory.get("theory_name", "Untitled")}}]},
        "Category": {"multi_select": [{"name": c} for c in raw_cats]},
        "Scope": {"select": {"name": theory.get("scope", "全般")}},
        "Player Char": {"select": {"name": theory.get("player_char", "全般")}}, 
        "Target Char": {"select": {"name": target_char}} if target_char else {"select": None},
        "Importance": {"select": {"name": theory.get("importance", "B (状況限定)")}},
        "Abstract": {"rich_text": [{"text": {"content": theory.get("abstract", "")}}]},
        "Source Log": {"relation": [{"id": log_id}]},
        "Verification": {"status": {"name": "Draft"}},
        "Tags": {"multi_select": [{"name": t} for t in theory.get("tags", [])]}
    }
    
    children = []
    if "source_context" in theory:
        children.append({
            "object":"block", "type":"callout", 
            "callout":{
                "rich_text":[{"text":{"content": f"Source: {theory['source_context'][:1900]}"}}],
                "icon": {"emoji": "💡"}
            }
        })
    children.extend(text_to_blocks(theory.get("detail", "")))

    try:
        res = requests.post(
            "https://api.notion.com/v1/pages", 
            headers=HEADERS, 
            json={"parent": {"database_id": TARGET_THEORY_DB_ID}, "properties": props, "children": children}
        )
        if res.status_code == 200:
            print(f"✅ Saved: [{theory.get('scope')}] {theory.get('theory_name')}")
        else:
            print(f"❌ Save Failed ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"❌ Network Error: {e}")

# --- Main ---
def main():
    global ACTIVE_MODEL_ID
    print("--- Generalization Started (Dynamic Latest-Model Search Mode) ---", flush=True)
    
    try:
        # 待機ループ: 有効なモデルが見つかるまで粘る
        max_model_wait = 10  # 最大10回試行（最大600秒）
        attempt = 0
        while attempt < max_model_wait:
            ACTIVE_MODEL_ID = resolve_best_model()
            if ACTIVE_MODEL_ID:
                print(f"✅ Model resolved: {ACTIVE_MODEL_ID}", flush=True)
                break
            attempt += 1
            print(f"⏳ Waiting 60s for models to become available... (Attempt {attempt}/{max_model_wait})", flush=True)
            time.sleep(60)
        
        if not ACTIVE_MODEL_ID:
            print("❌ CRITICAL: Could not resolve any model after max attempts", flush=True)
            sys.exit(1)

        has_more = True
        error_count = 0
        max_consecutive_errors = 5
        
        while has_more:
            query = {
                "filter": {
                    "property": "AI処理済み",
                    "checkbox": {"equals": False}
                },
                "page_size": 10,
                "sorts": [{"property": "日付", "direction": "descending"}]
            }
            
            try:
                res = requests.post(
                    f"https://api.notion.com/v1/databases/{SOURCE_LOG_DB_ID}/query",
                    headers=HEADERS,
                    json=query,
                    timeout=30
                )
                if res.status_code != 200:
                    print(f"⚠️ Notion API error ({res.status_code}): {res.text[:200]}", flush=True)
                    error_count += 1
                    if error_count >= max_consecutive_errors:
                        print(f"❌ Max consecutive errors reached. Exiting.", flush=True)
                        break
                    time.sleep(10)
                    continue
                
                logs = res.json().get("results", [])
                error_count = 0  # Reset error count on success
                
            except requests.exceptions.Timeout:
                print(f"⚠️ Request timeout. Retrying...", flush=True)
                error_count += 1
                time.sleep(10)
                continue
            except Exception as e:
                print(f"❌ Failed to fetch logs: {e}", flush=True)
                error_count += 1
                if error_count >= max_consecutive_errors:
                    print(f"❌ Max consecutive errors reached. Exiting.", flush=True)
                    break
                time.sleep(10)
                continue
            
            if not logs:
                print("ℹ️ No more unprocessed logs found.", flush=True)
                has_more = False
                break

            print(f"🔍 Processing batch of {len(logs)} logs with {ACTIVE_MODEL_ID}...", flush=True)

            for log in logs:
                try:
                    log_id = log.get('id')
                    print(f"\n📄 Processing Log: {log_id}", flush=True)
                    content = get_page_content(log_id)
                    if len(content) < 30:
                        print(f"   ⊘ Content too short, skipping", flush=True)
                        mark_log_as_processed(log_id)
                        continue
                    
                    theories = generate_theories(content)
                    
                    if not theories:
                        print(f"   ⊘ No theories extracted, marking as processed", flush=True)
                        mark_log_as_processed(log_id)
                        continue

                    for t in theories:
                        save_theory(t, log_id)
                        time.sleep(1)
                    
                    mark_log_as_processed(log_id)
                    time.sleep(2)
                    
                except Exception as e:
                    print(f"   ❌ Error processing log {log_id}: {e}", flush=True)
                    try:
                        mark_log_as_processed(log_id)
                    except:
                        pass
                    continue
        
        print("\n✅ Generalization completed successfully", flush=True)
        
    except KeyboardInterrupt:
        print("\n⚠️ Interrupted by user", flush=True)
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Fatal error in main loop: {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
