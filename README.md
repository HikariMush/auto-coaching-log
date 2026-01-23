# SmashZettel-Bot: Auto-Coaching AI for Super Smash Bros. Ultimate

A self-evolving AI coaching system that leverages RAG (Retrieval-Augmented Generation), Chain-of-Thought reasoning, and user feedback loops to provide deep analysis and actionable advice for Smash Bros. players.

## 🎯 Project Overview

**Goal:** Build an intelligent Discord Bot that analyzes player situations and provides frame-perfect coaching advice.

**Architecture:**
- **Knowledge Source:** Raw SmashBros game mechanics data (raw_data/*.txt)
- **Vector Store:** Pinecone for semantic search
- **Reasoning:** DSPy with Google Gemini for CoT analysis
- **Interface:** Discord Bot with `/ask` and `/teach` commands
- **Learning:** User corrections saved to training_data.jsonl with auto-GitHub commits

## 📂 Directory Structure

```
.
├── .env                           # Secrets (DO NOT COMMIT)
├── .env.example                   # Template for .env
├── .gitignore                     # Git ignore rules
├── requirements.txt               # Python dependencies
├── Dockerfile                     # Container definition
├── README.md                      # This file
├── discord_bot.py                 # Discord Bot (Main - 推奨)
├── coaching_log_processor.py      # コーチングログ自動処理
├── .github/
│   └── workflows/
│       ├── auto_coaching_log.yml  # コーチングログ処理（15分ごと）
│       ├── discord_bot.yml        # Discord Bot起動
│       └── data_management.yml    # データ管理
├── data/                          # Data files
│   ├── training_data.jsonl        # User corrections (Gold Standards)
│   ├── general_knowledge.jsonl    # General knowledge data
│   ├── element_feedback.jsonl     # Element feedback data
│   ├── qa_logs.jsonl              # Q&A logs
│   └── ...                        # Other data files
├── docs/                          # Documentation
│   ├── PROJECT_GUIDE.md           # Project guide
│   ├── BOT_USER_GUIDE.md          # Bot user guide
│   ├── DSPY_DESIGN.md             # DSPy design documentation
│   └── ...                        # Other documentation
├── logs/                          # Log files
│   └── excel_ingestion_log*.txt   # Ingestion logs
├── plans/                         # Planning documents
│   └── *.md                       # Various planning documents
├── scripts/                       # Utility scripts
│   ├── quickstart.sh              # Quick start script
│   ├── setup_data.py              # Data setup script
│   ├── ingest_general_knowledge.py # Knowledge ingestion
│   └── ...                        # Other scripts
├── src/                           # Source code
│   ├── __init__.py
│   ├── discord_bot_dspy.py        # Discord Bot (DSPy版・代替実装)
│   ├── brain/
│   │   ├── __init__.py
│   │   ├── raw_data/              # Knowledge base (*.txt files)
│   │   ├── retriever.py           # Pinecone + DSPy Retriever
│   │   ├── model.py               # Type B Coaching Logic
│   │   └── core.py                # Core logic
│   └── utils/
│       ├── __init__.py
│       ├── ingest.py              # Data vectorization & Pinecone upload
│       └── ...                    # Other utilities
└── tests/                         # Test files
    ├── test_integration.py        # Integration tests
    ├── test_mario_extraction.py   # Mario data extraction tests
    └── ...                        # Other test files
```

## 🚀 Quick Start

### 1. Setup Environment

```bash
# Clone repository
git clone https://github.com/HikariMush/auto-coaching-log.git
cd auto-coaching-log

# Create .env from template
cp .env.example .env
# Edit .env with your API keys:
# - DISCORD_TOKEN
# - GEMINI_API_KEY
# - PINECONE_API_KEY
# - (Optional) GITHUB_TOKEN
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Ingest Knowledge Base

Before running the bot, populate Pinecone with SmashBros knowledge:

```bash
python -m src.utils.ingest
```

This script:
- Reads all `.txt` files from `src/brain/raw_data/`
- Generates embeddings using Google Gemini API
- Uploads to Pinecone index (`smash-zettel`)

### 4. Run the Bot

```bash
# メインのDiscord Bot（推奨）
python discord_bot.py

# または DSPy版
python -m src.discord_bot_dspy
```

The bot will:
- Connect to Discord
- Initialize the coaching model
- Listen for `/ask` and `/teach` commands

## 📖 Command Reference

### `/ask [query]`

Query the AI coach for analysis and advice.

**Example:**
```
/ask How do I edgeguard a Fox player?
```

**Response Structure:**
- **【分析】** (Analysis): Situation diagnosis, player psychology, risk-reward assessment
- **【アドバイス】** (Advice): Concrete, frame-perfect recommendations

### `/teach [query] [correction]`

Provide a correction or better answer to improve the model.

**Example:**
```
/teach "How to recover as Ness?" "Use DJ to gain height, then angle Up-B to the ledge."
```

**Data Persistence:**
- Saves to `data/training_data.jsonl` in format:
  ```json
  {
    "question": "...",
    "gold_answer": "...",
    "timestamp": "2026-01-21T...",
    "user_id": "..."
  }
  ```
- Automatically commits to GitHub (if GITHUB_TOKEN is set)

## 🛠️ Architecture Details

### DSPy Pipeline

The coaching system is built using DSPy for strict redefinability:

1. **Retriever** (`src/brain/retriever.py`):
   - Query → Pinecone embedding search
   - Returns top-5 relevant passages

2. **Analysis** (`src/brain/model.py::AnalysisSignature`):
   - Input: Context + Question
   - Output: Situation analysis (frame state, psychology, risk-reward)

3. **Advice** (`src/brain/model.py::AdviceSignature`):
   - Input: Context + Question + Analysis
   - Output: Concrete, numbered action items

### Async/Sync Bridge

DSPy inference is blocking. The Discord Bot uses `asyncio.to_thread()` to prevent event loop blocking:

```python
# In src/main.py
prediction = await asyncio.to_thread(_run_coaching, query)
```

### Knowledge Base

Raw knowledge is stored in `src/brain/raw_data/*.txt` files, each covering a specific mechanic:
- `攻撃判定.txt` - Hitbox mechanics
- `ふっとび.txt` - Knockback physics
- `復帰.txt` - Recovery strategies
- etc.

These are automatically vectorized and indexed on first bot startup.

## 🔧 Configuration

### Environment Variables

Required:
- `DISCORD_TOKEN` - Discord bot token
- `GEMINI_API_KEY` - Google Gemini API key
- `PINECONE_API_KEY` - Pinecone database key

Optional:
- `GITHUB_TOKEN` - For auto-commits to training data
- `NOTION_TOKEN`, `DRIVE_FOLDER_ID`, `GCP_SA_KEY` - For legacy features

### Pinecone Index

Default index: `smash-zettel`
- Dimension: 768 (Google embedding-001)
- Metric: Cosine similarity
- Deployment: Serverless (AWS us-east-1)

## 📊 Data Flow

```
User Question
      ↓
Discord Bot (/ask)
      ↓
Query Pinecone Retriever
      ↓
DSPy Analysis Module (ChainOfThought)
      ↓
DSPy Advice Module (ChainOfThought)
      ↓
Format & Send to Discord
      ↓
(User provides /teach correction)
      ↓
Save to training_data.jsonl
      ↓
Auto-commit to GitHub
```

## 🐳 Docker Deployment

Build and run in a container:

```bash
docker build -t smashzettel-bot .
docker run -e DISCORD_TOKEN=<token> \
           -e GEMINI_API_KEY=<key> \
           -e PINECONE_API_KEY=<key> \
           smashzettel-bot
```

For Google Cloud Run:
```bash
gcloud run deploy smashzettel-bot \
  --source . \
  --allow-unauthenticated \
  --set-env-vars DISCORD_TOKEN=<token>,GEMINI_API_KEY=<key>,PINECONE_API_KEY=<key>
```

## 🧪 Testing

### Local Testing

```python
# Test retriever
from src.brain.retriever import PineconeRetriever
retriever = PineconeRetriever()
results = retriever.forward("復帰の最適なタイミングは？")
print(results.context)

# Test coach
from src.brain.model import create_coach
coach = create_coach()
prediction = coach.forward("ネス対策のポイントは？")
print(prediction.analysis)
print(prediction.advice)
```

## 📝 Development Notes

### DSPy Compliance

All code adheres to DSPy principles:
- **Redefinability:** Prompts defined as `dspy.Signature` classes
- **Modularity:** Logic encapsulated in `dspy.Module` subclasses
- **Docstring Standards:** All classes include DSPy context explanation

### Future Enhancements

- [ ] Implement dspy.Teleprompter for automatic prompt optimization
- [ ] Add dspy.BootstrapFewShot using training_data.jsonl
- [ ] Support multiple LM providers (Claude, OpenAI)
- [ ] Implement metric for coaching quality evaluation
- [ ] Add caching layer for frequently asked questions

## 🤝 Contributing

Contributions welcome! Guidelines:
1. Maintain DSPy compliance (Signature-based prompts)
2. Add docstrings with DSPy context
3. Test with local coach instance before pushing
4. Update training_data.jsonl for edge cases

## 📄 License

[Specify your license]

## 👤 Author

SmashZettel Team

---

**Last Updated:** 2026-01-21  
**Version:** 1.0.0
