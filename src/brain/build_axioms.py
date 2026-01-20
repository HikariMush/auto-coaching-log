import os
import json
import dspy
import sys
import io
import glob
import re
from google import genai

# リアルタイム出力の強制設定
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

def select_verified_best_brain():
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    client = genai.Client(api_key=api_key)
    try:
        # 1. 物理的に存在する全モデルをスキャン
        available_list = list(client.models.list())
        candidates = []
        
        # 除外キーワード：憲法編纂には「最高解像度の知能」が必要なため軽量級や画像用を排除
        banned = ["nano", "flash", "imagen", "vision", "medlm", "aqa", "embedding"]
        
        for m in available_list:
            name_lower = m.name.lower()
            
            # 論理的防壁：テキスト生成を正式にサポートしているか物理検証 [cite: 2026-01-16]
            if "generateContent" not in m.supported_methods:
                continue
            if any(x in name_lower for x in banned):
                continue
            
            # スコアリング：2.5 Proがあれば2.5 Pro、2.0 Ultraがあれば2.0 Ultraを強制選定
            score = 0
            if "ultra" in name_lower: score += 10000
            elif "pro" in name_lower: score += 5000
            
            # バージョン加点：2.5 > 2.0 > 1.5
            v_match = re.search(r"(\d+)\.(\d+)", name_lower)
            if v_match:
                score += int(v_match.group(1)) * 500 + int(v_match.group(2)) * 50
            
            # 実験版(exp/preview)は推論能力が強化されているため加点 [cite: 2026-01-16]
            if any(x in name_lower for x in ["exp", "preview"]):
                score += 100
            
            candidates.append((score, m.name))
        
        # 降順ソート
        candidates.sort(key=lambda x: x[0], reverse=True)
        
        if not candidates:
            # 万が一のフォールバックも、確実なProを指定
            return "gemini/gemini-1.5-pro"
            
        final_target = candidates[0][1].split("/")[-1]
        return f"gemini/{final_target}"
        
    except Exception as e:
        print(f"Selection Critical Failure: {e}")
        return "gemini/gemini-1.5-pro"

# 最強知能の確定と起動
active_brain = select_verified_best_brain()
print(f"SZ Logic Engine (Verified Best): {active_brain}")

lm = dspy.LM(active_brain, api_key=os.getenv("GEMINI_API_KEY").strip())
dspy.settings.configure(lm=lm)

class SmashConstitution(dspy.Signature):
    """
    Wiki全文から不変の物理・仕様を『憲法』として定義せよ。
    - 42項目の相互依存（例：シールドと吹っ飛みの関係）を論理的に整理すること。
    - 数式は LaTeX ($) を使用。
    - 抽出した理論の物理的整合性を再帰的に検証し、矛盾があれば指摘せよ。
    """
    page_title = dspy.InputField()
    full_text = dspy.InputField()
    axioms = dspy.OutputField(desc="数式、フレーム定数、例外仕様の厳密なリスト")
    self_critique = dspy.OutputField(desc="論理的矛盾のチェック結果")

def build_brain():
    data_files = sorted(glob.glob("src/brain/raw_data/*.txt"))
    if not data_files:
        print("Error: src/brain/raw_data/ is empty.")
        return

    analyzer = dspy.ChainOfThought(SmashConstitution)
    final_constitution = []
    total = len(data_files)

    print(f"--- SZ完全憲法編纂プロセス：全 {total} ファイル ---")

    for i, file_path in enumerate(data_files):
        title = os.path.basename(file_path).replace(".txt", "")
        progress = ((i + 1) / total) * 100
        print(f"\n[{progress:.1f}%] 最高解像度解析中: {title}")
        
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if len(content.strip()) > 50:
            # Pro/Ultraモデルによる深層論理抽出
            result = analyzer(page_title=title, full_text=content)
            
            print(f"--- {title} 憲法抽出成果（プレビュー） ---")
            print(result.axioms[:700] + "...")
            print(f"--- 論理整合性検証: {result.self_critique[:200]} ---\n")
            
            final_constitution.append({
                "category": title,
                "axioms": result.axioms,
                "logical_verification": result.self_critique
            })
        else:
            print(f"Skipped: {title}")

    with open("pending_basic_theory.json", "w", encoding="utf-8") as f:
        json.dump(final_constitution, f, ensure_ascii=False, indent=2)
    print("\n--- DONE: SZ完全憲法（最強知能同期版）を統合しました ---")

if __name__ == "__main__":
    build_brain()
