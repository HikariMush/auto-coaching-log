import os
import json
import dspy
import sys
import io
import glob
import re
import time
from google import genai

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

def find_ultimate_logic_engine():
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    client = genai.Client(api_key=api_key)
    print("📡 物理知能の最終評価フェーズ開始...", flush=True)
    
    try:
        all_models = list(client.models.list())
        candidates = []
        
        # 排除対象（画像生成、埋め込み、軽量モデル、実験的機能） [cite: 2026-01-16]
        ban_list = ["nano", "imagen", "veo", "embedding", "gecko", "aqa", "vision", "audio", "tts", "robotics", "computer-use", "deep-research"]

        for m in all_models:
            full_id = m.name # models/gemini-3-pro-preview 等
            raw_id = full_id.lower()
            
            if not "gemini" in raw_id and not "gemma" in raw_id: continue
            if any(x in raw_id for x in ban_list): continue
            
            # 知能スコアリング：Versionを100倍、Tierを補正 [cite: 2026-01-16]
            score = 0
            v_match = re.search(r"(\d+\.?\d*)", raw_id)
            if v_match:
                score += float(v_match.group(1)) * 100
            
            if "ultra" in raw_id: score += 50
            elif "pro" in raw_id: score += 30
            elif "thinking" in raw_id: score += 40
            
            if "preview" in raw_id or "exp" in raw_id:
                score += 5
                
            candidates.append({"score": score, "full_id": full_id, "short_id": full_id.split("/")[-1]})
        
        candidates.sort(key=lambda x: x["score"], reverse=True)
        
        # 実射試験：リストの最上位から生存確認 [cite: 2026-01-16]
        for entry in candidates:
            print(f"  検証: {entry['short_id']} (Score: {entry['score']})", end=" -> ", flush=True)
            try:
                client.models.generate_content(model=entry['full_id'], contents="ping")
                print("疎通成功")
                return entry['full_id'], entry['short_id']
            except:
                print("失敗")
                continue
        return "models/gemini-1.5-pro", "gemini-1.5-pro"
    except Exception as e:
        print(f"致命的探索失敗: {e}")
        return "models/gemini-1.5-pro", "gemini-1.5-pro"

# 1. 最強知能のロック
RAW_FULL_ID, SHORT_ID = find_ultimate_logic_engine()
print(f"\nSZ Logic Engine (Locked): {SHORT_ID}\n")

# DSPy構成（Native SDK ブリッジ） [cite: 2026-01-16]
class SZNativeLM(dspy.LM):
    def __init__(self, model_id, api_key):
        super().__init__(model_id)
        self.client = genai.Client(api_key=api_key)
        self.model_id = model_id
    def __call__(self, prompt=None, messages=None, **kwargs):
        content = prompt if prompt else messages[-1]['content']
        # 憲法編纂のため、常に決定論的（temperature=0.0）に動作 [cite: 2026-01-16]
        res = self.client.models.generate_content(model=self.model_id, contents=content, config={'temperature': 0.0})
        return [res.text]

lm = SZNativeLM(RAW_FULL_ID, os.getenv("GEMINI_API_KEY").strip())
dspy.settings.configure(lm=lm)

class AxiomSynthesizer(dspy.Signature):
    """断片化された仕様を、LaTeX ($) を用いた一つの基本理論（憲法）へ統合せよ。"""
    fragments = dspy.InputField()
    refined_axioms = dspy.OutputField(desc="論理矛盾を排除した数式と物理法則のリスト")

def process_file_recursive(file_path):
    title = os.path.basename(file_path).replace(".txt", "")
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    # チャンク分割：モデルの文脈維持能力を最大化 [cite: 2026-01-16]
    chunk_size = 500
    chunks = ["".join(lines[i:i + chunk_size]) for i in range(0, len(lines), chunk_size)]
    print(f"【編纂中】: {title} ({len(lines)} 行 / {len(chunks)} チャンク)")
    
    fragments = []
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY").strip())
    for idx, c_text in enumerate(chunks):
        print(f"  - 抽出 {idx+1}/{len(chunks)}...", end=" ", flush=True)
        res = client.models.generate_content(
            model=RAW_FULL_ID, 
            contents=f"以下のデータからスマブラの物理・仕様を抽出せよ。数式は LaTeX ($) を使用。\n\n{c_text}"
        )
        fragments.append(res.text)
        print("完了")

    print(f"  - 論理統合プロセス開始...")
    synthesizer = dspy.ChainOfThought(AxiomSynthesizer)
    final_res = synthesizer(fragments="\n\n".join(fragments))
    return {"category": title, "axioms": final_res.refined_axioms}

def main():
    files = sorted(glob.glob("src/brain/raw_data/*.txt"))
    final_constitution = []
    for f in files:
        res = process_file_recursive(f)
        final_constitution.append(res)
        # 一項目ごとに保存し、不慮の停止に備える [cite: 2026-01-16]
        with open("pending_basic_theory.json", "w", encoding="utf-8") as out:
            json.dump(final_constitution, out, ensure_ascii=False, indent=2)
    print("\n--- DONE: SZ絶対憲法の物理的編纂が完了しました ---")

if __name__ == "__main__":
    main()
