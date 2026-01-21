#!/usr/bin/env python3
"""
SmashZettel-Bot: Cost Estimation & Feature Approval Tool

Calculates precise costs for optimization cycle features and awaits user approval
before implementing each feature.

Features:
1. Notion 差分検出 & 同期
2. Pinecone → ローカル反映
3. ローカル → Notion 反映
4. LLM モデル選択 (Flash/Pro/Thinking)
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple


class CostCalculator:
    """Calculate API costs for each feature"""
    
    # API pricing (as of 2026-01)
    PRICING = {
        'gemini_embedding': {
            'model': 'embedding-001',
            'free_tier': 60000,  # tokens/month
            'price_per_1m_tokens': 0.075,
        },
        'gemini_flash': {
            'model': 'Gemini 2.0 Flash',
            'input_price': 0.075,    # per 1M tokens
            'output_price': 0.30,    # per 1M tokens
        },
        'gemini_pro': {
            'model': 'Gemini 2.0 Pro',
            'input_price': 1.50,
            'output_price': 6.00,
        },
        'gemini_thinking': {
            'model': 'Gemini 2.0 Thinking',
            'input_price': 6.00,
            'output_price': 24.00,
        },
        'pinecone': {
            'storage_per_vector_month': 0.10,
        },
    }
    
    # Default assumptions
    ASSUMPTIONS = {
        'current_vectors': 100,          # raw_data 50 + Notion 42
        'tokens_per_notion_page': 750,
        'tokens_per_embedding_trial_input': 600,
        'tokens_per_embedding_trial_output': 500,
        'teleprompter_trials': 100,
        'new_notion_pages_per_month': 5,
        'new_vectors_per_optimization': 0,  # Prompts don't create new vectors
    }
    
    def __init__(self):
        self.assumptions = self.ASSUMPTIONS.copy()
    
    def calc_embedding_cost(self, token_count: int) -> float:
        """Calculate embedding cost for tokens"""
        free_tier = self.PRICING['gemini_embedding']['free_tier']
        
        if token_count <= free_tier:
            return 0.0
        
        excess_tokens = token_count - free_tier
        price_per_token = self.PRICING['gemini_embedding']['price_per_1m_tokens'] / 1_000_000
        return excess_tokens * price_per_token
    
    def calc_teleprompter_cost(self, model: str, trials: int) -> float:
        """Calculate Teleprompter optimization cost"""
        model_key = f'gemini_{model.lower()}'
        if model_key not in self.PRICING:
            raise ValueError(f"Unknown model: {model}")
        
        pricing = self.PRICING[model_key]
        
        # Per trial costs
        input_tokens = self.assumptions['tokens_per_embedding_trial_input'] * trials
        output_tokens = self.assumptions['tokens_per_embedding_trial_output'] * trials
        
        # Calculate costs
        input_cost = (input_tokens / 1_000_000) * pricing['input_price']
        output_cost = (output_tokens / 1_000_000) * pricing['output_price']
        
        return input_cost + output_cost
    
    def calc_pinecone_cost(self, vector_count: int) -> float:
        """Calculate monthly Pinecone storage cost"""
        per_vector = self.PRICING['pinecone']['storage_per_vector_month']
        return vector_count * per_vector
    
    def feature_1_cost(self) -> Dict[str, float]:
        """Feature 1: Notion 差分検出 & 同期"""
        # Assume 5 new/updated pages per month
        tokens = self.assumptions['new_notion_pages_per_month'] * self.assumptions['tokens_per_notion_page']
        embedding_cost = self.calc_embedding_cost(tokens)
        
        return {
            'name': '1. Notion 差分検出 & 同期',
            'tokens': tokens,
            'monthly_cost': embedding_cost,
            'description': f"{self.assumptions['new_notion_pages_per_month']}ページ/月の埋め込み",
        }
    
    def feature_2_cost(self) -> Dict[str, float]:
        """Feature 2: Pinecone → ローカル反映"""
        # Pure local operation, no API cost
        return {
            'name': '2. Pinecone → ローカル反映',
            'tokens': 0,
            'monthly_cost': 0.0,
            'description': 'ローカルストレージのみ (API 呼び出し無制限)',
        }
    
    def feature_3_cost(self) -> Dict[str, float]:
        """Feature 3: ローカル → Notion 反映"""
        # Notion API は無料だが埋め込みが必要な場合がある
        tokens = self.assumptions['new_vectors_per_optimization'] * 1000
        embedding_cost = self.calc_embedding_cost(tokens)
        
        return {
            'name': '3. ローカル → Notion 反映',
            'tokens': tokens,
            'monthly_cost': embedding_cost,
            'description': 'Notion API は無料, 埋め込みは不要想定',
        }
    
    def teleprompter_cost_by_model(self) -> Dict[str, Dict]:
        """Calculate Teleprompter costs for each model"""
        trials = self.assumptions['teleprompter_trials']
        
        costs = {}
        for model in ['flash', 'pro', 'thinking']:
            cost = self.calc_teleprompter_cost(model, trials)
            costs[model] = {
                'model': self.PRICING[f'gemini_{model}']['model'],
                'trials': trials,
                'cost': cost,
            }
        
        return costs
    
    def total_monthly_cost(self, features: List[str], model: str = 'flash') -> Dict:
        """Calculate total monthly cost"""
        feature_costs = {
            'feature_1': self.feature_1_cost()['monthly_cost'] if '1' in features else 0,
            'feature_2': self.feature_2_cost()['monthly_cost'] if '2' in features else 0,
            'feature_3': self.feature_3_cost()['monthly_cost'] if '3' in features else 0,
            'teleprompter': self.calc_teleprompter_cost(model, self.assumptions['teleprompter_trials']),
            'pinecone': self.calc_pinecone_cost(self.assumptions['current_vectors']),
        }
        
        total = sum(feature_costs.values())
        
        return {
            'breakdown': feature_costs,
            'total': total,
            'annual': total * 12,
        }


def print_banner(title: str):
    """Print section banner"""
    print(f"\n{'='*80}")
    print(f"💰 {title}")
    print(f"{'='*80}\n")


def show_feature_costs():
    """Show individual feature costs"""
    print_banner("機能別コスト分析")
    
    calc = CostCalculator()
    
    features = [
        calc.feature_1_cost(),
        calc.feature_2_cost(),
        calc.feature_3_cost(),
    ]
    
    for i, feature in enumerate(features, 1):
        print(f"【{feature['name']}】")
        print(f"  説明: {feature['description']}")
        print(f"  Token: {feature['tokens']:,}")
        
        if feature['monthly_cost'] == 0:
            print(f"  月額コスト: ✅ $0.00 (無料)")
        else:
            print(f"  月額コスト: ${feature['monthly_cost']:.2f}")
        
        print()


def show_model_comparison():
    """Show LLM model cost comparison"""
    print_banner("LLM モデル別コスト比較 (100 試行)")
    
    calc = CostCalculator()
    costs = calc.teleprompter_cost_by_model()
    
    print(f"{'モデル':<20} {'コスト/100試行':<20} {'特徴':<40}")
    print("-" * 80)
    
    models_info = {
        'flash': '高速, 安い (推奨)',
        'pro': '中程度品質',
        'thinking': '高品質 (遅い)',
    }
    
    for model, info in costs.items():
        print(f"{info['model']:<20} ${info['cost']:<18.2f} {models_info[model]:<40}")
    
    print(f"\n✅ 推奨: Flash モデル ($0.02)")
    print(f"   Pro に変更した場合の追加コスト: ${costs['pro']['cost'] - costs['flash']['cost']:.2f}/100試行\n")


def show_total_cost_scenarios():
    """Show total monthly cost scenarios"""
    print_banner("シナリオ別月額コスト")
    
    calc = CostCalculator()
    
    scenarios = [
        {
            'name': 'シナリオ A: 最小実装',
            'features': [],
            'model': 'flash',
        },
        {
            'name': 'シナリオ B: 推奨実装',
            'features': ['1', '2'],
            'model': 'flash',
        },
        {
            'name': 'シナリオ C: 完全実装',
            'features': ['1', '2', '3'],
            'model': 'flash',
        },
        {
            'name': 'シナリオ D: 完全 + Pro',
            'features': ['1', '2', '3'],
            'model': 'pro',
        },
    ]
    
    for scenario in scenarios:
        costs = calc.total_monthly_cost(scenario['features'], scenario['model'])
        
        print(f"【{scenario['name']}】")
        print(f"  機能: {', '.join([f'機能{f}' for f in scenario['features']]) if scenario['features'] else 'なし'}")
        print(f"  LLM: {scenario['model'].upper()}")
        print(f"  月額: ${costs['total']:.2f}")
        print(f"  年間: ${costs['annual']:.2f}")
        
        # Show breakdown
        if costs['breakdown']['feature_1'] > 0:
            print(f"    - 機能 1: ${costs['breakdown']['feature_1']:.2f}")
        if costs['breakdown']['feature_2'] > 0:
            print(f"    - 機能 2: ${costs['breakdown']['feature_2']:.2f}")
        if costs['breakdown']['feature_3'] > 0:
            print(f"    - 機能 3: ${costs['breakdown']['feature_3']:.2f}")
        print(f"    - Teleprompter: ${costs['breakdown']['teleprompter']:.2f}")
        print(f"    - Pinecone: ${costs['breakdown']['pinecone']:.2f}")
        print()


def approval_form():
    """Interactive approval form"""
    print_banner("承認フォーム")
    
    print("""
これから以下の項目について、あなたの承認を得ます。

推奨設定:
  ✅ 機能 1 (Notion 差分検出 & 同期)
  ✅ 機能 2 (Pinecone → ローカル反映)
  ⚠️  機能 3 (ローカル → Notion 反映)
  ✅ Flash モデル
  
推奨月額: $10.02
年間: $120.24
    """)
    
    approvals = {}
    
    # Feature 1
    while True:
        resp = input("【機能 1】Notion 差分検出 & 同期を実装しますか？(y/n/q) ").strip().lower()
        if resp in ['y', 'n', 'q']:
            approvals['feature_1'] = resp == 'y'
            if resp == 'q':
                return None
            break
    
    # Feature 2
    while True:
        resp = input("【機能 2】Pinecone → ローカル反映を実装しますか？(y/n/q) ").strip().lower()
        if resp in ['y', 'n', 'q']:
            approvals['feature_2'] = resp == 'y'
            if resp == 'q':
                return None
            break
    
    # Feature 3
    while True:
        resp = input("【機能 3】ローカル → Notion 反映を実装しますか？(y/n/q) ").strip().lower()
        if resp in ['y', 'n', 'q']:
            approvals['feature_3'] = resp == 'y'
            if resp == 'q':
                return None
            break
    
    # LLM Model
    while True:
        resp = input("【LLM モデル】Flash(推奨), Pro, Thinking?(f/p/t/q) ").strip().lower()
        if resp in ['f', 'p', 't', 'q']:
            if resp == 'q':
                return None
            model_map = {'f': 'flash', 'p': 'pro', 't': 'thinking'}
            approvals['llm_model'] = model_map[resp]
            break
    
    return approvals


def save_approval(approvals: Dict):
    """Save approval decision"""
    approval_file = Path('data/feature_approvals.json')
    approval_file.parent.mkdir(exist_ok=True)
    
    record = {
        'timestamp': datetime.now().isoformat(),
        'approvals': approvals,
        'calc_version': '1.0',
    }
    
    approval_file.write_text(json.dumps(record, indent=2))
    print(f"\n✅ 承認内容を保存しました: {approval_file}")


def main():
    """Main execution"""
    print("\n" + "="*80)
    print("🤖 SmashZettel-Bot: 最適化パイプライン コスト分析 & 承認ツール")
    print("="*80)
    
    # Step 1: Show feature costs
    show_feature_costs()
    
    # Step 2: Show model comparison
    show_model_comparison()
    
    # Step 3: Show total cost scenarios
    show_total_cost_scenarios()
    
    # Step 4: Get approval
    print("\n" + "="*80)
    print("次のステップに進みます")
    print("="*80)
    
    approvals = approval_form()
    
    if approvals is None:
        print("\n❌ キャンセルしました")
        return
    
    # Show final decision
    print("\n" + "="*80)
    print("✅ あなたの選択")
    print("="*80)
    
    calc = CostCalculator()
    features = [k.replace('feature_', '') for k, v in approvals.items() if k.startswith('feature_') and v]
    total_cost = calc.total_monthly_cost(features, approvals.get('llm_model', 'flash'))
    
    print(f"\n実装機能:")
    if approvals['feature_1']:
        print(f"  ✅ 機能 1: Notion 差分検出 & 同期")
    else:
        print(f"  ❌ 機能 1: Notion 差分検出 & 同期")
    
    if approvals['feature_2']:
        print(f"  ✅ 機能 2: Pinecone → ローカル反映")
    else:
        print(f"  ❌ 機能 2: Pinecone → ローカル反映")
    
    if approvals['feature_3']:
        print(f"  ✅ 機能 3: ローカル → Notion 反映")
    else:
        print(f"  ❌ 機能 3: ローカル → Notion 反映")
    
    print(f"\nLLM モデル: {approvals['llm_model'].upper()}")
    print(f"\n月額費用: ${total_cost['total']:.2f}")
    print(f"年間費用: ${total_cost['annual']:.2f}")
    
    # Save approval
    save_approval(approvals)
    
    print("\n" + "="*80)
    print("🚀 次のステップ")
    print("="*80)
    print("""
1. このツールを再度実行してから承認内容を確認
2. 承認内容に基づいて機能を実装開始
3. data/feature_approvals.json に承認内容が保存されます
    """)


if __name__ == '__main__':
    main()
