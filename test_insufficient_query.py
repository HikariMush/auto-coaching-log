#!/usr/bin/env python3
"""
不足質問ハンドラーのテスト
「ヒカリ」とだけ質問した場合の挙動を確認
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.brain.core import SmashBrain

def test_insufficient_query():
    """不足質問のテスト"""
    print("="*70)
    print("🧪 不足質問ハンドラーテスト")
    print("="*70 + "\n")
    
    brain = SmashBrain()
    
    # テストケース1: キャラ名のみ
    print("【テスト1】キャラ名のみの質問")
    question1 = "ヒカリ"
    print(f"質問: {question1}\n")
    
    answer1 = brain(question1)
    print(f"回答:\n{answer1}\n")
    
    # 検証
    checks1 = {
        "[1]が含まれる": "[1]" in answer1,
        "[2]が含まれる": "[2]" in answer1,
        "[3]が含まれる": "[3]" in answer1,
        "質問例が提示される": "？" in answer1 or "?" in answer1,
        "話題リストがある": "①" in answer1 or "1." in answer1 or "・" in answer1,
    }
    
    print("検証結果:")
    for check_name, result in checks1.items():
        status = "✅" if result else "❌"
        print(f"  {status} {check_name}: {'OK' if result else 'NG'}")
    
    print("\n" + "="*70 + "\n")
    
    # テストケース2: 具体的な質問（比較用）
    print("【テスト2】具体的な質問（正常系）")
    question2 = "ヒカリの空前の発生フレームは？"
    print(f"質問: {question2}\n")
    
    answer2 = brain(question2)
    print(f"回答（先頭300文字）:\n{answer2[:300]}...\n")
    
    # 検証
    checks2 = {
        "8Fが含まれる": "8F" in answer2 or "8フレーム" in answer2,
        "正確なデータ": "発生" in answer2,
    }
    
    print("検証結果:")
    for check_name, result in checks2.items():
        status = "✅" if result else "❌"
        print(f"  {status} {check_name}: {'OK' if result else 'NG'}")
    
    print("\n" + "="*70)
    print("🏁 テスト完了")
    print("="*70)

if __name__ == '__main__':
    test_insufficient_query()
