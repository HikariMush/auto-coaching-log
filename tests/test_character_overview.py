#!/usr/bin/env python3
"""
キャラクター概要機能のテスト
「ヒカリ」とだけ質問した場合の挙動を確認
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.brain.core import SmashBrain

def test_character_overview():
    """キャラクター名のみの質問テスト"""
    print("="*70)
    print("🧪 キャラクター概要機能テスト")
    print("="*70 + "\n")
    
    brain = SmashBrain()
    
    # テスト: ヒカリとだけ質問
    question = "ヒカリ"
    print(f"質問: {question}\n")
    
    answer = brain(question)
    print(f"回答:\n{answer}\n")
    
    # 検証
    checks = {
        "概要セクション": "[1]" in answer,
        "主要技セクション": "[2]" in answer,
        "深掘りガイド": "[3]" in answer or "さらに" in answer or "詳しく" in answer,
        "正確なデータ": any(f"{i}F" in answer for i in range(1, 20)),
    }
    
    print("\n" + "="*70)
    print("検証結果:")
    for check_name, result in checks.items():
        status = "✅" if result else "❌"
        print(f"  {status} {check_name}: {'OK' if result else 'NG'}")
    
    print("\n" + "="*70)
    print("🏁 テスト完了")
    print("="*70)

if __name__ == '__main__':
    test_character_overview()
