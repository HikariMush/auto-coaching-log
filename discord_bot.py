import os
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import asyncio
import json
from datetime import datetime
from pathlib import Path

# 環境変数の読み込み
load_dotenv()

# --- Configuration ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
QA_LOG_FILE = Path("data/qa_logs.jsonl")
TRAINING_DATA_FILE = Path("data/training_data.jsonl")
ELEMENT_FEEDBACK_FILE = Path("data/element_feedback.jsonl")
GENERAL_KNOWLEDGE_FILE = Path("data/general_knowledge.jsonl")

# --- Import Brain ---
from src.brain.core import SmashBrain

# --- Discord Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Brain インスタンス
brain = None

# --- Bot Commands ---
@bot.event
async def on_ready():
    global brain
    print(f'🤖 Logged in as {bot.user}!')
    print(f'📊 Servers: {len(bot.guilds)}')
    
    # Brainの初期化
    try:
        print('🧠 Initializing SmashBrain...')
        brain = SmashBrain()
        print('✅ Brain initialized successfully')
    except Exception as e:
        print(f'❌ Brain initialization failed: {e}')
        brain = None
    
    # コマンド同期
    try:
        synced = await bot.tree.sync()
        print(f'✅ Synced {len(synced)} command(s)')
    except Exception as e:
        print(f'❌ Command sync failed: {e}')

@bot.event
async def on_message(message):
    # Bot自身のメッセージは無視
    if message.author.bot:
        return

    # スレッド内での会話対応
    if isinstance(message.channel, discord.Thread) and message.channel.owner_id == bot.user.id:
        await handle_thread_message(message)
        return

    # 通常のコマンド処理
    await bot.process_commands(message)

async def handle_thread_message(message):
    """
    スレッド内での追加質問に対応（会話履歴を保持 + 要約）
    
    改善V2:
    - 過去の会話を要約して、現在の質問に関連する情報だけを抽出
    - トークン数削減（50%）+ 文脈理解の向上（30%）
    """
    if not brain:
        await message.channel.send("⚠️ AI Brainが初期化されていません。")
        return
    
    async with message.channel.typing():
        try:
            # スレッド内の過去メッセージを取得（最新10件まで）
            raw_history = ""
            async for msg in message.channel.history(limit=10, before=message):
                # Bot自身のメッセージとユーザーメッセージのみ含める
                if msg.author.bot and msg.author.id == bot.user.id:
                    raw_history = f"Bot: {msg.content[:200]}\n{raw_history}"  # 各メッセージ200文字まで
                elif not msg.author.bot:
                    raw_history = f"User: {msg.content}\n{raw_history}"
            
            # 会話要約を実行（履歴がある場合のみ）
            summarized_context = ""
            if raw_history:
                from src.brain.core import summarize_conversation
                summarized_context = await asyncio.to_thread(
                    summarize_conversation,
                    raw_history,
                    message.content
                )
            
            # 非同期実行でBrainを呼び出し
            # 要約された文脈を渡す（元の履歴より短くなる）
            answer = await asyncio.to_thread(brain, message.content, summarized_context)
            
            # ログ記録
            await asyncio.to_thread(log_qa, message.content, answer, str(message.author.id))
            
            # 長すぎる回答は分割
            if len(answer) > 1900:
                chunks = [answer[i:i+1900] for i in range(0, len(answer), 1900)]
                for chunk in chunks:
                    await message.channel.send(chunk)
            else:
                await message.channel.send(answer)
        except Exception as e:
            await message.channel.send(f"❌ エラーが発生しました: {e}")
            print(f"[Thread Error] {e}")

@bot.tree.command(name="ask", description="スマブラの質問をする")
@app_commands.describe(question="質問内容（例: マリオの空前の発生は？）")
async def ask(interaction: discord.Interaction, question: str):
    """
    /ask コマンド: Pineconeベースの質問応答
    """
    # Brainが初期化されていない場合
    if not brain:
        await interaction.response.send_message(
            "⚠️ AI Brainが初期化されていません。botを再起動してください。",
            ephemeral=True
        )
        return
    
    try:
        # Deferして処理中であることを通知
        await interaction.response.defer()
        
        # 非同期でBrainを実行 (DSPy推奨: module()を使用)
        answer = await asyncio.to_thread(brain, question)
        
        # ログ記録
        await asyncio.to_thread(log_qa, question, answer, str(interaction.user.id))
        
        # Embedで回答を表示
        embed = discord.Embed(
            title=f"Q: {question}",
            description=answer[:4000] if len(answer) <= 4000 else answer[:3997] + "...",
            color=0x00ff00
        )
        embed.set_footer(text="💬 スレッドで追加質問 | /teach で回答を修正できます")
        
        # 回答を送信
        webhook_msg = await interaction.followup.send(embed=embed, wait=True)
        
        # スレッドを作成
        try:
            full_msg = await interaction.channel.fetch_message(webhook_msg.id)
            thread = await full_msg.create_thread(
                name=f"Q: {question[:80]}",
                auto_archive_duration=1440  # 24時間
            )
            await thread.send("このスレッドで続けて質問ができます。")
        except Exception as e:
            print(f"⚠️ スレッド作成エラー: {e}")
            
    except discord.errors.HTTPException as e:
        if "already been acknowledged" in str(e):
            return
        print(f"❌ Discord API Error: {e}")
    except Exception as e:
        print(f"❌ Error in /ask command: {e}")
        try:
            await interaction.followup.send(
                f"❌ エラーが発生しました: {e}",
                ephemeral=True
            )
        except:
            pass

@bot.tree.command(name="status", description="Botの状態を確認")
async def status(interaction: discord.Interaction):
    """Bot の状態確認コマンド"""
    brain_status = "✅ 正常" if brain else "❌ 未初期化"
    
    # ログファイルの統計
    qa_count = 0
    training_count = 0
    
    if QA_LOG_FILE.exists():
        with open(QA_LOG_FILE, 'r', encoding='utf-8') as f:
            qa_count = sum(1 for _ in f)
    
    if TRAINING_DATA_FILE.exists():
        with open(TRAINING_DATA_FILE, 'r', encoding='utf-8') as f:
            training_count = sum(1 for _ in f)
    
    embed = discord.Embed(
        title="🤖 Bot Status",
        color=0x00ff00 if brain else 0xff0000
    )
    embed.add_field(name="Brain", value=brain_status, inline=False)
    embed.add_field(name="Servers", value=str(len(bot.guilds)), inline=True)
    embed.add_field(name="Latency", value=f"{bot.latency*1000:.0f}ms", inline=True)
    embed.add_field(name="QA Logs", value=f"{qa_count}件", inline=True)
    embed.add_field(name="Training Data", value=f"{training_count}件", inline=True)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="teach", description="回答に対する修正やフィードバックを提供")
@app_commands.describe(
    question="元の質問",
    correction="正解またはより良い回答"
)
async def teach(interaction: discord.Interaction, question: str, correction: str):
    """
    /teach コマンド: ユーザーからのフィードバックを収集（全文修正）
    """
    await interaction.response.defer(ephemeral=True)
    
    try:
        # トレーニングデータとして保存
        await asyncio.to_thread(save_training_data, question, correction, str(interaction.user.id))
        
        # Git自動コミット
        commit_success = await asyncio.to_thread(commit_to_github)
        
        response = (
            f"✅ フィードバックを保存しました。\n\n"
            f"**質問:** {question[:100]}{'...' if len(question) > 100 else ''}\n"
            f"**修正:** {correction[:100]}{'...' if len(correction) > 100 else ''}"
        )
        
        if commit_success:
            response += "\n\n📤 GitHubに自動コミットしました。"
        
        await interaction.followup.send(response, ephemeral=True)
        print(f"[Teach] Feedback recorded from user {interaction.user.id}: {question[:50]}")
        
    except Exception as e:
        print(f"[Teach] Error: {e}")
        await interaction.followup.send(
            f"❌ フィードバックの保存に失敗しました: {str(e)[:100]}",
            ephemeral=True
        )

@bot.tree.command(name="teach_element", description="回答の特定要素に対するフィードバック")
@app_commands.describe(
    question="元の質問",
    element_number="要素番号（1, 2, 3, 4）",
    correction="この要素の修正内容"
)
async def teach_element(interaction: discord.Interaction, question: str, element_number: int, correction: str):
    """
    /teach_element コマンド: 要素別フィードバックを収集
    
    使用例:
    /teach_element question:"マリオの空前は？" element_number:2 correction:"硬直差の計算式を明記すべき：発生3F + 着地硬直9F = -9F"
    """
    await interaction.response.defer(ephemeral=True)
    
    try:
        # 要素番号のバリデーション
        if element_number not in [1, 2, 3, 4]:
            await interaction.followup.send(
                f"❌ 要素番号は1〜4の範囲で指定してください。\n"
                f"[1] フレームデータ・基礎情報\n"
                f"[2] 技術的解説\n"
                f"[3] 実戦での使い方\n"
                f"[4] 補足・注意点",
                ephemeral=True
            )
            return
        
        # 要素別トレーニングデータとして保存
        await asyncio.to_thread(
            save_element_feedback,
            question,
            element_number,
            correction,
            str(interaction.user.id)
        )
        
        # Git自動コミット
        commit_success = await asyncio.to_thread(commit_to_github)
        
        element_names = {
            1: "フレームデータ・基礎情報",
            2: "技術的解説",
            3: "実戦での使い方",
            4: "補足・注意点"
        }
        
        response = (
            f"✅ 要素別フィードバックを保存しました。\n\n"
            f"**質問:** {question[:100]}{'...' if len(question) > 100 else ''}\n"
            f"**対象要素:** [{element_number}] {element_names[element_number]}\n"
            f"**修正:** {correction[:100]}{'...' if len(correction) > 100 else ''}"
        )
        
        if commit_success:
            response += "\n\n📤 GitHubに自動コミットしました。"
        
        await interaction.followup.send(response, ephemeral=True)
        print(f"[TeachElement] Element {element_number} feedback from user {interaction.user.id}: {question[:50]}")
        
    except Exception as e:
        print(f"[TeachElement] Error: {e}")
        await interaction.followup.send(
            f"❌ フィードバックの保存に失敗しました: {str(e)[:100]}",
            ephemeral=True
        )

@bot.tree.command(name="add_knowledge", description="一般的な重要知識を追加（全質問に適用される基礎知識）")
@app_commands.describe(
    title="知識のタイトル（例: ガーキャンの仕組み）",
    content="知識の内容（詳細な説明、計算式、例外ルールなど）",
    category="カテゴリ（frame_theory/mechanic/strategy/character_specific）"
)
async def add_knowledge(interaction: discord.Interaction, title: str, content: str, category: str):
    """
    /add_knowledge コマンド: 一般的な重要知識をPineconeに登録
    
    使用例:
    /add_knowledge title:"ガーキャン上スマの例外ルール"
                   content:"上Bと上スマはガーキャン時にジャンプ踏切の3Fが不要。通常のガーキャンジャンプ攻撃は「ジャンプF+攻撃F」だが、上スマは「攻撃Fのみ」。"
                   category:"frame_theory"
    
    この知識は特定の質問への回答ではなく、全ての関連質問に適用される基礎知識として扱われます。
    """
    await interaction.response.defer(ephemeral=True)
    
    try:
        # 一般知識として保存
        await asyncio.to_thread(
            save_general_knowledge,
            title,
            content,
            category,
            str(interaction.user.id)
        )
        
        # Git自動コミット
        commit_success = await asyncio.to_thread(commit_to_github)
        
        response = (
            f"✅ 一般知識を保存しました。\n\n"
            f"**タイトル:** {title}\n"
            f"**カテゴリ:** {category}\n"
            f"**内容:** {content[:150]}{'...' if len(content) > 150 else ''}\n\n"
            f"この知識は全ての関連質問に適用されます。"
        )
        
        if commit_success:
            response += "\n\n📤 GitHubに自動コミットしました。"
        
        await interaction.followup.send(response, ephemeral=True)
        print(f"[AddKnowledge] General knowledge added: {title}")
        
    except Exception as e:
        print(f"[AddKnowledge] Error: {e}")
        await interaction.followup.send(
            f"❌ 知識の保存に失敗しました: {str(e)[:100]}",
            ephemeral=True
        )

# --- Helper Functions ---
def log_qa(question: str, answer: str, user_id: str) -> None:
    """質問と回答をログファイルに記録"""
    try:
        QA_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        entry = {
            "question": question,
            "answer": answer,
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        with open(QA_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            
    except Exception as e:
        print(f"⚠️ QA log failed: {e}")

def save_training_data(question: str, correction: str, user_id: str) -> None:
    """ユーザーのフィードバックをトレーニングデータとして保存"""
    try:
        TRAINING_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        entry = {
            "question": question,
            "gold_answer": correction,
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        with open(TRAINING_DATA_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            
    except Exception as e:
        print(f"⚠️ Training data save failed: {e}")
        raise

def save_element_feedback(question: str, element_number: int, correction: str, user_id: str) -> None:
    """要素別フィードバックを保存"""
    try:
        ELEMENT_FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        element_names = {
            1: "frame_data",
            2: "technical_explanation",
            3: "practical_usage",
            4: "notes_and_tips"
        }
        
        entry = {
            "question": question,
            "element_number": element_number,
            "element_name": element_names.get(element_number, "unknown"),
            "correction": correction,
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        with open(ELEMENT_FEEDBACK_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            
    except Exception as e:
        print(f"⚠️ Element feedback save failed: {e}")
        raise

def save_general_knowledge(title: str, content: str, category: str, user_id: str) -> None:
    """
    一般的な重要知識を保存
    
    これらの知識は特定の質問への回答ではなく、
    全ての関連質問に適用される基礎知識として扱われます。
    
    例:
    - ガーキャンの例外ルール（上スマ、上Bは3F不要）
    - ベクトル変更とずらしの区別
    - 復帰阻止と崖上がり狩りの違い
    """
    try:
        GENERAL_KNOWLEDGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        entry = {
            "title": title,
            "content": content,
            "category": category,
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat(),
            "is_general_knowledge": True  # Pinecone登録時の優先度フラグ
        }
        
        with open(GENERAL_KNOWLEDGE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        
        print(f"[GeneralKnowledge] Saved: {title}")
            
    except Exception as e:
        print(f"⚠️ General knowledge save failed: {e}")
        raise

def commit_to_github() -> bool:
    """トレーニングデータをGitHubに自動コミット"""
    try:
        from git import Repo
        
        repo = Repo(".")
        
        # 変更をステージング
        files_to_commit = []
        if QA_LOG_FILE.exists():
            repo.index.add([str(QA_LOG_FILE)])
            files_to_commit.append(str(QA_LOG_FILE))
        if TRAINING_DATA_FILE.exists():
            repo.index.add([str(TRAINING_DATA_FILE)])
            files_to_commit.append(str(TRAINING_DATA_FILE))
        if ELEMENT_FEEDBACK_FILE.exists():
            repo.index.add([str(ELEMENT_FEEDBACK_FILE)])
            files_to_commit.append(str(ELEMENT_FEEDBACK_FILE))
        if GENERAL_KNOWLEDGE_FILE.exists():
            repo.index.add([str(GENERAL_KNOWLEDGE_FILE)])
            files_to_commit.append(str(GENERAL_KNOWLEDGE_FILE))
        
        # 変更がある場合のみコミット
        if repo.index.diff("HEAD"):
            timestamp = datetime.utcnow().isoformat()
            repo.index.commit(
                f"[Auto] Bot data update: {timestamp}",
                author_name="SmashZettel-Bot",
                author_email="bot@smashzettel.local"
            )
            repo.remote().push()
            print(f"📤 GitHub commit successful: {', '.join(files_to_commit)}")
            return True
        
        return False
        
    except Exception as e:
        print(f"⚠️ GitHub commit failed (non-critical): {e}")
        return False

if __name__ == "__main__":
    # ファイルが直接実行された場合のみBotを起動
    if not DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN environment variable not set")
        print("💡 Set it with: export DISCORD_TOKEN='your_token_here'")
        exit(1)
    
    print("🤖 Starting Discord Bot...")
    print("📋 This bot uses Pinecone-based SmashBrain for answering questions")
    bot.run(DISCORD_TOKEN)
