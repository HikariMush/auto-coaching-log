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
            results.append({"id": page_id, "title": title, "url": url})
        return results
    except Exception as e:
        print(f"Notion Search Error: {e}")
        return []

def get_page_content_text(page_id):
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
    url = "https://api.notion.com/v1/pages"
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
            "Reference Source": {"relation": relations}
        }
    }
    requests.post(url, headers=NOTION_HEADERS, json=payload)

def create_request_ticket(user_name, request_content, context, is_talk_request=False):
    """Request DBにチケット作成。is_talk_request=Trueなら「通話ネタ」としてタグ付け"""
    url = "https://api.notion.com/v1/pages"
    
    # 通話ネタの場合はタイトルに【通話希望】とつける等で区別
    title_prefix = "【通話ネタ】" if is_talk_request else ""
    
    payload = {
        "parent": {"database_id": REQUEST_DB_ID},
        "properties": {
            "Request Content": {"title": [{"text": {"content": f"{title_prefix}{request_content[:80]}"}}]},
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
    model_id = "gemini-2.0-flash-exp"
    
    prompt = f"""
    あなたはスマブラのプロコーチのアシスタントAIです。
    生徒からの質問に対し、以下の「コーチが書いた理論（Context）」を根拠に回答してください。
    
    Context:
    {context_texts[:30000]}
    
    Question:
    {question}
    
    Instruction:
    - Contextにある情報だけで答えてください。
    - 答えられない場合は正直に「データベースに情報がありません」と答えてください。
    """
    try:
        res = client.models.generate_content(model=model_id, contents=prompt)
        return res.text
    except:
        return "AI Error: 回答生成に失敗しました。"

# --- Discord UI Components ---

# 1. 修正提案モーダル
class FeedbackModal(Modal, title="情報の修正・補足提案"):
    comment = TextInput(label="修正点・補足", style=discord.TextStyle.paragraph)
    def __init__(self, question, answer, ref_ids):
        super().__init__()
        self.question = question
        self.answer = answer
        self.ref_ids = ref_ids
    async def on_submit(self, interaction: discord.Interaction):
        create_feedback_ticket(interaction.user, self.question, self.answer, self.comment.value, self.ref_ids)
        await interaction.response.send_message("✅ 修正依頼を受け付けました。", ephemeral=True)

# 2. リクエストモーダル
class RequestModal(Modal, title="新規コンテンツのリクエスト"):
    req_content = TextInput(label="知りたい内容")
    context = TextInput(label="背景・詳細", style=discord.TextStyle.paragraph, required=False)
    async def on_submit(self, interaction: discord.Interaction):
        create_request_ticket(interaction.user, self.req_content.value, self.context.value)
        await interaction.response.send_message("✅ リクエストを受け付けました。", ephemeral=True)

# 3. メインビュー
class ResponseView(View):
    def __init__(self, question, answer, ref_ids):
        super().__init__(timeout=None)
        self.question = question
        self.answer = answer
        self.ref_ids = ref_ids

    # Button A: 役に立った
    @discord.ui.button(label="役に立った", style=discord.ButtonStyle.green, emoji="👍")
    async def helpful(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("評価ありがとうございます！", ephemeral=True)

    # Button B: コーチに直接聞く (NEW)
    @discord.ui.button(label="コーチに直接聞く", style=discord.ButtonStyle.blurple, emoji="🙋")
    async def ask_coach(self, interaction: discord.Interaction, button: Button):
        # 即座にRequest DBへ登録
        context_str = f"Question: {self.question}\nAI Answer Preview: {self.answer[:100]}..."
        create_request_ticket(interaction.user, self.question, context_str, is_talk_request=True)
        
        await interaction.response.send_message(
            f"✅ **「{self.question}」** を次回の通話ネタとして保存しました。\nコーチが確認後、通話時に詳しく解説します！", 
            ephemeral=True
        )

    # Button C: 修正提案
    @discord.ui.button(label="修正提案", style=discord.ButtonStyle.secondary, emoji="⚠️")
    async def feedback(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(FeedbackModal(self.question, self.answer, self.ref_ids))

    # Button D: 新規リクエスト
    @discord.ui.button(label="リクエスト", style=discord.ButtonStyle.secondary, emoji="🆕")
    async def request(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(RequestModal())

# --- Bot Commands ---
@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')
    await bot.tree.sync()

@bot.tree.command(name="ask", description="攻略情報を検索")
async def ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    
    pages = search_notion(question)
    
    # 検索ヒットなし -> リクエストへ誘導
    if not pages:
        view = View()
        req_btn = Button(label="リクエストを送る", style=discord.ButtonStyle.primary, emoji="🆕")
        async def req_callback(intr): await intr.response.send_modal(RequestModal())
        req_btn.callback = req_callback
        view.add_item(req_btn)
        await interaction.followup.send(f"情報が見つかりませんでした。\n執筆リクエストを送りますか？", view=view)
        return

    # コンテキスト作成
    context_text = ""
    ref_links = []
    ref_ids = []
    
    for p in pages[:3]:
        text = get_page_content_text(p["id"])
        context_text += f"--- Source: {p['title']} ---\n{text}\n"
        ref_links.append(f"・[{p['title']}]({p['url']})")
        ref_ids.append(p["id"])

    # 回答生成
    ai_answer = generate_answer(question, context_text)
    
    # 埋め込み作成
    embed = discord.Embed(title=f"Q. {question}", description=ai_answer, color=0x00ff00)
    if ref_links:
        embed.add_field(name="📚 Reference", value="\n".join(ref_links), inline=False)
    
    # フッター案内
    embed.set_footer(text="これについて詳しく聞きたい場合は「🙋 コーチに直接聞く」を押してください。")
    
    view = ResponseView(question, ai_answer, ref_ids)
    await interaction.followup.send(embed=embed, view=view)

bot.run(DISCORD_TOKEN)
