import os
import time
import json
import requests
from google import genai
from google.genai import types

# --- Config ---
SOURCE_LOG_DB_ID = "2e01bc8521e380ffaf28c2ab9376b00d"   # ログDB
TARGET_THEORY_DB_ID = "2e21bc8521e38029b8b1d5c4b49731eb"  # Theory DB

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# --- Model Resolver ---
def resolve_best_model():
    client = genai.Client(api_key=GEMINI_API_KEY)
    candidates = [
        "gemini-2.0-flash-exp", 
        "gemini-1.5-flash", 
        "gemini-1.5-flash-001",
        "gemini-1.5-pro"
    ]
    print("💎 Resolving Best Gemini Model...", flush=True)
    for model in candidates:
        try:
            client.models.generate_content(model=model, contents="Test")
            print(f"✅ Model Resolved: {model}", flush=True)
            return model
        except Exception: continue
    print("⚠️ All checks failed. Fallback to 'gemini-1.5-flash'", flush=True)
    return "gemini-1.5-flash"

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
    """ログ側の『AI処理済み』チェックボックスをONにする"""
    url = f"https://api.notion.com/v1/pages/{page_id}"
    payload = {
        "properties": {
            "AI処理済み": {
                "checkbox": True
            }
        }
    }
    try:
        requests.patch(url, headers=HEADERS, json=payload)
        print(f"   ☑️ Marked as processed: {page_id}")
    except Exception as e:
        print(f"   ⚠️ Failed to mark processed: {e}")

def text_to_blocks(text):
    blocks = []
    for line in text.split('\n'):
        if not line.strip(): 
            blocks.append({"object":"block", "type":"paragraph", "paragraph":{"rich_text":[]}})
            continue
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
    あなたはスマブラの理論構築AIです。入力されたコーチングログから「一般的攻略理論」を抽出してください。
    
    【重要】
    1. "detail" フィールドは、Notionのページ本文になります。Markdown形式で記述してください。
    2. "characters"（キャラクター名）は、必ず「スマブラSPの日本語正式名称」で出力してください。
    3. 以下のJSON形式で出力してください。

    Format (JSON Array):
    [
      {{
        "theory_name": "タイトル (30文字以内)",
        "category": "立ち回り", 
        "importance": "S",
        "characters": ["クラウド", "全般"],
        "tags": ["着地狩り", "崖"],
        "abstract": "一覧表示用の3行要約",
        "detail": "### 解説\\nここに詳細な理論を書く。", 
        "source_context": "元ログからの引用抜粋"
      }}
    ]

    Log: {log_text[:15000]}
    """
    try:
        res = client.models.generate_content(
            model=ACTIVE_MODEL_ID, 
            contents=prompt, 
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        return json.loads(res.text)
    except Exception as e:
        print(f"Gemini Error: {e}")
        return []

# --- Save Logic ---
def save_theory(theory, log_id):
    props = {
        "Theory Name": {"title": [{"text": {"content": theory.get("theory_name", "Untitled")}}]},
        "Category": {"select": {"name": theory.get("category", "立ち回り")}},
        "Importance": {"select": {"name": theory.get("importance", "B (状況限定)")}},
        "Abstract": {"rich_text": [{"text": {"content": theory.get("abstract", "")}}]},
        "Source Log": {"relation": [{"id": log_id}]},
        "Verification": {"status": {"name": "Draft"}},
        "キャラクター": {"multi_select": [{"name": c} for c in theory.get("characters", [])]},
        "Tags": {"multi_select": [{"name": t} for t in theory.get("tags", [])]}
    }
    
    children = []
    if "source_context" in theory:
        children.append({
            "object":"block", "type":"callout", 
            "callout":{
                "rich_text":[{"text":{"content": f"Source Context:\n{theory['source_context'][:1900]}"}}],
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
            print(f"✅ Saved: {theory.get('theory_name')}")
        else:
            print(f"❌ Save Failed ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"❌ Network Error: {e}")

# --- Main ---
def main():
    global ACTIVE_MODEL_ID
    print("--- Generalization Started ---")
    ACTIVE_MODEL_ID = resolve_best_model()

    # ★最適化: 「AI処理済み」がチェックされていないものだけを取得
    query = {
        "filter": {
            "property": "AI処理済み",
            "checkbox": {
                "equals": False
            }
        },
        "page_size": 5, 
        "sorts": [{"property": "日付", "direction": "descending"}]
    }
    
    try:
        res = requests.post(f"https://api.notion.com/v1/databases/{SOURCE_LOG_DB_ID}/query", headers=HEADERS, json=query)
        logs = res.json().get("results", [])
    except Exception as e:
        print(f"❌ Failed to fetch logs: {e}")
        logs = []
    
    if not logs:
        print("ℹ️ No unprocessed logs found.")
        return

    for log in logs:
        print(f"Processing Log: {log['id']}")
        content = get_page_content(log["id"])
        
        # コンテンツが少なすぎる場合はスキップするが、処理済みにはする（ループ防止）
        if len(content) < 50: 
            print("   ⚠️ Content too short. Marking as processed.")
            mark_log_as_processed(log["id"])
            continue
        
        theories = generate_theories(content)
        
        if not theories:
             print("   ⚠️ No theories extracted. Marking as processed.")
             mark_log_as_processed(log["id"])
             continue

        for t in theories:
            save_theory(t, log["id"])
            time.sleep(1)
            
        # 最後に処理済みフラグを立てる
        mark_log_as_processed(log["id"])

if __name__ == "__main__":
    main()
