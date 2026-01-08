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
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID") # Admin(コーチ)のID

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
    """ユーザーの質問文からNotion検索用の単語を抽出する"""
    client = genai.Client(api_key=GEMINI_API_KEY)
    model_id = "gemini-2.0-flash-exp"
    
    prompt = f"""
    ユーザーの質問から、Notionデータベースを検索するための「最も重要な単語1つ」を抽出してください。
    Output Rule: 余計な説明は不要。単語のみ出力。英語キャラ名はカタカナ変換。
    User Question: {user_question}
    """
    try:
        res = client.models.generate_content(model=model_id, contents=prompt)
        return res.text.strip()
    except:
        return user_question

def generate_answer(question, context_texts):
    """
    初回回答生成用 (/askコマンド)
    """
    client = genai.Client(api_key=GEMINI_API_KEY)
    model_id = "gemini-2.0-flash-exp"
    
    prompt = f"""
    あなたはスマブラのプロコーチのアシスタントAIです。
    生徒からの質問に対し、以下のContextに基づいて回答してください。

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
    except:
        return "AI Error: 回答生成に失敗しました。"

def generate_chat_answer(history_text, context_text, new_question):
    """
    スレッド会話用 (継続的な会話)
    """
    client = genai.Client(api_key=GEMINI_API_KEY)
    model_id = "gemini-2.0-flash-exp"
    
    prompt = f"""
    あなたはスマブラのプロコーチのアシスタントAIです。
    ユーザーとの会話履歴とContextに基づき回答してください。

    Context (コーチのメモ):
    {context_texts[:20000] if 'context_texts' in locals() else context_text[:20000]}
    
    Conversation History:
    {history_text}
    
    Current Question:
    {new_question}
    
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
    except:
        return "AI Error: 回答生成に失敗しました。"

# --- Notion API Helpers ---
def search_notion(query_text):
    """Theory DBから関連ページを検索"""
    url = f"https://api.notion.com/v1/databases/{THEORY_DB_ID}/query"
    payload = {
        "page_size": 3,
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
            results.append({"id": page.get("id"), "title": title, "url": page.get("url")})
        return results
    except Exception as e:
        print(f"Notion Search Error: {e}")
        return []

def get_page_content_text(page_id):
    """ページテキスト取得"""
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

def append_block_to_page(page_id, text_content):
    """Notionページ末尾に追記する（Admin用）"""
    url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    payload = {
        "children": [
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [{"type": "text", "text": {"content": text_content}}],
                    "icon": {"emoji": "📝"},
                    "color": "gray_background"
                }
            }
        ]
    }
    try:
        requests.patch(url, headers=NOTION_HEADERS, json=payload)
        return True
    except Exception as e:
        print(f"Append Error: {e}")
        return False

def create_request_ticket(user_name, request_content, context, is_talk_request=False):
    url = "https://api.notion.com/v1/pages"
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

# --- Discord UI & Events ---

class ResponseView(View):
    def __init__(self, question, answer):
        super().__init__(timeout=None)
        self.question = question
        self.answer = answer

    @discord.ui.button(label="コーチに直接聞く", style=discord.ButtonStyle.blurple, emoji="🙋")
    async def ask_coach(self, interaction: discord.Interaction, button: Button):
        context_str = f"Question: {self.question}\nAI Answer Preview: {self.answer[:100]}..."
        create_request_ticket(interaction.user, self.question, context_str, is_talk_request=True)
        await interaction.response.send_message("✅ 通話ネタとして保存しました。", ephemeral=True)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')
    await bot.tree.sync()

# メッセージイベント（スレッド内の会話 & Adminコマンド処理）
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # 1. Adminコマンド: !add (Notion追記)
    if message.content.startswith("!add"):
        # 権限チェック
        if str(message.author.id) != str(ADMIN_USER_ID):
            return 
        
        if not isinstance(message.channel, discord.Thread):
            await message.channel.send("⚠️ `!add` コマンドはBotが作成したスレッド内でのみ有効です。")
            return

        target_content = message.content[5:].strip()
        thread_name = message.channel.name
        # スレッド名「Q. ロボット」から検索ワード「ロボット」を抽出して対象ページを再特定
        search_word = thread_name.replace("Q. ", "") 
        
        pages = search_notion(search_word)
        if not pages:
            await message.channel.send("⚠️ 追記対象のページが見つかりませんでした。")
            return
            
        target_page = pages[0] # 最も関連度の高いページ
        
        # 追記実行
        success = append_block_to_page(target_page["id"], f"【コーチ補足】\n{target_content}")
        if success:
            await message.channel.send(f"✅ ページ **[{target_page['title']}]** に補足情報を追記しました。")
        else:
            await message.channel.send("❌ Notionへの書き込みに失敗しました。")
        return

    # 2. スレッド内の通常会話 (生徒の深掘り質問)
    if isinstance(message.channel, discord.Thread) and message.channel.owner_id == bot.user.id:
        async with message.channel.typing():
            # 会話履歴の取得
            history = [msg async for msg in message.channel.history(limit=10)]
            history_text = "\n".join([f"{m.author.name}: {m.content}" for m in reversed(history)])
            
            # Contextの取得 (スレッドの最初のBotメッセージのEmbedから簡易取得)
            first_msg = [m async for m in message.channel.history(limit=1, oldest_first=True)][0]
            context_text = ""
            if first_msg.embeds:
                context_text = first_msg.embeds[0].description
            
            # 回答生成
            answer = generate_chat_answer(history_text, context_text, message.content)
            await message.channel.send(answer)

@bot.tree.command(name="ask", description="攻略情報を検索・質問")
async def ask(interaction: discord.Interaction, question: str):
    await interaction.response.defer()
    
    search_keyword = extract_search_query(question)
    pages = search_notion(search_keyword)
    
    if not pages:
        await interaction.followup.send(f"「{search_keyword}」の情報は見つかりませんでした。")
        return

    # Context構築
    context_text = ""
    ref_links = []
    for p in pages[:3]:
        text = get_page_content_text(p["id"])
        context_text += f"--- Source: {p['title']} ---\n{text}\n"
        ref_links.append(f"・[{p['title']}]({p['url']})")

    ai_answer = generate_answer(question, context_text)
    
    embed = discord.Embed(title=f"Q. {question}", description=ai_answer, color=0x00ff00)
    if ref_links:
        embed.add_field(name="📚 Reference", value="\n".join(ref_links), inline=False)
    
    # スレッド作成の案内
    embed.set_footer(text="💬 この回答についてさらに質問がある場合は、この下のスレッドで会話できます。")
    
    view = ResponseView(question, ai_answer)
    
    # メッセージ送信
    msg = await interaction.followup.send(embed=embed, view=view)
    
    # スレッドを作成 (ここで生徒との会話、およびコーチの!addが可能になる)
    thread = await msg.create_thread(name=f"Q. {search_keyword}", auto_archive_duration=1440)
    await thread.send("このスレッドで続けて質問ができます。（コーチもここから補足可能です）")

bot.run(DISCORD_TOKEN)
