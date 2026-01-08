import os
import time
import json
import requests
from google import genai
from google.genai import types

# --- Config ---
# IDはハードコードするか、os.getenvでSecretsから取るか統一してください
SOURCE_LOG_DB_ID = "2e01bc8521e380ffaf28c2ab9376b00d"   # 既存のログDB
TARGET_THEORY_DB_ID = "2e21bc8521e38029b8b1d5c4b49731eb"  # 今回作ったTheory DB

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# --- Notion API Helpers ---
def get_page_content(page_id):
    """ログページの全文を取得"""
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

def check_if_processed(log_page_id):
    """既に理論化済みのログかチェック"""
    query = {"filter": {"property": "Source Log", "relation": {"contains": log_page_id}}, "page_size": 1}
    try:
        res = requests.post(f"https://api.notion.com/v1/databases/{TARGET_THEORY_DB_ID}/query", headers=HEADERS, json=query)
        return len(res.json().get("results", [])) > 0 if res.status_code == 200 else False
    except: return False

def text_to_blocks(text):
    """MarkdownテキストをNotion Blockに変換（詳細解説用）"""
    blocks = []
    for line in text.split('\n'):
        if not line.strip(): 
            blocks.append({"object":"block", "type":"paragraph", "paragraph":{"rich_text":[]}})
            continue
        # 簡易Markdown解析
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
    # プロンプト：詳細解説をMarkdownで見やすく書かせる
    prompt = f"""
    あなたはスマブラの理論構築AIです。入力されたコーチングログから「一般的攻略理論」を抽出してください。
    
    【重要】
    1. "detail" フィールドは、Notionのページ本文になります。見出し(###)や箇条書き(-)を使って、人間が読みやすいMarkdown形式で記述してください。
    2. 必ず以下のJSON形式で出力してください。

    Format (JSON Array):
    [
      {{
        "theory_name": "タイトル (30文字以内)",
        "category": "立ち回り", 
        "importance": "S",
        "characters": ["Cloud", "Common"],
        "tags": ["着地狩り", "崖"],
        "abstract": "一覧表示用の3行要約",
        "detail": "### 解説\\nここに詳細な理論を書く。\\n- 理由1\\n- 理由2", 
        "source_context": "元ログからの引用抜粋"
      }}
    ]

    Log: {log_text[:15000]}
    """
    try:
        # Gemini 1.5 Flash (高速・安価) を使用
        res = client.models.generate_content(
            model="gemini-1.5-flash", 
            contents=prompt, 
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        return json.loads(res.text)
    except Exception as e:
        print(f"Gemini Error: {e}")
        return []

# --- Save Logic ---
def save_theory(theory, log_id):
    # プロパティ設定
    props = {
        "Theory Name": {"title": [{"text": {"content": theory.get("theory_name", "Untitled")}}]},
        "Category": {"select": {"name": theory.get("category", "立ち回り")}},
        "Importance": {"select": {"name": theory.get("importance", "B (状況限定)")}},
        "Abstract": {"rich_text": [{"text": {"content": theory.get("abstract", "")}}]},
        "Source Log": {"relation": [{"id": log_id}]},
        "Verification": {"status": {"name": "Draft"}},
        # Detailプロパティは廃止し、Abstractのみプロパティに残す
        # "Detail": ... (Don't set property, use page content)
        "Characters": {"multi_select": [{"name": c} for c in theory.get("characters", [])]},
        "Tags": {"multi_select": [{"name": t} for t in theory.get("tags", [])]}
    }
    
    # ページ本文（ブロック）の作成
    children = []
    
    # 1. 引用元情報
    if "source_context" in theory:
        children.append({
            "object":"block", "type":"callout", 
            "callout":{
                "rich_text":[{"text":{"content": f"Source Context:\n{theory['source_context'][:1900]}"}}],
                "icon": {"emoji": "💡"}
            }
        })

    # 2. 詳細解説 (Markdown -> Blocks)
    detail_blocks = text_to_blocks(theory.get("detail", ""))
    children.extend(detail_blocks)

    try:
        requests.post(
            "https://api.notion.com/v1/pages", 
            headers=HEADERS, 
            json={"parent": {"database_id": TARGET_THEORY_DB_ID}, "properties": props, "children": children}
        )
        print(f"Saved: {theory.get('theory_name')}")
    except Exception as e:
        print(f"Save Error: {e}")

# --- Main ---
def main():
    print("--- Generalization Started ---")
    # 直近5件のログを取得
    query = {"page_size": 5, "sorts": [{"property": "日付", "direction": "descending"}]}
    try:
        res = requests.post(f"https://api.notion.com/v1/databases/{SOURCE_LOG_DB_ID}/query", headers=HEADERS, json=query)
        logs = res.json().get("results", [])
    except: logs = []
    
    for log in logs:
        if check_if_processed(log["id"]): 
            print("Skipping (Already processed).")
            continue
            
        print(f"Processing Log: {log['id']}")
        content = get_page_content(log["id"])
        
        if len(content) < 50: continue
        
        theories = generate_theories(content)
        for t in theories:
            save_theory(t, log["id"])
            time.sleep(1) # API Rate Limit対策

if __name__ == "__main__":
    main()
