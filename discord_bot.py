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

# --- Gemini Helper Functions ---
def extract_search_query(user_question):
    """
    ユーザーの質問文からNotion検索用の単語を抽出する。
    """
    client = genai.Client(api_key=GEMINI_API_KEY)
    model_id = "gemini-2.0-flash-exp"
    
    prompt = f"""
    あなたはデータベース検索のクエリエキスパートです。
    ユーザーの質問から、Notionデータベースを検索するための「最も重要な単語1つ」を抽出してください。
    
    ターゲットのNotionDBのプロパティ傾向:
    - キャラクター名（例: ロボット, マリオ, スネーク, ホムヒカ）
    - スマブラの技術用語（例: 崖狩り, 着地狩り, 復帰阻止, ライン管理）
    
    User Question: {user_question}
    
    Output Rule:
    - 余計な説明は一切不要。単語のみを出力すること。
    - 複数の単語がある場合、最も核心となる単語（特にキャラクター名）を最優先して1つだけ選ぶこと。
    - 英語のキャラ名はカタカナに直すこと（Rob -> ロボット）。
    - 略称は一般的な名称に直すこと（クラウド -> クラウド, ガノン -> ガノンドロフ）。
    """
    
    try:
        res = client.models.generate_content(model=model_id, contents=prompt)
        return res.text.strip()
    except Exception as e:
        print(f"Gemini Extract Error: {e}")
        return user_question # エラー時はそのまま返す

def generate_answer(question, context_texts):
    """
    検索結果(Context)をもとに、コーチとしての回答を生成する。
    """
    client = genai.Client(api_key=GEMINI_API_KEY)
    model_id = "gemini-2.0-flash-exp"
    
    prompt = f"""
    あなたはスマブラの「分析官・参謀」です。
    生徒（ユーザー）からの質問に対し、以下の「コーチ自身のメモ（Context）」に基づいて、
    **冷静かつ論理的**に回答してください。

    Context (コーチのメモ):
    {context_texts[:30000]}
    
    Question:
    {question}
    
    Response Guidelines:
    1. **トーン**: 
       - 「～です/～ます」調の丁寧語。
       - **感情的な煽りや、過度な感嘆符（！）は用いない。**
       - 「～だと思え！」「～しろ！」といった命令口調は禁止。推奨や提案の形（～が有効です、～を推奨します）をとる。
       - 絵文字は視認性を高めるためのアイコン（✅や🔹など）を使用し、装飾目的の絵文字（🍕や🎁）は淡々とした印象を与えすぎないよう必要に応じて使用する。
    2. **構造化**: 
       - 結論を最初に端的に述べる。
       - 理由や具体的なアクションを箇条書きで整理する。
    3. **内容**: 
       - Contextにある理論や数値に基づき、淡々と事実を伝える。
       - 精神論や根性論は排除する。
       - Contextにない情報はハルシネーション（嘘）を防ぐため、「データベースに情報がありません」と回答する。
       - 回答の最後にユーザーを励ます。
    """
    
    try:
        res = client.models.generate_content(model=model_id, contents=prompt)
        return res.text
    except Exception as e:
        print(f"Gemini Generate Error: {e}")
        return "AI Error: 回答生成に失敗しました。"

# --- Notion API Helpers ---
def search_notion(query_text):
    """Theory DBから関連ページを検索"""
    url = f"https://api.notion.com/v1/databases/{THEORY_DB_ID}/query"
    
    # 検索クエリの構築
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
            
            # タイトル取得
            title_list = props.get("Theory Name", {}).get("title", [])
            title = title_list[0].get("text", {}).get("content", "No Title") if title_list else "No Title"
            
            page_id = page.get("id")
            page_url = page.get("url")
            results.append({"id": page_id, "title": title, "url": page_url})
            
        return results
    except Exception as e:
        print(f"Notion Search Error: {e}")
        return []

def get_page_content_text(page_id):
    """ページ内のブロックを取得してテキスト化"""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=50"
    try:
        res = requests.get(url, headers=NOTION_HEADERS)
        data = res.json()
        full_text = ""
        for block in data.get("results", []):
            btype = block.get("type")
            # テキストが含まれる可能性のあるブロックタイプ
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

    # Button B: コーチに直接聞く
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
    
    # 1. Geminiに検索ワードを考えさせる
    search_keyword = extract_search_query(question)
    print(f"Original: {question} -> Search Keyword: {search_keyword}") # ログ確認用
    
    # 2. 抽出したキーワードでNotionを検索
    pages = search_notion(search_keyword)
    
    # 検索ヒットなし -> リクエストへ誘導
    if not pages:
        view = View()
        req_btn = Button(label="リクエストを送る", style=discord.ButtonStyle.primary, emoji="🆕")
        async def req_callback(intr): await intr.response.send_modal(RequestModal())
        req_btn.callback = req_callback
        view.add_item(req_btn)
        
        # ユーザーには「何で検索したか」も伝える
        msg = f"「{search_keyword}」に関する情報が見つかりませんでした。\n(検索ワード自動変換: {question} → {search_keyword})\n\n執筆リクエストを送りますか？"
        await interaction.followup.send(msg, view=view)
        return

    # 3. コンテキスト作成
    context_text = ""
    ref_links = []
    ref_ids = []
    
    for p in pages[:3]:
        text = get_page_content_text(p["id"])
        context_text += f"--- Source: {p['title']} ---\n{text}\n"
        ref_links.append(f"・[{p['title']}]({p['url']})")
        ref_ids.append(p["id"])

    # 4. 回答生成 (Contextだけでなく、ユーザーの元の質問文 question を渡
