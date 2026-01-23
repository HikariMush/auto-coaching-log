#!/usr/bin/env python3
"""
SmashZettel-Bot: Complete Optimization Flow
FROM: User running bot + providing /teach corrections
TO: Automatic prompt optimization with dspy.Teleprompter

This script orchestrates the entire optimization pipeline.
"""

import os
import json
import sys
from pathlib import Path
from datetime import datetime

# Configuration
DATA_DIR = Path('/workspaces/auto-coaching-log/data')
TRAINING_DATA_FILE = DATA_DIR / 'training_data.jsonl'
OPTIMIZED_MODEL_FILE = DATA_DIR / 'optimized_coach_state.json'
MIN_TRAINING_EXAMPLES = 30  # Minimum examples before optimization

def print_step(num, title, description=""):
    """Pretty print workflow steps"""
    print(f"\n{'='*70}")
    print(f"STEP {num}: {title}")
    print(f"{'='*70}")
    if description:
        print(description)

def print_substep(num, title):
    """Pretty print sub-steps"""
    print(f"\n  [{num}] {title}")

def step1_setup_environment():
    """STEP 1: Environment Setup"""
    print_step(1, "Environment Setup", 
               "Initialize .env and verify API credentials")
    
    print_substep("1.1", "Check .env file exists")
    env_file = Path('/workspaces/auto-coaching-log/.env')
    if env_file.exists():
        print(f"    ✅ .env file found")
        # Verify required keys
        import dotenv
        config = dotenv.dotenv_values(env_file)
        required_keys = [
            'GEMINI_API_KEY',
            'PINECONE_API_KEY',
            'DISCORD_BOT_TOKEN'
        ]
        missing = [k for k in required_keys if k not in config or not config[k]]
        if missing:
            print(f"    ⚠️  Missing keys: {', '.join(missing)}")
            print(f"    📝 Edit .env and add missing values")
            return False
        print(f"    ✅ All required keys present")
    else:
        print(f"    ❌ .env file not found")
        print(f"    📝 Copy .env.example → .env and fill in your API keys")
        print(f"       cp .env.example .env")
        return False
    
    print_substep("1.2", "Verify data directory")
    DATA_DIR.mkdir(exist_ok=True)
    print(f"    ✅ Data directory ready: {DATA_DIR}")
    
    return True

def step2_ingest_knowledge_base():
    """STEP 2: Ingest Knowledge Base"""
    print_step(2, "Ingest Knowledge Base",
               "Load raw_data and Notion into Pinecone (one-time setup)")
    
    print_substep("2.1", "Ingest raw_data/*.txt files")
    print(f"""
    Run this ONCE to populate Pinecone with SmashBros mechanics:
    
    $ python -m src.utils.ingest
    
    What it does:
    ├─ Reads 42 .txt files from src/brain/raw_data/
    ├─ Embeds each with Google embedding-001 (768-dim)
    ├─ Uploads vectors to Pinecone index "smash-zettel"
    └─ Total: ~50-100 vectors (~200KB)
    
    ⏱️  Estimated time: 2-5 minutes
    """)
    
    print_substep("2.2", "Sync Notion Theory DB")
    print(f"""
    Run this FIRST TIME, then schedule for hourly runs:
    
    $ python -m src.utils.notion_sync
    
    What it does:
    ├─ Fetches all pages from Notion Theory DB
    ├─ Extracts block contents
    ├─ Embeds with Google embedding-001
    ├─ Uploads to Pinecone index
    └─ Metadata: synced_at timestamp
    
    For scheduled runs (recommended):
    ├─ Google Cloud Tasks: Run hourly
    ├─ Local cron: 0 * * * * cd /path && python -m src.utils.notion_sync
    └─ or manually before bot startup
    """)
    
    print("\n    ✅ Knowledge base ready")
    return True

def step3_launch_discord_bot():
    """STEP 3: Launch Discord Bot"""
    print_step(3, "Launch Discord Bot",
               "Start the bot and begin collecting user corrections")
    
    print_substep("3.1", "Start the bot")
    print(f"""
    $ python src/main.py
    
    What it does:
    ├─ Connects to Discord
    ├─ Registers slash commands:
    │  ├─ /ask <query>  - Get coaching advice
    │  └─ /teach <query> <correction> - Provide corrections
    ├─ Listens for commands
    └─ Starts asyncio event loop
    
    ✅ Bot is live - Ready for user interaction!
    """)
    
    print_substep("3.2", "User workflow")
    print(f"""
    Users interact with the bot:
    
    1️⃣  User: /ask "クラウドに勝つには？"
        Bot: "【分析】... 【アドバイス】..."
    
    2️⃣  User evaluates response
        ├─ If satisfied: ✅ No action needed
        └─ If needs improvement: Go to step 3
    
    3️⃣  User: /teach query:"クラウドに勝つには？" correction:"より具体的にコンボを教えて"
        Bot: ✅ Correction saved to training_data.jsonl
    
    4️⃣  Repeat: More queries → More corrections accumulated
        └─ Goal: Collect 30+ corrections for optimization
    """)
    
    return True

def step4_monitor_training_data():
    """STEP 4: Monitor Training Data Accumulation"""
    print_step(4, "Monitor Training Data Accumulation",
               "Track correction submissions as they arrive")
    
    print_substep("4.1", "Check training data file")
    print(f"""
    Location: {TRAINING_DATA_FILE}
    
    Format: JSONL (one JSON object per line)
    
    $ tail -20 data/training_data.jsonl
    """)
    
    print_substep("4.2", "Analyze data")
    print(f"""
    $ python -c "
import json
from pathlib import Path

jsonl_path = Path('data/training_data.jsonl')
if jsonl_path.exists():
    lines = jsonl_path.read_text().strip().split('\\n')
    entries = [json.loads(line) for line in lines if line]
    print(f'Total corrections collected: {{len(entries)}}')
    for i, entry in enumerate(entries[-5:], 1):
        print(f'  {{i}}: Q=\"{{entry[\"question\"][:40]}}...\"')
        print(f'      Correction=\"{{entry.get(\"gold_answer\", \"?\")[:40]}}...\"')
else:
    print('No training data yet')
    "
    """)
    
    print_substep("4.3", "Wait for sufficient data")
    print(f"""
    Optimization Thresholds:
    ├─ Phase 1 (Initial feedback): 5-10 corrections
    ├─ Phase 2 (Pattern recognition): 20-30 corrections
    ├─ Phase 3 (Robust optimization): 50+ corrections
    ├─ Phase 4 (Continuous improvement): 100+ corrections
    └─ Recommended first run: 30-50 corrections
    
    📊 Data Collection Timeline:
    ├─ Day 1-2: 5-10 corrections (first patterns emerge)
    ├─ Day 3-5: 20-30 corrections (initial optimization possible)
    ├─ Day 7-10: 50+ corrections (robust optimization)
    └─ Ongoing: 100+ corrections (continuous refinement)
    """)
    
    return True

def step5_prepare_optimization():
    """STEP 5: Prepare for Optimization"""
    print_step(5, "Prepare for Optimization",
               "Define metrics and optimization strategy")
    
    print_substep("5.1", "Define coaching quality metric")
    print(f"""
    Create a scoring function that evaluates coaching quality.
    
    Location: src/utils/optimize_coach.py (you'll create this)
    
    Example implementation:
    
    ```python
    def coaching_quality_metric(gold, pred, trace=None):
        '''
        Score prediction against gold answer.
        
        Dimensions:
        1. Relevance: Is advice related to user's question?
        2. Specificity: Is it character/move specific?
        3. Actionability: Can user execute the advice?
        4. Correctness: Does it match SmashBros mechanics?
        '''
        
        # Extract scores from gold data
        gold_data = json.loads(gold) if isinstance(gold, str) else gold
        
        # Measure prediction quality
        pred_text = pred.advice if hasattr(pred, 'advice') else str(pred)
        gold_text = gold_data.get('gold_answer', '')
        
        # Calculate metrics
        relevance_score = measure_relevance(pred_text, gold_text)
        specificity_score = measure_specificity(pred_text)
        actionability_score = measure_actionability(pred_text)
        
        # Combine scores
        final_score = (
            0.4 * relevance_score +
            0.3 * specificity_score +
            0.3 * actionability_score
        )
        
        return final_score
    ```
    """)
    
    print_substep("5.2", "Load training data")
    print(f"""
    Training data format (JSONL):
    
    {{
        "question": "ネスに勝つにはどうすればいい？",
        "gold_answer": "より具体的にコンボを教えて",
        "timestamp": "2026-01-21T12:34:56.789Z",
        "improvements": ["specificity", "actionability"],
        "original_response": "【分析】... 【アドバイス】...",
    }}
    
    Read with:
    
    ```python
    import json
    from pathlib import Path
    
    def load_training_data():
        jsonl_file = Path('data/training_data.jsonl')
        entries = []
        with open(jsonl_file, 'r') as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))
        return entries
    ```
    """)
    
    return True

def step6_run_teleprompter_optimization():
    """STEP 6: Run dspy.Teleprompter Optimization"""
    print_step(6, "Run dspy.Teleprompter Optimization",
               "Automatically tune prompts using collected corrections")
    
    print_substep("6.1", "Create optimization script")
    print(f"""
    Create: src/utils/optimize_coach.py
    
    This script will:
    ├─ Load training data from JSONL
    ├─ Initialize dspy.Teleprompter
    ├─ Define optimization metrics
    ├─ Run optimization trials (100+ iterations)
    ├─ Save optimized coach state
    └─ Output new optimized prompts
    """)
    
    print_substep("6.2", "Run optimization")
    print(f"""
    $ python -m src.utils.optimize_coach
    
    What it does:
    ├─ Loads {TRAINING_DATA_FILE}
    ├─ Initializes SmashCoach model
    ├─ Runs dspy.Teleprompter optimizer
    │  ├─ Tries 100+ different prompts
    │  ├─ Evaluates each with coaching_quality_metric
    │  ├─ Selects best performing prompts
    │  └─ Returns optimized model
    ├─ Saves state to: {OPTIMIZED_MODEL_FILE}
    └─ Displays before/after comparison
    
    ⏱️  Estimated time: 10-30 minutes (depends on data size)
    💰 API cost: ~$5-15 USD (100 trials × LLM calls)
    
    Progress indicator:
    Trial 1/100: quality=0.62
    Trial 2/100: quality=0.64
    ...
    Trial 100/100: quality=0.78 ✅ (Best found)
    """)
    
    return True

def step7_validate_optimization():
    """STEP 7: Validate Optimization Results"""
    print_step(7, "Validate Optimization Results",
               "Test optimized model against held-out test set")
    
    print_substep("7.1", "Compare before/after")
    print(f"""
    Run validation:
    
    $ python -c "
from src.utils.optimize_coach import validate_optimization
validate_optimization()
    "
    
    Output example:
    
    BEFORE Optimization:
    ├─ Average quality score: 0.65
    ├─ Relevance: 0.70
    ├─ Specificity: 0.62
    ├─ Actionability: 0.63
    └─ Sample response: '【分析】... 【アドバイス】...'
    
    AFTER Optimization:
    ├─ Average quality score: 0.78 ✅ (+20%)
    ├─ Relevance: 0.85
    ├─ Specificity: 0.75
    ├─ Actionability: 0.74
    └─ Sample response: '【分析（詳細）】... 【アドバイス（具体的）】...'
    """)
    
    print_substep("7.2", "Test with new queries")
    print(f"""
    Manually test a few queries:
    
    $ python -c "
from src.brain.model import create_coach
coach = create_coach()
pred = coach.forward('新しいキャラに勝つには？')
print('Analysis:', pred.analysis)
print('Advice:', pred.advice)
    "
    
    Expected improvements:
    ├─ More specific to character/move combos
    ├─ More actionable steps (コンボ例など)
    ├─ Better structured output
    └─ Fewer generic statements
    """)
    
    return True

def step8_deploy_optimized_model():
    """STEP 8: Deploy Optimized Model"""
    print_step(8, "Deploy Optimized Model",
               "Replace production model with optimized version")
    
    print_substep("8.1", "Backup current model")
    print(f"""
    $ cp src/brain/model.py src/brain/model.py.backup
    """)
    
    print_substep("8.2", "Load optimized state")
    print(f"""
    Update src/main.py to load optimized model:
    
    ```python
    # In _run_coaching():
    from pathlib import Path
    import json
    
    optimized_state_file = Path('data/optimized_coach_state.json')
    
    if optimized_state_file.exists():
        # Load optimized coach
        coach = load_optimized_coach()  # Custom function
        print("✅ Loaded optimized coach")
    else:
        # Fall back to default coach
        coach = create_coach()
        print("⚠️  Using default coach (optimization not yet run)")
    ```
    """)
    
    print_substep("8.3", "Restart bot")
    print(f"""
    $ python src/main.py
    
    Bot now uses OPTIMIZED prompts
    └─ Users will see improved responses
    """)
    
    return True

def step9_collect_new_data():
    """STEP 9: Continuous Improvement Cycle"""
    print_step(9, "Continuous Improvement Cycle",
               "Collect new corrections and re-optimize periodically")
    
    print_substep("9.1", "Monitor quality degradation")
    print(f"""
    Set up monitoring to track coaching quality over time:
    
    Daily check:
    $ python -c "
from pathlib import Path
import json
from datetime import datetime, timedelta

jsonl = Path('data/training_data.jsonl')
lines = jsonl.read_text().strip().split('\\n')
entries = [json.loads(l) for l in lines if l]

# Find entries from last 24h
now = datetime.fromisoformat(datetime.now().isoformat())
recent = [e for e in entries 
          if datetime.fromisoformat(e['timestamp']) > now - timedelta(days=1)]

print(f'Corrections in last 24h: {{len(recent)}}')
print(f'Total: {{len(entries)}}')
    "
    """)
    
    print_substep("9.2", "Re-optimize schedule")
    print(f"""
    Recommended re-optimization schedule:
    
    Initial phase (Week 1-2):
    ├─ Run optimization daily or every 2 days
    ├─ Collect 5-10 new corrections before each run
    ├─ Monitor quality improvements
    └─ Adjust metric weights based on results
    
    Stabilization phase (Week 3+):
    ├─ Run optimization weekly
    ├─ Collect 20-30 new corrections before each run
    ├─ Monitor for quality regressions
    └─ Only deploy if score improves
    
    Mature phase (Month 2+):
    ├─ Run optimization monthly
    ├─ Collect 50+ new corrections before each run
    ├─ Focus on edge cases and rare queries
    └─ Gradual quality improvement expected
    """)
    
    print_substep("9.3", "Set up automation (optional)")
    print(f"""
    Fully automated pipeline (using GitHub Actions or Cloud Tasks):
    
    Daily workflow:
    1. Check correction count
    2. If count > threshold:
       a. Run optimization
       b. Validate results
       c. Deploy if quality improved
       d. Notify admins
    3. Commit optimized state to GitHub
    4. Tag release with version number
    
    GitHub Actions example (.github/workflows/optimize.yml):
    
    name: Daily Coach Optimization
    on:
      schedule:
        - cron: '0 2 * * *'  # 2 AM daily
    
    jobs:
      optimize:
        runs-on: ubuntu-latest
        steps:
          - uses: actions/checkout@v3
          - name: Run optimization
            run: python -m src.utils.optimize_coach
          - name: Deploy if improved
            run: python -m src.utils.deploy_optimized
          - name: Commit changes
            run: |
              git add data/optimized_coach_state.json
              git commit -m "chore: Daily coach optimization"
              git push
    """)
    
    return True

def step10_monitoring_and_analysis():
    """STEP 10: Monitoring and Analysis"""
    print_step(10, "Monitoring and Analysis",
               "Track long-term improvement trends")
    
    print_substep("10.1", "Generate reports")
    print(f"""
    Weekly quality report:
    
    $ python -c "
from src.utils.analyze_coach_quality import generate_weekly_report
report = generate_weekly_report()
print(report)
    "
    
    Report includes:
    ├─ Quality score trend (graph)
    ├─ Most improved dimensions (relevance/specificity/actionability)
    ├─ Most corrected query types
    ├─ Least corrected query types (good performance!)
    ├─ Recommended focus areas
    └─ Next optimization strategy
    """)
    
    print_substep("10.2", "Build feedback loop metrics")
    print(f"""
    Track over time:
    ├─ /teach usage rate (corrections per day)
    ├─ Quality score per query type
    ├─ Query response latency
    ├─ User satisfaction indicator (no /teach = satisfied)
    └─ New vs revisited queries
    
    Goal: Minimize /teach corrections over time
    Success: 80%+ of queries satisfy users on first response
    """)
    
    return True

def main():
    """Print complete optimization flow"""
    print("\n" + "="*70)
    print("🚀 SmashZettel-Bot: Complete User Correction → Auto-Optimization Flow")
    print("="*70)
    print("\nThis guide walks through the COMPLETE lifecycle:")
    print("FROM: Bot startup with initial prompts")
    print("TO:   Automatic prompt optimization after collecting user corrections")
    print("\n")
    
    steps = [
        step1_setup_environment,
        step2_ingest_knowledge_base,
        step3_launch_discord_bot,
        step4_monitor_training_data,
        step5_prepare_optimization,
        step6_run_teleprompter_optimization,
        step7_validate_optimization,
        step8_deploy_optimized_model,
        step9_collect_new_data,
        step10_monitoring_and_analysis,
    ]
    
    for step_func in steps:
        step_func()
    
    print("\n" + "="*70)
    print("✅ COMPLETE FLOW DOCUMENTED")
    print("="*70)
    print("""
Next actions:
1. Follow STEP 1-2 to set up (one time)
2. Run STEP 3 to start bot (ongoing)
3. Wait for STEP 4 (collect corrections)
4. When ready, run STEP 5-6 (optimize)
5. Deploy STEP 7-8 (use optimized model)
6. Repeat STEP 9 for continuous improvement

📊 Key metrics to track:
   - Correction count: target 30+ for first optimization
   - Quality score: target +20% improvement after optimization
   - /teach usage: target decreasing over time
   - Response latency: monitor for increases

Time estimates:
   - Setup (Step 1-2): 30 minutes
   - Bot running (Step 3): Ongoing
   - Data collection (Step 4): 3-7 days
   - Optimization (Step 6): 10-30 minutes
   - Deploy (Step 8): 5 minutes
   - Total first cycle: ~1-2 weeks

💰 API costs:
   - Knowledge ingestion: ~$1-3
   - Optimization (100 trials): ~$5-15
   - Ongoing: ~$0.10-0.50 per optimization run

Good luck! 🎉
""")

if __name__ == '__main__':
    main()
