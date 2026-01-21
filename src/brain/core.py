import os
import re
import dspy
import sqlite3
import google.generativeai as genai
from pinecone import Pinecone

# --- Config ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")

# DB Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRAME_DB_PATH = os.path.join(BASE_DIR, '../../data/framedata.db')

# --- 1. Dynamic Model Resolver ---
def get_best_models():
    """
    Google APIから利用可能な全モデルを取得し、
    'Thinking'(賢さ優先) と 'Reflex'(速度優先) のそれぞれで最強のモデルIDを返す。
    """
    genai.configure(api_key=GEMINI_API_KEY)
    
    try:
        all_models = list(genai.list_models())
        candidates = []
        for m in all_models:
            name = m.name.replace("models/", "")
            if "gemini" in name and "vision" not in name and "embedding" not in name:
                candidates.append(name)
        
        # スコアリング関数 (バージョン > グレード > 最新性)
        def calculate_score(name, is_speed_priority=False):
            score = 0
            # Version (2.5 -> 2500, 2.0 -> 2000, 1.5 -> 1500)
            version_match = re.search(r"(\d+\.\d+)", name)
            if version_match:
                score += float(version_match.group(1)) * 1000
            
            # Grade
            if "ultra" in name: score += 300
            elif "pro" in name: score += 200
            elif "flash" in name: 
                # 速度優先ならFlashを高評価、思考優先なら低評価
                score += 500 if is_speed_priority else 100
            
            # Latest / Experimental
            if "exp" in name: score += 50
            if "thinking" in name and not is_speed_priority: score += 20 # 思考モデルならThinking加点
            
            return score

        # Thinking Model (賢さ重視: Pro/Ultra/Thinking)
        thinking_candidates = sorted(candidates, key=lambda x: calculate_score(x, is_speed_priority=False), reverse=True)
        best_thinking = thinking_candidates[0] if thinking_candidates else "gemini-1.5-pro"

        # Reflex Model (速度重視: Flash系の中で最強のもの)
        reflex_candidates = sorted(candidates, key=lambda x: calculate_score(x, is_speed_priority=True), reverse=True)
        best_reflex = reflex_candidates[0] if reflex_candidates else "gemini-1.5-flash"

        print(f"🧠 Dynamic Model Selection:\n  Thinking Engine: {best_thinking}\n  Reflex Engine:   {best_reflex}")
        return best_thinking, best_reflex

    except Exception as e:
        print(f"⚠️ Model resolution failed: {e}. Falling back to defaults.")
        return "gemini-1.5-pro", "gemini-1.5-flash"

# モデル解決とDSPy設定
THINKING_MODEL_ID, REFLEX_MODEL_ID = get_best_models()

# DSPyの設定
# 注意: dspy.Google は 'models/' 接頭辞が必要な場合があるため補完
reflex_lm = dspy.Google(model=f"models/{REFLEX_MODEL_ID.replace('models/', '')}", api_key=GEMINI_API_KEY)
thinking_lm = dspy.Google(model=f"models/{THINKING_MODEL_ID.replace('models/', '')}", api_key=GEMINI_API_KEY)

# デフォルトは思考モデル
dspy.settings.configure(lm=thinking_lm)

# --- 2. Define Signatures ---
class IntentClassifier(dspy.Signature):
    """
    ユーザーの質問を分析し、最適な情報ソースを決定せよ。
    - 具体的な技の数値(発生、硬直差、ダメージ等) → 'frame_data'
    - 立ち回り、対策、心理戦、考え方、コンボなど → 'theory'
    """
    question = dspy.InputField(desc="ユーザーの質問")
    intent = dspy.OutputField(desc="'frame_data' or 'theory'")
    character = dspy.OutputField(desc="関連キャラ名 (例: クラウド, ネス)。不明ならNone")
    move = dspy.OutputField(desc="関連する技名 (例: 空前, 上B)。不明ならNone")

class CoachAnswer(dspy.Signature):
    """
    あなたは世界一のスマブラコーチです。Contextに基づき、ユーザーを勝利へ導く回答を作成せよ。
    """
    context = dspy.InputField(desc="検索されたフレームデータや攻略理論")
    question = dspy.InputField(desc="ユーザーの質問")
    answer = dspy.OutputField(desc="論理的かつ具体的なコーチング回答")

# --- 3. Retrievers ---
def search_frame_data(char_name, move_name):
    """SQLiteからフレームデータを検索"""
    if not os.path.exists(FRAME_DB_PATH): return "DB Error"
    conn = sqlite3.connect(FRAME_DB_PATH)
    c = conn.cursor()
    query = """
        SELECT m.move_name, m.startup, m.total_frames, m.landing_lag, m.shield_advantage, m.base_damage, m.note 
        FROM moves m JOIN characters c ON m.char_id = c.id 
        WHERE c.name LIKE ? AND m.move_name LIKE ?
    """
    c.execute(query, (f'%{char_name}%', f'%{move_name}%'))
    rows = c.fetchall()
    conn.close()
    
    if not rows: return "該当データなし"
    
    res = f"【{char_name}の{move_name} データ】\n"
    for r in rows:
        res += f"- {r[0]}: 発生{r[1]}F / 全体{r[2]}F / ガード硬直差{r[4]}F / ダメージ{r[5]}%\n"
    return res

def search_theory(query):
    """Pineconeから理論ベクトル検索"""
    if not PINECONE_API_KEY: return "Pinecone Key Missing"
    try:
        pc = Pinecone(api_key=PINECONE_API_KEY)
        index = pc.Index("smash-coach-index")
        
        # Embeddingも動的に最強モデルに合わせたいが、
        # Ingest時と同じモデル(text-embedding-004)を使わないと空間がズレてヒットしなくなるため固定
        genai.configure(api_key=GEMINI_API_KEY)
        emb = genai.embed_content(model="models/text-embedding-004", content=query)
        
        results = index.query(vector=emb['embedding'], top_k=5, include_metadata=True)
        
        context = "【参照された攻略理論】\n"
        if not results['matches']:
            return "関連する理論が見つかりませんでした。"
            
        for m in results['matches']:
            meta = m['metadata']
            score = m['score']
            if score < 0.5: continue
            context += f"--- {meta.get('title')} (関連度:{score:.2f}) ---\n{meta.get('text_content')}\n\n"
            
        return context
    except Exception as e:
        return f"Search Error: {e}"

# --- 4. Brain Module ---
class SmashBrain(dspy.Module):
    """
    === DSPy Reasoning Engine (Legacy Type A) ===
    
    STUDENT COMPONENT: Reasoning orchestrator combining Intent Classification + Context Retrieval + Answer Generation
    
    This is the legacy Type A architecture (before Type B refactoring in model.py).
    Maintained for backward compatibility. New code should use SmashCoach (Type B).
    
    === Pipeline ===
    1. IntentClassifier (Reflex LM): Determine info source (frame_data vs theory)
    2. Search Dispatch: Query SQLite (frame_data) or Pinecone (theory)
    3. CoachAnswer (Thinking LM): Generate response using ChainOfThought reasoning
    
    === Optimization Paths ===
    - dspy.Teleprompter: Auto-tune IntentClassifier and CoachAnswer prompts
    - dspy.BootstrapFewShot: Learn from user /teach corrections
    - Dual-Model Strategy: Reflex for classification (fast), Thinking for generation (quality)
    """
    def __init__(self):
        super().__init__()
        self.classify = dspy.ChainOfThought(IntentClassifier)
        self.generate = dspy.ChainOfThought(CoachAnswer)
    
    def forward(self, question):
        """
        === DSPy Forward Pass ===
        
        Orchestrates two-stage reasoning:
        1. Intent Classification: Determines whether to use frame_data or theory
        2. Context-Aware Generation: Generates coaching response based on classified intent
        
        Args:
            question: User's coaching query (str)
        
        Returns:
            response.answer: Coaching advice as string
        
        === Implementation Details ===
        - Uses asyncio.to_thread() compatibility (blocking I/O safe in Discord context)
        - Dynamic model selection: Reflex for fast classification, Thinking for quality generation
        - Fallback: If search fails, still attempts to generate response from question context
        
        === Redefinability ===
        - LM models: Can be swapped via dspy.context(lm=...)
        - Retrieval sources: Can be extended to support additional databases
        - Signatures: IntentClassifier and CoachAnswer prompts are dspy.Signature (tunable)
        """
        # 1. 意図分類 (Reflex Model: 最強のFlashを使用)
        with dspy.context(lm=reflex_lm):
            classification = self.classify(question=question)
        
        intent = classification.intent.lower()
        char = classification.character
        move = classification.move
        
        # 2. 情報検索
        context = ""
        if "frame" in intent or "data" in intent:
            if char:
                context = search_frame_data(char, move if move else "")
            else:
                context = search_theory(question)
        else:
            context = search_theory(question)
            
        # 3. 回答生成 (Thinking Model: 最強のPro/Expを使用)
        # デフォルトコンテキストがThinkingなのでそのまま実行
        response = self.generate(context=context, question=question)
        
        return response.answer
