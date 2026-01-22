#!/usr/bin/env python3
"""
SmashZettel-Bot: Coach Optimizer
Runs dspy.Teleprompter optimization on collected training data.

V2機能:
- 要素別最適化: 各要素（[1]〜[4]）を個別に最適化
- 全文最適化との併用

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

# --- 要素別Signature定義 ---
class FrameDataElement(dspy.Signature):
    """[1] フレームデータ・基礎情報の生成に特化したSignature"""
    context = dspy.InputField(desc="検索されたフレームデータ")
    question = dspy.InputField(desc="ユーザーの質問")
    frame_data_info = dspy.OutputField(desc="発生F、全体F、ダメージ%などの数値データ。簡潔かつ正確に。")

class TechnicalElement(dspy.Signature):
    """[2] 技術的解説の生成に特化したSignature"""
    context = dspy.InputField(desc="技術的な理論データ")
    question = dspy.InputField(desc="ユーザーの質問")
    technical_explanation = dspy.OutputField(desc="硬直差の計算、確定反撃、コンボルートなど。計算式を明記。")

class PracticalElement(dspy.Signature):
    """[3] 実戦での使い方の生成に特化したSignature"""
    context = dspy.InputField(desc="立ち回り・戦術データ")
    question = dspy.InputField(desc="ユーザーの質問")
    practical_usage = dspy.OutputField(desc="具体的な使用場面、リスク・リターン、状況別の選択肢。3つ以上の具体例を含める。")

class NotesElement(dspy.Signature):
    """[4] 補足・注意点の生成に特化したSignature"""
    context = dspy.InputField(desc="キャラ差・注意点データ")
    question = dspy.InputField(desc="ユーザーの質問")
    notes_and_tips = dspy.OutputField(desc="キャラ差、初心者向けアドバイス、よくある間違いなど。")

# Configuration
DATA_DIR = Path(__file__).parent.parent.parent / 'data'
TRAINING_DATA_FILE = DATA_DIR / 'training_data.jsonl'
ELEMENT_FEEDBACK_FILE = DATA_DIR / 'element_feedback.jsonl'
OPTIMIZED_STATE_FILE = DATA_DIR / 'optimized_coach_state.json'
OPTIMIZATION_HISTORY_DIR = DATA_DIR / 'optimization_history'
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

def load_element_feedback() -> List[Dict[str, Any]]:
    """Load element-specific feedback from JSONL file"""
    if not ELEMENT_FEEDBACK_FILE.exists():
        print(f"📝 Element feedback not found: {ELEMENT_FEEDBACK_FILE}")
        return []
    
    entries = []
    with open(ELEMENT_FEEDBACK_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    
    print(f"✅ Loaded {len(entries)} element-specific feedback entries")
    return entries

def analyze_element_patterns(element_feedback: List[Dict]) -> Dict[int, List[str]]:
    """Analyze common improvement patterns for each element"""
    patterns = {1: [], 2: [], 3: [], 4: []}
    
    for entry in element_feedback:
        element_num = entry.get('element_number')
        correction = entry.get('correction', '')
        
        if element_num in patterns:
            patterns[element_num].append(correction)
    
    # Summarize patterns
    summary = {}
    for element_num, corrections in patterns.items():
        if corrections:
            summary[element_num] = {
                'count': len(corrections),
                'examples': corrections[:3]  # Top 3 examples
            }
    
    return summary

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
    4. Tone: Is tone calm and objective (not overly enthusiastic)?
    
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
    tone_score = measure_tone_calmness(pred_text)
    
    # Combine with weights
    final_score = (
        0.35 * relevance_score +
        0.25 * specificity_score +
        0.25 * actionability_score +
        0.15 * tone_score
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

def measure_tone_calmness(text: str) -> float:
    """
    Measure tone calmness: Is the response calm and objective?
    
    Heuristics:
    - Penalty for overly enthusiastic expressions (「絶対に！」「超強い！」etc.)
    - Penalty for excessive exclamation marks
    - Bonus for analytical terms (「分析すると」「データから」etc.)
    - Bonus for conditional/balanced language (「ただし」「場合による」etc.)
    
    Returns:
        float: Calmness score 0.0-1.0 (higher = calmer)
    """
    if not text:
        return 0.5
    
    score = 1.0  # Start at maximum calmness
    
    # Penalty: Overly enthusiastic expressions
    enthusiastic_phrases = [
        '絶対に', '超強い', '超重要', '最強', '必ず勝てる', 'めちゃくちゃ',
        'ヤバい', 'ぶっ壊れ', '圧倒的', '完璧', '無敵'
    ]
    for phrase in enthusiastic_phrases:
        count = text.count(phrase)
        score -= count * 0.1
    
    # Penalty: Excessive exclamation marks
    exclamation_count = text.count('！') + text.count('!')
    if exclamation_count > 3:
        score -= (exclamation_count - 3) * 0.05
    
    # Penalty: All-caps enthusiasm (rarely applies to Japanese but check anyway)
    import re
    all_caps_words = re.findall(r'\b[A-Z]{3,}\b', text)
    score -= len(all_caps_words) * 0.05
    
    # Bonus: Analytical/objective language
    analytical_terms = [
        '分析すると', 'データから', '統計的に', '客観的に', '検証すると',
        '理論上', '実際には', '確率的に', '数値的に'
    ]
    analytical_count = sum(1 for term in analytical_terms if term in text)
    score += analytical_count * 0.05
    
    # Bonus: Balanced/conditional language
    balanced_terms = [
        'ただし', '場合による', '状況次第', 'ケースバイケース', '一概には',
        '必ずしも', 'とは限らない', '可能性がある', '傾向がある'
    ]
    balanced_count = sum(1 for term in balanced_terms if term in text)
    score += balanced_count * 0.05
    
    # Bonus: Calm instructional language
    calm_phrases = [
        '考えられます', '推奨します', '検討してください', 'おすすめです',
        '有効です', '効果的です', '参考にしてください'
    ]
    calm_count = sum(1 for phrase in calm_phrases if phrase in text)
    score += calm_count * 0.03
    
    return max(0.0, min(1.0, score))

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

def compare_before_after(base_coach: Any, optimized_coach: Any, test_queries: List[str]) -> List[Dict]:
    """
    Compare predictions before and after optimization
    
    Returns:
        List[Dict]: 比較結果のリスト（履歴保存用）
    """
    
    print("\n" + "="*70)
    print("📊 Before vs After Comparison")
    print("="*70)
    
    comparisons = []
    
    for i, query in enumerate(test_queries[:3], 1):
        print(f"\n{'─'*70}")
        print(f"Query {i}: {query}")
        print(f"{'─'*70}")
        
        comparison = {
            "query": query,
            "before": {},
            "after": {}
        }
        
        try:
            pred_before = base_coach.forward(query)
            before_text = str(pred_before.analysis) + "\n" + str(pred_before.advice)
            comparison["before"] = {
                "analysis": str(pred_before.analysis),
                "advice": str(pred_before.advice)
            }
            print(f"\n📌 BEFORE Optimization:")
            print(f"   Analysis: {str(pred_before.analysis)[:100]}...")
            print(f"   Advice: {str(pred_before.advice)[:100]}...")
        except Exception as e:
            print(f"   ❌ Error: {e}")
            comparison["before"]["error"] = str(e)
        
        try:
            pred_after = optimized_coach.forward(query)
            after_text = str(pred_after.analysis) + "\n" + str(pred_after.advice)
            comparison["after"] = {
                "analysis": str(pred_after.analysis),
                "advice": str(pred_after.advice)
            }
            print(f"\n✨ AFTER Optimization:")
            print(f"   Analysis: {str(pred_after.analysis)[:100]}...")
            print(f"   Advice: {str(pred_after.advice)[:100]}...")
        except Exception as e:
            print(f"   ❌ Error: {e}")
            comparison["after"]["error"] = str(e)
        
        comparisons.append(comparison)
    
    return comparisons

def save_optimization_history(
    timestamp: str,
    training_count: int,
    element_feedback_count: int,
    comparisons: List[Dict],
    optimized_elements: Dict[int, Any]
) -> str:
    """
    最適化履歴を保存
    
    Args:
        timestamp: 実行日時
        training_count: トレーニングデータ数
        element_feedback_count: 要素別フィードバック数
        comparisons: Before/After比較結果
        optimized_elements: 最適化された要素
    
    Returns:
        str: 保存したファイルのパス
    """
    OPTIMIZATION_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    
    # ファイル名: YYYYMMDD_HHMMSS_optimization.md
    filename = f"{timestamp.replace(':', '').replace('-', '').replace('.', '')[:15]}_optimization.md"
    filepath = OPTIMIZATION_HISTORY_DIR / filename
    
    # Markdown形式でレポート生成
    report = f"""# 最適化履歴レポート

**実行日時**: {timestamp}

## 📊 データ統計

- **トレーニングデータ**: {training_count}件
- **要素別フィードバック**: {element_feedback_count}件
- **最適化された要素数**: {len(optimized_elements)}個

## 🔧 最適化された要素

"""
    
    element_names = {
        1: "フレームデータ・基礎情報",
        2: "技術的解説",
        3: "実戦での使い方",
        4: "補足・注意点"
    }
    
    for elem_num in sorted(optimized_elements.keys()):
        report += f"- [{elem_num}] {element_names.get(elem_num, 'Unknown')}\n"
    
    report += f"\n## 📝 Before vs After 比較\n\n"
    
    for i, comp in enumerate(comparisons, 1):
        report += f"### テストケース {i}\n\n"
        report += f"**質問**: {comp['query']}\n\n"
        
        if "error" not in comp["before"]:
            report += f"#### 📌 BEFORE（最適化前）\n\n"
            report += f"**Analysis**:\n```\n{comp['before'].get('analysis', 'N/A')[:300]}\n```\n\n"
            report += f"**Advice**:\n```\n{comp['before'].get('advice', 'N/A')[:300]}\n```\n\n"
        
        if "error" not in comp["after"]:
            report += f"#### ✨ AFTER（最適化後）\n\n"
            report += f"**Analysis**:\n```\n{comp['after'].get('analysis', 'N/A')[:300]}\n```\n\n"
            report += f"**Advice**:\n```\n{comp['after'].get('advice', 'N/A')[:300]}\n```\n\n"
        
        # 変化の分析
        if "error" not in comp["before"] and "error" not in comp["after"]:
            before_len = len(comp['before'].get('advice', ''))
            after_len = len(comp['after'].get('advice', ''))
            report += f"**変化**: 回答長 {before_len}文字 → {after_len}文字（{after_len - before_len:+d}文字）\n\n"
        
        report += "---\n\n"
    
    report += f"""## 🚀 次のステップ

1. このレポートを確認して、改善の方向性を評価
2. 改善が不十分な場合:
   - さらにフィードバックを収集（特に弱い要素）
   - メトリックを調整
   - 再度最適化を実行
3. 改善が十分な場合:
   - Botを再起動して新しいモデルを適用
   - ユーザーからの評価を収集

## 📝 メモ

- 前回の最適化からの差分を確認する場合、前回のレポートと比較してください
- 最適化は段階的に改善するため、1回で完璧になるとは限りません
- 定期的な最適化（2週間に1回程度）を推奨します
"""
    
    # ファイルに保存
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\n📄 Optimization history saved to: {filepath}")
    return str(filepath)

def optimize_element(element_number: int, element_feedback: List[Dict], element_signature, metric: Callable) -> Any:
    """
    特定の要素を個別に最適化
    
    Args:
        element_number: 要素番号（1-4）
        element_feedback: その要素に関するフィードバックリスト
        element_signature: 要素用のSignature（FrameDataElement等）
        metric: 評価メトリック
    
    Returns:
        最適化されたモデル
    """
    if not element_feedback:
        print(f"  ⚠️  No feedback for element {element_number}, skipping...")
        return None
    
    print(f"\n  📝 Optimizing element {element_number} with {len(element_feedback)} examples...")
    
    # フィードバックをDSPy Exampleに変換
    element_dataset = []
    for fb in element_feedback:
        example = dspy.Example(
            question=fb.get('question', ''),
            correction=fb.get('correction', ''),
            context=""  # 簡略化のためcontextは空
        ).with_inputs('question', 'context')
        element_dataset.append(example)
    
    # 最適化実行
    try:
        base_module = dspy.ChainOfThought(element_signature)
        
        # Teleprompter で最適化（試行回数を減らす）
        optimizer = dspy.Teleprompter(
            metric=metric,
            trainset=element_dataset,
            valset=element_dataset[:max(1, len(element_dataset)//5)],
            num_trials=20,  # 要素別なので軽く
            seed=42
        )
        
        optimized = optimizer.compile(
            student=base_module,
            trainset=element_dataset,
            metric=metric
        )
        
        print(f"  ✅ Element {element_number} optimization complete")
        return optimized
        
    except Exception as e:
        print(f"  ⚠️  Element {element_number} optimization failed: {e}")
        return None

def main():
    """Main optimization pipeline (V2: 要素別最適化対応)"""
    
    print("\n" + "="*70)
    print("🚀 SmashZettel-Bot: Coach Optimizer V2 (要素別最適化対応)")
    print("="*70)
    
    # Step 1: Load training data
    print("\n📂 Loading training data...")
    entries = load_training_data()
    
    if not entries:
        print(f"❌ No training data found. Run the bot first to collect /teach corrections.")
        return 1
    
    print(f"✅ Loaded {len(entries)} training examples")
    
    # Step 1.5: Load and analyze element feedback
    print("\n🔍 Loading element-specific feedback...")
    element_feedback = load_element_feedback()
    
    element_patterns = {}
    if element_feedback:
        element_patterns = analyze_element_patterns(element_feedback)
        print("\n📊 Element Feedback Analysis:")
        element_names = {
            1: "フレームデータ・基礎情報",
            2: "技術的解説",
            3: "実戦での使い方",
            4: "補足・注意点"
        }
        for elem_num, data in element_patterns.items():
            print(f"\n  [{elem_num}] {element_names[elem_num]}")
            print(f"      フィードバック数: {data['count']}件")
            print(f"      改善例:")
            for i, example in enumerate(data['examples'][:2], 1):
                print(f"        {i}. {example[:80]}{'...' if len(example) > 80 else ''}")
    
    if len(entries) < MIN_TRAINING_EXAMPLES:
        print(f"\n⚠️  Warning: Only {len(entries)} examples.")
        print(f"   Minimum recommended: {MIN_TRAINING_EXAMPLES}")
        print(f"   Optimization quality may be poor with fewer examples.")
    
    # Step 2: Prepare DSPy dataset
    print("\n📊 Preparing DSPy dataset...")
    trainset = prepare_dspy_dataset(entries)
    print(f"✅ Prepared {len(trainset)} examples")
    
    # Step 2.5: 要素別最適化（element_feedbackがある場合）
    optimized_elements = {}
    if element_feedback and len(element_feedback) >= 10:
        print("\n🔧 Running element-specific optimization...")
        
        # 要素別にフィードバックを分類
        elements_data = {1: [], 2: [], 3: [], 4: []}
        for fb in element_feedback:
            elem_num = fb.get('element_number')
            if elem_num in elements_data:
                elements_data[elem_num].append(fb)
        
        # 各要素を個別に最適化
        element_signatures = {
            1: FrameDataElement,
            2: TechnicalElement,
            3: PracticalElement,
            4: NotesElement
        }
        
        for elem_num in [1, 2, 3, 4]:
            if elements_data[elem_num]:
                optimized = optimize_element(
                    elem_num,
                    elements_data[elem_num],
                    element_signatures[elem_num],
                    coaching_quality_metric
                )
                if optimized:
                    optimized_elements[elem_num] = optimized
        
        print(f"\n✅ Optimized {len(optimized_elements)} elements individually")
    
    # Step 3: Run optimization
    print("\n🔧 Starting full model optimization...")
    
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
    comparisons = compare_before_after(base_coach, optimized_coach, test_queries)
    
    # Step 5.5: Save optimization history
    timestamp = datetime.now().isoformat()
    history_file = save_optimization_history(
        timestamp=timestamp,
        training_count=len(entries),
        element_feedback_count=len(element_feedback) if element_feedback else 0,
        comparisons=comparisons,
        optimized_elements=optimized_elements
    )
    
    # Step 6: Report
    print("\n" + "="*70)
    print("✅ Optimization Complete!")
    print("="*70)
    
    # Enhanced report with element feedback
    element_summary = ""
    if element_feedback:
        total_element_fb = len(element_feedback)
        element_summary = f"""
📊 Element-Specific Feedback Summary:
   Total: {total_element_fb}件
   要素別の改善パターンが学習されました。
   詳細は上記の「Element Feedback Analysis」を参照してください。
"""
    
    print(f"""
📄 最適化履歴レポート: {history_file}

Next steps:
1. Review before/after comparison above and optimization history report
2. If quality improved:
   - Update src/main.py to load optimized model
   - Restart Discord bot
   - Monitor quality of responses
3. If quality didn't improve:
   - Collect more training examples (30+ recommended)
   - Use /teach_element for focused improvements
   - Improve metric scoring
   - Re-run optimization
{element_summary}
📝 Note: Remember to commit your optimized state:
   git add data/optimized_coach_state.json data/element_feedback.jsonl data/optimization_history/
   git commit -m "chore: Update coach optimization"
   git push origin main
""")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
