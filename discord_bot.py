import os
import discord
from discord import app_commands
from discord.ui import Button, View, Modal, TextInput
from discord.ext import commands
import requests
import json
from datetime import datetime
from google import genai
from google.genai import types
from dotenv import load_dotenv

# 環境変数の読み込み
load_dotenv()

# --- Configuration ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Database IDs
THEORY_DB_ID = "2e21bc8521e38029b8b1d5c4b49731eb"
REQUEST_DB_ID = "2e21bc8521e380a5b263fecf87b1ad7c"
FEEDBACK_DB_ID = "2e21bc8521e380c696bbd2fea868186e"

# Notion API Headers
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# --- Discord Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Notion API Helpers ---
def search_notion(query_text):
    """Theory DBから関連ページを検索"""
    url = f"https://api.notion.com/v1/databases/{THEORY_DB_ID}/query"
    payload = {
        "page_size": 5,
        "filter": {
            "or": [
                {"property": "Theory Name", "title": {"contains": query_text}},
                {"property": "Tags", "multi_select": {"contains": query_text}},
                {"property": "キャラクター", "multi_select": {"contains": query_text}}
            ]
        }
    }
    try:
        res = requests.post(url, headers=NOTION_HEADERS, json=payload)
        data = res.json()
        results = []
        for page in data.get("results", []):
            props = page.get("properties", {})
            title_list = props.get("Theory Name", {}).get("title", [])
            title = title_list[0].get("text", {}).get("content", "No Title") if title_list else "No Title"
            page_id = page.get("id")
            url = page.get("url")
            
            # 本文取得（簡易版：最初のブロックのみ）
            content_preview = "..." 
            results.append({"id": page_id, "title": title, "url": url, "content": content_preview})
        return results
    except Exception as e:
        print(f"Notion Search Error: {e}")
        return []

def get_page_content_text(page_id):
    """ページの中身（テキスト）を取得してGeminiに読ませる用"""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=50"
    try:
        res = requests.get(url, headers=NOTION_HEADERS)
        data = res.json()
        full_text = ""
        for block in data.get("results", []):
            btype = block.get("type")
            if "rich_text" in block.get(btype, {}):
                text_list = block[btype].get("rich_text", [])
                full_text += "".join([t.get("text", {}).get("content", "") for t in text_list]) + "\n"
        return full_text
    except:
        return ""

def create_feedback_ticket(user_name, question, answer, comment, ref_page_ids):
    """Feedback DBに修正依頼を作成"""
    url = "https://api.notion.com/v1/pages"
    
    # 複数のリファレンスIDをリレーション形式に変換
    relations = [{"id": pid} for pid in ref_page_ids]
    
    payload = {
        "parent": {"database_id": FEEDBACK_DB_ID},
        "properties": {
            "Topic": {"title": [{"text": {"content": f"Fix: {question[:20]}..."}}]},
            "Question": {"rich_text": [{"text": {"content": question[:2000]}}]},
            "AI Answer": {"rich_text": [{"text": {"content": answer[:2000]}}]},
            "User Comment": {"rich_text": [{"text": {"content": comment[:2000]}}]},
            "User Name": {"rich_text": [{"text": {"content": str(user_name)}}]},
            "Status": {"status": {"name": "New"}},
            "受付日": {"date": {"start": datetime.now().isoformat()}},
            "Reference Source": {"relation": relations} # ここで紐付け
        }
    }
    requests.post(url, headers=NOTION_HEADERS, json=payload)

def create_request_ticket(user_name, request_content, context):
    """Request DBに新規要望を作成"""
    url = "https://api.notion.com/v1/pages"
    payload = {
        "parent": {"database_id": REQUEST_DB_ID},
        "properties": {
            "Request Content": {"title": [{"text": {"content": request_content[:100]}}]},
            "Context": {"rich_text": [{"text": {"content": context[:2000]}}]},
            "User Name": {"rich_text": [{"text": {"content": str(user_name)}}]},
            "Status": {"status": {"name": "New"}},
            "受付日": {"date": {"start": datetime.now().isoformat()}},
            "Count": {"number": 1}
        }
    }
    requests.post(url, headers=NOTION_HEADERS, json=payload)

# --- Gemini Logic ---
def generate_answer(question, context_texts):
    client = genai.Client(api_key=GEMINI_API_KEY)
    model_id = "gemini-2.0-flash-exp" # 利用可能なモデル
    
    prompt = f"""
    あなたはスマブラのプロコーチのアシスタントAIです。
    以下の「コーチが書いた理論（Context）」だけを根拠にして、生徒の質問に答えてください。
    
    Context:
    {context_texts[:30000]}
    
    Question:
    {question}
    
    Instruction:
    - 生徒に対して親身かつ論理的に答えてください。
    - Contextに答えがない場合は「申し訳ありません、その情報はまだデータベースにありません」と正直に答えてください。
    - 嘘をつかないでください。
    """
    try:
        res = client.models.generate_content(model=model_id, contents=prompt)
        return res.text
    except Exception as e:
        return "AI Error: 回答生成に失敗しました。"

# --- Discord UI Components ---

# 1. 修正提案用モーダル
class FeedbackModal(Modal, title="情報の修正・補足提案"):
    comment = TextInput(label="修正すべき点や補足情報を教えてください", style=discord.TextStyle.paragraph, placeholder="例: ver13.0で空後の発生が早くなったので...")

    def __init__(self, question, answer, ref_ids):
        super().__init__()
        self.question = question
        self.answer = answer
        self.ref_ids = ref_ids

    async def on_submit(self, interaction: discord.Interaction):
        create_feedback_ticket(interaction.user, self.question, self.answer, self.comment.value, self.ref_ids)
        await interaction.response.send_message("✅ フィードバックありがとうございます！コーチに修正依頼を出しました。", ephemeral=True)

# 2. 新規リクエスト用モーダル
class RequestModal(Modal, title="新規コンテンツのリクエスト"):
    req_content = TextInput(label="知りたい内容（タイトル）", placeholder="例: カズヤの即死コンボの抜け方")
    context = TextInput(label="具体的な状況や背景", style=discord.TextStyle.paragraph, placeholder="いつも0%から運ばれて死にます。ずらし方向が知りたいです。", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        create_request_ticket(interaction.user, self.req_content.value, self.context.value)
        await interaction.response.send_message("✅ リクエストを受け付けました！今後の更新をお待ちください。", ephemeral=True)

# 3. 回答下のボタンView
class ResponseView(View):
    def __init__(self, question, answer, ref_ids):
        super().__init__(timeout=None)
        self.question = question
        self.answer = answer
        self.ref_ids = ref_ids

    @discord.ui.button(label="役に立った", style=discord.ButtonStyle.green, emoji="👍")
    async def helpful(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("評価ありがとうございます！", ephemeral=True)

    @discord.ui.button(label="修正・補足を提案", style=discord.ButtonStyle.secondary, emoji="⚠️")
    async def feedback(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(FeedbackModal(self.question, self.answer, self.ref_ids))

    @discord.ui.button(label="情報なし/リクエスト", style=discord.ButtonStyle.primary, emoji="🆕")
    async def request(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(RequestModal())

# --- Bot Commands ---
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands")
    except Exception as e:
        print(e)

@bot.tree.command(name="ask", description="スマブラの攻略情報を検索・質問します")
async def ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer() # 処理中表示
    
    # 1. Notion検索
    pages = search_notion(question)
    
    if not pages:
        # ヒットしなかった場合 -> 即リクエスト誘導
        view = View()
        req_btn = Button(label="リクエストを送る", style=discord.ButtonStyle.primary, emoji="🆕")
        
        async def req_callback(intr):
            await intr.response.send_modal(RequestModal())
        req_btn.callback = req_callback
        view.add_item(req_btn)
        
        await interaction.followup.send(f"検索結果: 0件\n「{question}」に関する情報はデータベースに見つかりませんでした。\nコーチに執筆リクエストを送りますか？", view=view)
        return

    # 2. 中身を取得してコンテキスト作成
    context_text = ""
    ref_links = []
    ref_ids = []
    
    for p in pages[:3]: # Top 3のみ使用
        text = get_page_content_text(p["id"])
        context_text += f"--- Source: {p['title']} ---\n{text}\n"
        ref_links.append(f"・[{p['title']}]({p['url']})")
        ref_ids.append(p["id"])

    # 3. Geminiで回答生成
    ai_answer = generate_answer(question, context_text)
    
    # 4. 返信作成
    embed = discord.Embed(title=f"Q. {question}", description=ai_answer, color=0x00ff00)
    if ref_links:
        embed.add_field(name="📚 参照ソース (根拠)", value="\n".join(ref_links), inline=False)
    
    embed.set_footer(text="内容が古い・間違っている場合は「修正提案」ボタンを押してください。")
    
    # 5. 送信
    view = ResponseView(question, ai_answer, ref_ids)
    await interaction.followup.send(embed=embed, view=view)

# Run
bot.run(DISCORD_TOKEN)
