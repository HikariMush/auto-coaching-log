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
    """初回回答生成用 (/askコマンド)"""
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
       - 命令口調は禁止。推奨や提案の形（～が有効です）をとる。
       - 絵文字はアイコン（✅や🔹）として使用し、他にワードに関連する絵文字を回答に最低1つ入れる。
    2. **構造化**: 
       - 結論を最初に端的に述べる。
       - 理由や具体的なアクションを箇条書きで整理する。
    3. **内容**: 
       - Contextにある理論や数値に基づき、淡々と事実を伝える。
       - 精神論や根性論は排除する。
       - Contextにない情報は「データベースに情報がありません」と回答する。
       - 回答の最後にユーザーを励ます。
    """
    try:
        res = client.models.generate_content(model=model_id, contents=prompt)
        return res.text
    except:
        return "AI Error: 回答生成に失敗しました。"

def generate_chat_answer(history_text, context_text, new_question):
    """スレッド会話用 (継続的な会話)"""
    client = genai.Client(api_key=GEMINI_API_KEY)
    model_id = "gemini-2.0-flash-exp"
    
    prompt = f"""
    あなたはスマブラのプロコーチのアシスタントAIです。
    ユーザーとの会話履歴とContextに基づき回答してください。

    Context (コーチのメモ):
    {context_text[:20000]}
    
    Conversation History:
    {history_text}
    
    Current Question:
    {new_question}
    
    Response Guidelines:
    - 基本的に初回回答と同じトーン（丁寧、冷静、論理的）を維持すること。
    - Contextにある情報（コーチの理論）を最優先すること。
    - ユーザーの新しい質問に対して、Contextの情報を応用して答えること。
    - 最後に軽く励ますこと。
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
                {"property": "キャラクター", "multi_select": {"contains": query
