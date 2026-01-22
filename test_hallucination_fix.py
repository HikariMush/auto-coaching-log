#!/usr/bin/env python3
"""
ハルシネーション修正のテスト
ヒカリの空前の発生フレームが正確に回答されるか確認
"""
import sys
import os

# パスを追加
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.brain.core import SmashBrain

def test_hikari_fair():
    """ヒカリの空前の発生フレームテスト"""
    print("="*70)
    print("🧪 ハルシネーション修正テスト: ヒカリの空前")
    print("="*70 + "\n")
    
    brain = SmashBrain()
    
    # テストケース1: 発生フレームを質問
    print("【テスト1】発生フレームを質問")
    question1 = "ヒカリの空前の発生フレームは何F？"
    print(f"質問: {question1}\n")
    
    answer1 = brain(question1)
    print(f"回答:\n{answer1}\n")
    
    # 検証
    if "8F" in answer1 or "8フレーム" in answer1 or "発生】8F" in answer1:
        print("✅ 正解: 8Fが含まれています")
    else:
        print("❌ 不正解: 8Fが含まれていません")
    
    if "7F" in answer1 or "9F" in answer1:
        print("⚠️  警告: 間違った数値が含まれています")
    
    print("\n" + "="*70 + "\n")
    
    # テストケース2: 全体的な技データを質問
    print("【テスト2】技の詳細データを質問")
    question2 = "ヒカリの空前について教えて"
    print(f"質問: {question2}\n")
    
    answer2 = brain(question2)
    print(f"回答:\n{answer2}\n")
    
    # 検証
    checks = {
        "発生8F": "8F" in answer2 or "8フレーム" in answer2,
        "全体37F": "37F" in answer2 or "37フレーム" in answer2,
        "ダメージ7%": "7%" in answer2 or "7.0%" in answer2,
        "1v1 8.4%": "8.4%" in answer2,
    }
    
    print("検証結果:")
    for check_name, result in checks.items():
        status = "✅" if result else "❌"
        print(f"  {status} {check_name}: {'OK' if result else 'NG'}")
    
    print("\n" + "="*70)
    print("🏁 テスト完了")
    print("="*70)

if __name__ == '__main__':
    test_hikari_fair()
