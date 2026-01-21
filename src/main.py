"""
SmashZettel-Bot: Async Discord Bot for SmashBros AI Coaching

This is the main entry point for the Discord Bot. It implements:
- /ask: Query the coaching AI for analysis and advice
- /teach: Submit user corrections to training_data.jsonl

Architecture:
- Async/Sync Bridge: DSPy inference (blocking) is wrapped with asyncio.to_thread()
  to prevent blocking the async Discord event loop.
- Data Persistence: User corrections are saved to data/training_data.jsonl
  and automatically committed to GitHub via gitpython.
"""

import os
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from src.brain.model import create_coach

# Load environment
load_dotenv()

# Configuration
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
TRAINING_DATA_FILE = Path("data/training_data.jsonl")

if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable not set.")

# Initialize Discord Bot
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="/", intents=intents)

# Global coaching module
coach = None


@bot.event
async def on_ready():
    """Initialize coaching module when bot is ready."""
    global coach

    if coach is None:
        print(f"🚀 Initializing SmashCoach...")
        try:
            coach = create_coach()
            print("✅ SmashCoach initialized successfully")
        except Exception as e:
            print(f"❌ Failed to initialize SmashCoach: {e}")

    print(f"✅ {bot.user} is now online!")


@bot.tree.command(
    name="ask",
    description="スマブラのコーチングを受けます。質問を入力してください。",
)
@app_commands.describe(query="あなたの質問（例：崖上がりの対策は？）")
async def ask_command(interaction: discord.Interaction, query: str):
    """
    Handle /ask command: Query the coaching AI.

    Parameters:
    -----------
    interaction : discord.Interaction
        Discord interaction object.
    query : str
        User's question in Japanese.
    """
    global coach

    if coach is None:
        await interaction.response.send_message(
            "❌ コーチが初期化されていません。しばらく待ってからお試しください。",
            ephemeral=True,
        )
        return

    # Defer response (might take time)
    await interaction.response.defer()

    try:
        # Run blocking DSPy inference in thread pool
        print(f"[Ask] Processing query: {query}")

        prediction = await asyncio.to_thread(_run_coaching, query)

        # Format response
        analysis = prediction.analysis or "（分析不可）"
        advice = prediction.advice or "（アドバイス不可）"

        # Truncate if necessary (Discord message limit: 2000 chars)
        response_text = f"""
**【分析】**
{analysis}

**【アドバイス】**
{advice}
"""
        response_text = response_text[:2000]

        await interaction.followup.send(response_text)

        print(f"[Ask] Response sent successfully")

    except Exception as e:
        print(f"[Ask] Error: {e}")
        await interaction.followup.send(
            f"❌ エラーが発生しました: {str(e)[:100]}",
            ephemeral=True,
        )


@bot.tree.command(
    name="teach",
    description="アドバイスに対する修正情報を提供します。",
)
@app_commands.describe(
    query="元の質問",
    correction="正解またはより良いアドバイス",
)
async def teach_command(
    interaction: discord.Interaction,
    query: str,
    correction: str,
):
    """
    Handle /teach command: Submit user corrections for model improvement.

    This saves the correction to training_data.jsonl in the format:
    {"question": query, "gold_answer": correction, "timestamp": "..."}

    And attempts to commit to GitHub automatically.

    Parameters:
    -----------
    interaction : discord.Interaction
        Discord interaction object.
    query : str
        Original question.
    correction : str
        User's corrected or better answer.
    """
    await interaction.response.defer()

    try:
        # Prepare training data entry
        entry = {
            "question": query,
            "gold_answer": correction,
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": str(interaction.user.id),
        }

        # Ensure data directory exists
        TRAINING_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Append to JSONL
        await asyncio.to_thread(_append_training_data, entry)

        # Attempt GitHub commit
        commit_result = await asyncio.to_thread(_commit_to_github)

        response = (
            f"✅ 修正データを保存しました。\n"
            f"質問: {query[:100]}\n"
            f"回答: {correction[:100]}"
        )

        if commit_result:
            response += "\n📤 GitHub へ自動コミットしました。"

        await interaction.followup.send(response)
        print(f"[Teach] Correction recorded: {query[:50]}")

    except Exception as e:
        print(f"[Teach] Error: {e}")
        await interaction.followup.send(
            f"❌ 保存に失敗しました: {str(e)[:100]}",
            ephemeral=True,
        )


# --- Helper Functions (Blocking) ---


def _run_coaching(query: str):
    """
    === Async/Sync Bridge: DSPy Inference in Thread Pool ===
    
    CRITICAL DESIGN PATTERN:
    - DSPy inference is BLOCKING (synchronous I/O, LLM calls).
    - Discord.py is ASYNC-only event loop.
    - Solution: asyncio.to_thread(wrapper) runs blocking code in thread pool.
    
    EXECUTION:
    1. Called from Discord command handler via: await asyncio.to_thread(_run_coaching, query)
    2. Runs in ThreadPoolExecutor (default max_workers=5).
    3. Blocks thread (not event loop) → Event loop remains responsive.
    4. Returns dspy.Prediction with analysis + advice fields.
    
    DSPy CONTEXT:
    - This is the Student component (reasoning engine).
    - Called by coach.forward() which is a dspy.Module.
    - Output fed to Discord formatting (type: dspy.Prediction).
    
    PERFORMANCE IMPLICATIONS:
    - Each query takes ~2-10s (depending on LLM latency).
    - Multiple concurrent queries use different thread pool threads.
    - Event loop remains responsive for other Discord interactions.
    
    REDEFINABILITY:
    - Could be replaced with async LLM client (if available).
    - Could implement caching layer (Redis) here for frequent queries.
    - Could add metrics/logging at this boundary.

    Parameters:
    -----------
    query : str
        User's question (DSPy Student receives this as input).

    Returns:
    --------
    dspy.Prediction
        Prediction object (same as coach.forward() output).
    """
    global coach
    return coach.forward(query)


def _append_training_data(entry: dict) -> None:
    """
    Append a training data entry to training_data.jsonl.

    Parameters:
    -----------
    entry : dict
        Entry dict with 'question', 'gold_answer', 'timestamp', 'user_id'.
    """
    with open(TRAINING_DATA_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _commit_to_github() -> bool:
    """
    Attempt to commit training_data.jsonl to GitHub.

    This function uses gitpython to:
    1. Stage the training data file.
    2. Commit with a timestamp message.
    3. Push to the default branch.

    Returns:
    --------
    bool
        True if commit successful, False otherwise.
    """
    try:
        from git import Repo

        repo = Repo(".")
        repo.index.add([str(TRAINING_DATA_FILE)])

        if repo.index.diff("HEAD"):
            timestamp = datetime.utcnow().isoformat()
            repo.index.commit(
                f"[Auto] Training data update: {timestamp}",
                author_name="SmashZettel-Bot",
                author_email="bot@smashzettel.local",
            )
            repo.remote().push()
            return True

    except Exception as e:
        print(f"[GitHub] Commit failed (non-critical): {e}")

    return False


# --- Bot Startup ---


async def main():
    """
    Start the Discord Bot.
    """
    try:
        print("🤖 Starting SmashZettel-Bot...")
        print(f"📡 Using Discord Token: {DISCORD_TOKEN[:10]}...")

        await bot.start(DISCORD_TOKEN)

    except KeyboardInterrupt:
        print("\n⏹️ Bot shutdown requested.")
        await bot.close()

    except Exception as e:
        print(f"❌ Bot startup failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
