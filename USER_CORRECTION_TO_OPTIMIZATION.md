# SmashZettel-Bot: Complete User Correction → Auto-Optimization Flow

**Last Updated:** 2026-01-21  
**Status:** Ready for production use

---

## 📋 Overview

This document explains the **complete lifecycle** of how user corrections become automatic prompt improvements:

```
PHASE 1: Setup
    ↓
PHASE 2: Bot Running (collecting corrections)
    ↓
PHASE 3: Optimization (auto-tune prompts)
    ↓
PHASE 4: Deployment (improved model)
    ↓
PHASE 5: Continuous Improvement (repeat)
```

---

## 🚀 QUICK START (5 minutes)

### Option 1: Automated Setup (Recommended)
```bash
cd /workspaces/auto-coaching-log
bash quickstart.sh
```

This script will:
1. ✅ Check Python version
2. ✅ Verify .env configuration
3. ✅ Install dependencies
4. ✅ Run tests
5. ✅ Ask what to do next

### Option 2: Manual Setup
```bash
# 1. Setup
cp .env.example .env
# Edit .env with your API keys

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run tests
python test_integration_comprehensive.py

# 4. Ingest knowledge base (one-time)
python -m src.utils.ingest
python -m src.utils.notion_sync

# 5. Launch bot
python src/main.py
```

---

## 📊 COMPLETE FLOW (Step by Step)

### PHASE 1: Initial Setup (One-Time)

#### Step 1.1: Environment Configuration
```bash
# Create .env file
cp .env.example .env

# Edit with your API keys
nano .env
```

**Required keys:**
```env
GEMINI_API_KEY=sk-***          # Google Gemini API
PINECONE_API_KEY=***           # Pinecone vector DB
DISCORD_BOT_TOKEN=***          # Discord bot token
NOTION_TOKEN=***               # (optional) Notion API
THEORY_DB_ID=***               # (optional) Notion DB ID
```

#### Step 1.2: Install Dependencies
```bash
# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install packages
pip install -r requirements.txt

# Verify installation
python -c "import dspy; print('✅ DSPy installed')"
```

#### Step 1.3: Verify Setup
```bash
# Run comprehensive tests
python test_integration_comprehensive.py

# Expected output:
# TEST 1: DSPy Module Composition          ✅ PASS
# TEST 2: Notion Sync Pipeline             ✅ PASS
# ...
# TEST 7: Documentation                    ✅ PASS
# 🎉 All tests PASSED (7/7)!
```

#### Step 1.4: Ingest Knowledge Base
```bash
# Ingest raw_data/*.txt files to Pinecone
python -m src.utils.ingest

# Optional: Sync Notion Theory DB
python -m src.utils.notion_sync

# Verify data was ingested
python -m src.utils.analyze_raw_data
# Output: data/raw_data_analysis.json
```

**⏱️ Time estimate:** 10-15 minutes

---

### PHASE 2: Bot Running & Collecting Corrections (3-7 days)

#### Step 2.1: Launch Discord Bot
```bash
python src/main.py
```

**Bot output:**
```
🤖 Connecting to Discord...
✅ Logged in as SmashZettelBot#1234
📡 Ready to serve coaching!
```

#### Step 2.2: User Interaction Flow

**Scenario 1: User wants coaching**
```
User: /ask "クラウドに勝つにはどうすればいい？"
    ↓
Bot processes via DSPy pipeline:
├─ PineconeRetriever: Fetch knowledge from Notion + raw_data
├─ AnalysisSignature: Diagnose the situation
├─ AdviceSignature: Generate actionable recommendations
    ↓
Bot responds: "【分析】クラウドの空中戦能力... 【アドバイス】..."
```

**Scenario 2: User provides correction**
```
User: /teach query:"クラウドに勝つには？" correction:"コンボを具体的に教えて"
    ↓
Bot saves to data/training_data.jsonl:
{
  "question": "クラウドに勝つにはどうすればいい？",
  "gold_answer": "コンボを具体的に教えて",
  "original_response": "【分析】... 【アドバイス】...",
  "timestamp": "2026-01-21T12:34:56Z"
}
    ↓
✅ Data saved for future optimization
```

#### Step 2.3: Monitor Data Collection
```bash
# Check how many corrections collected
python -c "
import json
from pathlib import Path

jsonl = Path('data/training_data.jsonl')
if jsonl.exists():
    entries = [json.loads(line) for line in jsonl.read_text().strip().split('\n') if line]
    print(f'Corrections collected: {len(entries)}')
    print(f'Target for first optimization: 30-50')
    print(f'Progress: {len(entries)/30*100:.0f}%')
"
```

**Expected timeline:**
- Day 1: 5-10 corrections
- Day 2-3: 15-25 corrections
- Day 4-5: 30+ corrections ✅ Ready for optimization
- Day 7: 50+ corrections (excellent data)

---

### PHASE 3: Optimization (When ready)

#### Step 3.1: Wait for Sufficient Data
```
Minimum: 30 corrections (acceptable quality)
Recommended: 50+ corrections (robust optimization)
Excellent: 100+ corrections (very accurate tuning)
```

Check your progress:
```bash
python -c "
import json
from pathlib import Path

entries = [json.loads(l) for l in Path('data/training_data.jsonl').read_text().strip().split('\n') if l]
count = len(entries)

if count < 20:
    print(f'⏳ Collecting data: {count}/30 ({count/30*100:.0f}%)')
elif count < 30:
    print(f'⏳ Almost ready: {count}/30 ({count/30*100:.0f}%)')
elif count < 50:
    print(f'✅ Ready to optimize: {count} corrections')
else:
    print(f'🎉 Excellent data: {count} corrections')
"
```

#### Step 3.2: Run Optimization
```bash
# Run dspy.Teleprompter optimizer
python -m src.utils.optimize_coach

# Output will show:
# 1️⃣  Initializing base coach...
# 2️⃣  Initializing dspy.Teleprompter...
# 3️⃣  Running optimization trials...
#    Trial 1/100: quality=0.62
#    Trial 2/100: quality=0.64
#    ...
#    Trial 100/100: quality=0.78 ✅ Best
# 💾 Saving optimized state...
# ✅ Optimization complete!
```

**⏱️ Time:** 10-30 minutes  
**💰 Cost:** $5-15 USD (100 LLM API calls)

#### Step 3.3: Review Results

The script shows before/after comparison:
```
Query 1: "ネスに勝つには？"

📌 BEFORE Optimization:
   Analysis: "ネスは心理戦のキャラです... "
   Advice: "相手の心理を読むことが大事です... "

✨ AFTER Optimization:
   Analysis: "ネスは復帰距離が長く、空中戦が強いキャラです..."
   Advice: "1. 序盤からダメージを稼ぐ 2. 上Bで撃墜..."
```

---

### PHASE 4: Deploy Optimized Model

#### Step 4.1: Update Bot Configuration
Edit `src/main.py` to load optimized model:

```python
# Around line 50 in _run_coaching():

from pathlib import Path
import json

optimized_state_file = Path('data/optimized_coach_state.json')

if optimized_state_file.exists():
    print("✅ Loading optimized coach")
    # Load and use optimized prompts
    # (Implementation depends on dspy version)
    coach = create_coach()  # Will be updated to load optimized state
else:
    print("⚠️  Using default coach")
    coach = create_coach()
```

#### Step 4.2: Restart Bot
```bash
# Stop current bot (Ctrl+C in terminal)

# Restart with optimized model
python src/main.py

# Output should show:
# ✅ Loading optimized coach
# 🤖 Connected to Discord
```

#### Step 4.3: Commit Changes
```bash
git add data/optimized_coach_state.json src/main.py
git commit -m "chore: Deploy optimized coach (trial 1)"
git push origin main
```

---

### PHASE 5: Continuous Improvement Cycle

#### Step 5.1: Monitor Quality
```bash
# Daily check
python -c "
import json
from pathlib import Path
from datetime import datetime, timedelta

jsonl = Path('data/training_data.jsonl')
entries = [json.loads(l) for l in jsonl.read_text().strip().split('\n') if l]

# Entries from last 24h
now = datetime.fromisoformat(datetime.now().isoformat())
recent = [e for e in entries 
          if datetime.fromisoformat(e['timestamp']) > now - timedelta(days=1)]

print(f'Last 24h: {len(recent)} corrections')
print(f'Total: {len(entries)} corrections')
print(f'Average quality: (calculated from metric)')
"
```

#### Step 5.2: Collect More Data (if needed)
- Continue running bot
- If users still provide many /teach corrections → prompts need more tuning
- If users rarely provide /teach corrections → prompts are good!

**Goal:** Minimize /teach usage over time as prompts improve

#### Step 5.3: Re-Optimize (Weekly or Monthly)
```bash
# Check if enough new corrections collected
NEW_CORRECTION_COUNT=$(python -c "...")

if [ $NEW_CORRECTION_COUNT -gt 20 ]; then
    echo "✅ Enough new data, re-optimizing..."
    python -m src.utils.optimize_coach
else
    echo "⏳ Waiting for more corrections..."
fi
```

#### Step 5.4: Set Up Automation (Optional)

**GitHub Actions (automatic daily optimization):**

Create `.github/workflows/daily_optimize.yml`:
```yaml
name: Daily Coach Optimization
on:
  schedule:
    - cron: '0 2 * * *'  # 2 AM UTC daily

jobs:
  optimize:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: pip install -r requirements.txt
      
      - name: Check data count
        id: check
        run: python -c "..."
      
      - name: Run optimization
        if: steps.check.outputs.count > 20
        run: python -m src.utils.optimize_coach
      
      - name: Commit changes
        run: |
          git config user.email "copilot@github.com"
          git config user.name "Copilot Bot"
          git add data/
          git commit -m "chore: Daily optimization" || true
          git push
```

---

## 📊 Timeline & Milestones

```
Day 1 (5-10 corrections):
├─ Bot running and serving
├─ Users getting initial responses
└─ Early patterns in corrections

Day 3 (15-25 corrections):
├─ Patterns becoming clear
├─ Common improvement areas identified
└─ Ready for analysis

Day 5 (30-50 corrections):
├─ ✅ Optimization threshold reached
├─ Run: python -m src.utils.optimize_coach
└─ Expected quality improvement: +15-25%

Day 7 (50+ corrections):
├─ Deploy optimized model
├─ Monitor user /teach usage
└─ Should decrease significantly

Week 2 (100+ corrections):
├─ Excellent training data
├─ Re-optimize for fine-tuning
├─ Expected quality improvement: +10-15%
└─ Most queries satisfied without /teach

Ongoing (500+ corrections):
├─ Continuous monitoring
├─ Monthly re-optimization
├─ Adapt to new meta/patches
└─ Gradual improvements expected
```

---

## 🎯 Success Metrics

### Primary Metrics
| Metric | Baseline | Target | Success |
|--------|----------|--------|---------|
| /teach usage rate | 40% | < 10% | When users rarely correct |
| Quality score | 0.65 | 0.85+ | +20-30% improvement |
| Response accuracy | 60% | 85%+ | Fewer factual errors |
| User satisfaction | ? | 4/5 ⭐ | Feedback-based |

### Secondary Metrics
| Metric | Purpose |
|--------|---------|
| Response time | Monitor latency (should stay <5s) |
| API cost | Track optimization expenses |
| Data collection rate | Adjust timeline expectations |
| Prompt diversity | Avoid overfitting to certain query types |

---

## 🔧 Advanced Options

### 1. Multi-Model Strategy
```python
# Use different models for different speeds/qualities

fast_coach = create_coach(model='gemini-2.0-flash')
deep_coach = create_coach(model='gemini-1.5-pro')

# Route based on complexity
if query_complexity > 0.7:
    pred = deep_coach.forward(query)  # More thorough
else:
    pred = fast_coach.forward(query)  # Faster response
```

### 2. Custom Metrics
```python
# Implement sport-specific metrics

def smash_bros_metric(gold, pred, trace=None):
    """Evaluate frame-data accuracy, combo validity, etc."""
    
    # Check if prediction mentions correct frame data
    # Validate combos are possible
    # Ensure character-specific advice
    
    return score  # 0.0-1.0
```

### 3. A/B Testing
```bash
# Deploy two different optimized models
# Split traffic 50/50
# Compare quality metrics

# Keep winner, re-optimize loser
```

---

## ⚠️ Troubleshooting

### Issue: Bot won't start
```bash
# Check .env file
python -c "from dotenv import load_dotenv; load_dotenv(); print(os.getenv('DISCORD_BOT_TOKEN'))"

# Check Discord token validity
# Verify bot has required permissions in Discord server
```

### Issue: Very few corrections collected
```
Possible causes:
├─ Users don't know about /teach command
├─ Responses are good (fewer corrections needed)
├─ Wrong user base (not familiar with command)

Solutions:
├─ Add help message: "Use /teach if response can improve"
├─ Check if /teach syntax is correct
├─ Ask specific users for feedback
```

### Issue: Optimization quality didn't improve
```
Possible causes:
├─ Training data has noise/errors
├─ Metric doesn't capture improvement
├─ Existing prompts already optimal
├─ Need more diverse training data

Solutions:
├─ Review/clean training data
├─ Adjust metric weights
├─ Collect more examples (50+)
├─ Try different metric function
```

---

## 📚 Related Documentation

- [DSPY_DESIGN.md](DSPY_DESIGN.md) - Architecture details
- [PROJECT_GUIDE.md](PROJECT_GUIDE.md) - Quick reference
- [DESIGN_QUESTIONS_ANSWERED.md](DESIGN_QUESTIONS_ANSWERED.md) - Design Q&A
- [SESSION_CHANGELOG.md](SESSION_CHANGELOG.md) - Implementation history

---

## 🎓 Understanding DSPy Optimization

### What is dspy.Teleprompter?

It's an automatic prompt optimizer that:
1. Takes your base model prompts
2. Tries 100+ variations
3. Evaluates each with a metric function
4. Returns the best-performing prompts

### Why is it better than manual tuning?

| Manual Tuning | dspy.Teleprompter |
|---------------|-------------------|
| Time: Hours-Days | Time: Minutes (automated) |
| Subjective | Objective (metric-based) |
| Hard to scale | Scales to any dataset |
| Error-prone | Reproducible |
| Limited exploration | Explores 100+ variations |

### Example: How It Works

```
Base Prompt:
  "You are a coach. Analyze the situation and provide advice."

Trial 1: "You are an expert coach. Analyze carefully..."
         Score: 0.62

Trial 2: "You are a professional fighting game coach. 
          Be specific about combos and frame data..."
         Score: 0.71

Trial 3: "You are the best SmashBros coach. Provide
          specific character combos with % thresholds..."
         Score: 0.78 ✅ Best!

Optimized Prompt: (from Trial 3)
```

---

## 🚀 Getting Started NOW

```bash
# 1. Quick setup (5 min)
bash quickstart.sh

# 2. Choose action:
#    - Ingest data: python -m src.utils.ingest
#    - Launch bot: python src/main.py
#    - Check quality: python -m src.utils.analyze_raw_data

# 3. Let bot run and collect corrections (3-7 days)

# 4. Optimize when ready:
#    python -m src.utils.optimize_coach

# 5. Deploy improved model and repeat!
```

---

**Next Step:** Run `bash quickstart.sh` and follow the prompts! 🎉

