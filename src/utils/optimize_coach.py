#!/usr/bin/env python3
"""
SmashZettel-Bot: Coach Optimizer
Runs dspy.Teleprompter optimization on collected training data.

Usage:
    python -m src.utils.optimize_coach
    
Environment variables:
    GEMINI_API_KEY: Google Gemini API key
    PINECONE_API_KEY: Pinecone API key
"""

import os
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Callable
from datetime import datetime

import dspy
import google.generativeai as genai

# LLM Model Configuration
LLM_MODEL = "gemini-2-5-flash"  # Updated to Gemini 2.5 Flash

# Configuration
DATA_DIR = Path(__file__).parent.parent.parent / 'data'
TRAINING_DATA_FILE = DATA_DIR / 'training_data.jsonl'
OPTIMIZED_STATE_FILE = DATA_DIR / 'optimized_coach_state.json'
MIN_TRAINING_EXAMPLES = 30

def load_training_data() -> List[Dict[str, Any]]:
    """Load training data from JSONL file"""
    if not TRAINING_DATA_FILE.exists():
        print(f"❌ Training data not found: {TRAINING_DATA_FILE}")
        return []
    
    entries = []
    with open(TRAINING_DATA_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    
    return entries

def prepare_dspy_dataset(entries: List[Dict]) -> List[dspy.Example]:
    """Convert JSONL entries to dspy.Example objects"""
    dataset = []
    
    for entry in entries:
        example = dspy.Example(
            question=entry.get('question', ''),
            gold_analysis=entry.get('gold_answer', ''),  # User correction
            context=entry.get('context', ''),
        ).with_inputs('question', 'context')
        
        dataset.append(example)
    
    return dataset

def coaching_quality_metric(gold: Any, pred: Any, trace=None) -> float:
    """
    === DSPy Optimization Metric ===
    
    Evaluates coaching quality across multiple dimensions:
    1. Relevance: Is advice related to the question?
    2. Specificity: Is it character/move specific?
    3. Actionability: Can user execute the advice?
    
    Args:
        gold: Gold standard (user correction)
        pred: Prediction from model (dspy.Prediction)
        trace: dspy trace (for debugging)
    
    Returns:
        float: Quality score 0.0-1.0
    """
    
    # Extract text
    if isinstance(pred, dspy.Prediction):
        pred_text = getattr(pred, 'advice', str(pred))
    else:
        pred_text = str(pred)
    
    if isinstance(gold, dspy.Example):
        gold_text = gold.gold_analysis
    else:
        gold_text = str(gold)
    
    # Calculate sub-scores
    relevance_score = measure_relevance(pred_text, gold_text)
    specificity_score = measure_specificity(pred_text)
    actionability_score = measure_actionability(pred_text)
    
    # Combine with weights
    final_score = (
        0.4 * relevance_score +
        0.3 * specificity_score +
        0.3 * actionability_score
    )
    
    return final_score

def measure_relevance(pred: str, gold: str) -> float:
    """
    Measure relevance: Does prediction match user's correction?
    
    Heuristics:
    - Keyword overlap
    - Length similarity
    - Topic alignment
    """
    if not pred or not gold:
        return 0.0
    
    pred_lower = pred.lower()
    gold_lower = gold.lower()
    
    # Keyword overlap
    pred_words = set(pred_lower.split())
    gold_words = set(gold_lower.split())
    overlap = len(pred_words & gold_words)
    max_words = max(len(pred_words), len(gold_words))
    
    keyword_score = overlap / max_words if max_words > 0 else 0.0
    
    # Length similarity (both should be substantial)
    pred_len = len(pred_lower)
    gold_len = len(gold_lower)
    
    if pred_len > 10 and gold_len > 10:
        length_score = min(pred_len, gold_len) / max(pred_len, gold_len)
    else:
        length_score = 0.0
    
    # Combined relevance
    relevance = (0.7 * keyword_score + 0.3 * length_score)
    
    return min(1.0, relevance)

def measure_specificity(text: str) -> float:
    """
    Measure specificity: Are there character/move names and details?
    
    Heuristics:
    - Presence of character names (クラウド, ネス, etc.)
    - Presence of move names (空前, 上B, etc.)
    - Presence of numbers (% damage, frames, etc.)
    - Presence of Japanese technical terms
    """
    if not text:
        return 0.0
    
    score = 0.0
    
    # Character names (common SmashBros characters)
    characters = ['クラウド', 'ネス', 'マリオ', 'ピカチュウ', 'ドンキー', 
                  'リンク', 'サムス', 'ヨッシー', 'カービィ', 'ウルフ']
    char_count = sum(1 for char in characters if char in text)
    score += min(0.3, char_count * 0.05)
    
    # Move names
    moves = ['空前', '空後', '空下', '空上', '横B', '上B', '下B', 'DA', 'DAA',
             'N回', 'NA', '横強', '上強', '下強', 'つかみ', 'つかみ投げ']
    move_count = sum(1 for move in moves if move in text)
    score += min(0.3, move_count * 0.04)
    
    # Numbers (frames, %, damage)
    import re
    number_pattern = r'\d+'
    numbers = re.findall(number_pattern, text)
    score += min(0.2, len(numbers) * 0.02)
    
    # Technical terms
    technical_terms = ['硬直', 'ガード', 'シールド', 'ふっとばし', 'ダメージ', 
                      'コンボ', 'リセット', '着地']
    term_count = sum(1 for term in technical_terms if term in text)
    score += min(0.2, term_count * 0.03)
    
    return min(1.0, score)

def measure_actionability(text: str) -> float:
    """
    Measure actionability: Can user execute the advice?
    
    Heuristics:
    - Step-by-step instructions
    - Action verbs (やる, する, 避ける, etc.)
    - Concrete examples
    - Condition/result pairs (if X then Y)
    """
    if not text:
        return 0.0
    
    score = 0.0
    
    # Action verbs
    action_verbs = ['やる', 'する', '避ける', '狙う', '使う', 'つなぐ', 
                   'コンボ', '掴む', 'ガード', 'ずらす', '受け身']
    verb_count = sum(1 for verb in action_verbs if verb in text)
    score += min(0.4, verb_count * 0.05)
    
    # Structural markers (示すステップ)
    markers = ['1.', '2.', '3.', '①', '②', '③', '→', 'その後', '次に']
    marker_count = sum(1 for marker in markers if marker in text)
    score += min(0.3, marker_count * 0.06)
    
    # Conditional statements (if-then)
    conditional_markers = ['もし', 'なら', 'と', '場合', '時に']
    conditional_count = sum(1 for marker in conditional_markers if marker in text)
    score += min(0.3, conditional_count * 0.04)
    
    return min(1.0, score)

def run_optimization(trainset: List[dspy.Example], metric: Callable) -> Any:
    """
    Run dspy.Teleprompter optimization
    
    Args:
        trainset: Training examples (from load_training_data)
        metric: Quality metric function
    
    Returns:
        Optimized SmashCoach model
    """
    
    print("\n" + "="*70)
    print("🔄 Running dspy.Teleprompter Optimization")
    print("="*70)
    
    # Import the coach model
    from src.brain.model import SmashCoach, create_coach
    
    # Initialize coach
    print("\n1️⃣  Initializing base coach...")
    base_coach = create_coach()
    
    # Initialize optimizer
    print("2️⃣  Initializing dspy.Teleprompter...")
    try:
        optimizer = dspy.Teleprompter(
            metric=metric,
            trainset=trainset,
            valset=trainset[:len(trainset)//5],  # 20% for validation
            num_trials=100,
            seed=42
        )
    except Exception as e:
        print(f"⚠️  Could not use dspy.Teleprompter: {e}")
        print("   Falling back to manual prompt tuning...")
        return base_coach
    
    # Run optimization
    print("3️⃣  Running optimization trials...")
    print("   (This may take 10-30 minutes and $5-15 in API costs)\n")
    
    try:
        optimized_coach = optimizer.compile(
            student=base_coach,
            trainset=trainset,
            metric=metric,
        )
        print("\n✅ Optimization complete!")
        return optimized_coach
    except Exception as e:
        print(f"\n⚠️  Optimization failed: {e}")
        print("   Using base coach as fallback")
        return base_coach

def save_optimized_state(coach: Any) -> None:
    """Save optimized coach state to file"""
    
    print(f"\n💾 Saving optimized state to {OPTIMIZED_STATE_FILE}")
    
    DATA_DIR.mkdir(exist_ok=True)
    
    # Serialize coach state
    state = {
        'timestamp': datetime.now().isoformat(),
        'model_type': 'SmashCoach',
        'version': '1.0',
        'prompts': {
            # Extract prompts from coach module
            'analysis': getattr(coach.analyze, '_signature', None),
            'advice': getattr(coach.advise, '_signature', None),
        },
        'training_examples': len(load_training_data()),
    }
    
    with open(OPTIMIZED_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"✅ Saved to {OPTIMIZED_STATE_FILE}")

def compare_before_after(base_coach: Any, optimized_coach: Any, test_queries: List[str]) -> None:
    """Compare predictions before and after optimization"""
    
    print("\n" + "="*70)
    print("📊 Before vs After Comparison")
    print("="*70)
    
    for i, query in enumerate(test_queries[:3], 1):
        print(f"\n{'─'*70}")
        print(f"Query {i}: {query}")
        print(f"{'─'*70}")
        
        try:
            pred_before = base_coach.forward(query)
            print(f"\n📌 BEFORE Optimization:")
            print(f"   Analysis: {str(pred_before.analysis)[:100]}...")
            print(f"   Advice: {str(pred_before.advice)[:100]}...")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        try:
            pred_after = optimized_coach.forward(query)
            print(f"\n✨ AFTER Optimization:")
            print(f"   Analysis: {str(pred_after.analysis)[:100]}...")
            print(f"   Advice: {str(pred_after.advice)[:100]}...")
        except Exception as e:
            print(f"   ❌ Error: {e}")

def main():
    """Main optimization pipeline"""
    
    print("\n" + "="*70)
    print("🚀 SmashZettel-Bot: Coach Optimizer (via dspy.Teleprompter)")
    print("="*70)
    
    # Step 1: Load training data
    print("\n📂 Loading training data...")
    entries = load_training_data()
    
    if not entries:
        print(f"❌ No training data found. Run the bot first to collect /teach corrections.")
        return 1
    
    print(f"✅ Loaded {len(entries)} training examples")
    
    if len(entries) < MIN_TRAINING_EXAMPLES:
        print(f"\n⚠️  Warning: Only {len(entries)} examples.")
        print(f"   Minimum recommended: {MIN_TRAINING_EXAMPLES}")
        print(f"   Optimization quality may be poor with fewer examples.")
    
    # Step 2: Prepare DSPy dataset
    print("\n📊 Preparing DSPy dataset...")
    trainset = prepare_dspy_dataset(entries)
    print(f"✅ Prepared {len(trainset)} examples")
    
    # Step 3: Run optimization
    print("\n🔧 Starting optimization process...")
    
    from src.brain.model import create_coach
    base_coach = create_coach()
    
    optimized_coach = run_optimization(trainset, coaching_quality_metric)
    
    # Step 4: Save optimized state
    save_optimized_state(optimized_coach)
    
    # Step 5: Compare before/after
    test_queries = [
        entries[0].get('question', ''),
        entries[len(entries)//2].get('question', ''),
        entries[-1].get('question', ''),
    ]
    compare_before_after(base_coach, optimized_coach, test_queries)
    
    # Step 6: Report
    print("\n" + "="*70)
    print("✅ Optimization Complete!")
    print("="*70)
    print("""
Next steps:
1. Review before/after comparison above
2. If quality improved:
   - Update src/main.py to load optimized model
   - Restart Discord bot
   - Monitor quality of responses
3. If quality didn't improve:
   - Collect more training examples (30+ recommended)
   - Improve metric scoring
   - Try different training subset
   - Re-run optimization

📝 Note: Remember to commit your optimized state:
   git add data/optimized_coach_state.json
   git commit -m "chore: Update coach optimization"
   git push origin main
""")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
