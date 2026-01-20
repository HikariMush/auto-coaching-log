import os
import json
import dspy
import sys
import io
import glob
import re
import litellm
from google import genai

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

def select_absolute_brain_v22():
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    client = genai.Client(api_key=api_key)
    
    print("--- 物理知能の動的確定フェーズ ---")
    try:
        # APIから現時点でアクティブなモデルを全取得 [cite: 2026-01-16]
        models = list(client.models.list())
        candidates = []
        
        for m in models:
            name = m.name # models/gemini-xxx
            # 推論に関係ないモデルを排除
            if not any(x in name.lower() for x in ["pro", "ultra"]): continue
            if any(x in name.lower() for x in ["vision", "flash", "nano", "imagen"]): continue
            
            score = 0
            if "ultra" in name.lower(): score += 10000
            elif "pro" in name.lower(): score += 5000
            
            # バージョン加点
            v = re.search(r"(\d+\.\d+)", name)
            if v: score += float(v.group(1)) * 1000
            
            candidates.append((score, name))
        
        candidates.sort(key=lambda x: x[0], reverse=True)
        
        # 404を物理的に排除する疎通テスト [cite: 2026-01-16]
        for _, full_name in candidates:
            # gemini/model_id の形式に整形
            model_id = full_name.split("/")[-1]
            target = f"gemini/{model_id}"
            print(f"  Testing: {target}", end=" -> ")
            try:
                litellm.completion(
                    model=target,
                    messages=[{"role": "user", "content": "1"}],
                    api_key=api_key,
                    timeout=10
                )
                print("SUCCESS (Locked)")
                return target
            except:
                print("FAILED")
                continue
                
        return "gemini/gemini-1.5-pro-002"
    except Exception as e:
        print(f"Crit: {e}")
        return "gemini/gemini-1.5-pro-002"

# 1. 脳の確定
BRAIN = select_absolute_brain_v22()
lm = dspy.LM(BRAIN, api_key=os.getenv("GEMINI_API_KEY").strip(), temperature=0.0)
dspy.settings.configure(lm=lm)

class SmashConstitution(dspy.Signature):
    """
    Wiki全文から不変の物理・仕様を『絶対憲法』として定義せよ。
    - 数式は LaTeX ($) を使用。例: $KB = \dots$
    - 42項目の相互依存関係（シールド、硬直、ふっとび）を論理的に整理。
    """
    page_title = dspy.InputField()
    raw_text = dspy.InputField()
    axioms = dspy.OutputField(desc="厳密な数式とルールのリスト")

def sanitize_text(text):
    # Ctrl+Aで混入した不正な文字や過剰な空白を除去 [cite: 2026-01-16]
    text = re.sub(r'[^\x00-\x7Fぁ-んァ-ヶ亜-熙]+', ' ', text)
    return "\n".join([line.strip() for line in text.splitlines() if line.strip()])

def build_brain():
    files = sorted(glob.glob("src/brain/raw_data/*.txt"))
    agent = dspy.ChainOfThought(SmashConstitution)
    final_db = []

    print(f"\n--- SZ絶対憲法編纂：全 {len(files)} 項目 ---")

    for f_path in files:
        title = os.path.basename(f_path).replace(".txt", "")
        with open(f_path, "r", encoding="utf-8") as f:
            # 巨大ファイルもここで正規化してノイズを減らす [cite: 2026-01-16]
            content = sanitize_text(f.read())

        if len(content) > 50:
            print(f"【集中編纂】: {title} ({len(content)} chars)")
            try:
                res = agent(page_title=title, raw_text=content)
                final_db.append({"category": title, "axioms": res.axioms})
                print(f"  - 完了")
            except Exception as e:
                print(f"  - エラー: {str(e)[:50]}")

    with open("pending_basic_theory.json", "w", encoding="utf-8") as f:
        json.dump(final_db, f, ensure_ascii=False, indent=2)
    print("\n--- DONE: SZ絶対憲法が物理的に確定されました ---")

if __name__ == "__main__":
    build_brain()
