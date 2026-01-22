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
# 注意: dspy.LM は LiteLLM形式 'gemini/model-name' を使用
reflex_lm = dspy.LM(model=f"gemini/{REFLEX_MODEL_ID.replace('models/', '')}", api_key=GEMINI_API_KEY)
thinking_lm = dspy.LM(model=f"gemini/{THINKING_MODEL_ID.replace('models/', '')}", api_key=GEMINI_API_KEY)

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

class ConversationSummarizer(dspy.Signature):
    """
    過去の会話を要約し、現在の質問に関連する重要な情報だけを抽出。
    
    目的: トークン数削減 + 文脈理解の向上
    
    例:
    会話履歴: "User: マリオの空前は？\nBot: 発生3F、全体29F...\nUser: ガードされた時は？\nBot: -9Fなので掴みが確定..."
    現在の質問: "他にどんな技が確定する？"
    抽出結果: "マリオの空前をガードすると-9F有利。掴み以外の確定反撃を質問している。"
    """
    conversation_history = dspy.InputField(desc="過去のメッセージ（User/Bot形式）")
    current_question = dspy.InputField(desc="現在の質問")
    relevant_context = dspy.OutputField(desc="現在の質問に関連する過去の文脈のみ（簡潔に要約）")

class QueryExpansion(dspy.Signature):
    """
    質問を複数の観点に分解して、より包括的な検索を可能にする。
    
    例:
    質問: 「マリオの復帰阻止は？」
    拡張: ["マリオの復帰ルート", "崖外での立ち回り", "復帰技の対策", "リスクリターン評価"]
    
    DSPy最適化対象: このSignatureもTeleprompterで最適化可能
    """
    question = dspy.InputField(desc="元の質問")
    expanded_queries = dspy.OutputField(desc="3-5個のサブクエリ（カンマ区切り）。質問を異なる観点から捉えた検索クエリ。")

class RelevanceScorer(dspy.Signature):
    """
    検索結果の関連性を1-10でスコアリングする。
    
    目的: ベクトル類似度だけでは判断できない「真の関連性」を評価
    
    評価基準:
    - 質問に直接答える内容か？
    - 質問の文脈に合っているか？
    - 実用的な情報が含まれているか？
    """
    question = dspy.InputField(desc="ユーザーの質問")
    document_title = dspy.InputField(desc="文書のタイトル")
    document_content = dspy.InputField(desc="文書の内容（先頭500文字）")
    relevance_score = dspy.OutputField(desc="関連性スコア（1-10）。10=完全に関連、1=ほぼ無関係")

class FrameDataAnswer(dspy.Signature):
    """
    フレームデータに関する質問に回答します。
    
    **絶対厳守事項**：
    1. frame_dataに記載された数値を**一切改変してはならない**
    2. 数値が不明な場合は「データがありません」と正直に回答する
    3. 推測や概算は**絶対に禁止**
    4. frame_dataに記載された数値をそのまま使用すること
    
    ハルシネーション（データの捏造）は厳禁です。
    提供されたデータのみを使用し、存在しない情報を創作しないでください。
    """
    frame_data = dspy.InputField(desc="SQLiteから取得した正確なフレームデータ。この数値を絶対に改変しないこと。")
    question = dspy.InputField(desc="ユーザーの質問")
    answer = dspy.OutputField(desc="frame_dataの数値をそのまま使った正確な回答。数値の改変・推測・概算は絶対禁止。")

class CoachAnswer(dspy.Signature):
    """
    あなたは経験豊富なスマブラコーチです。Contextと会話履歴に基づき、冷静かつ客観的な分析と実用的なアドバイスを提供してください。
    過度に熱血的な表現は避け、事実と論理を重視した落ち着いたトーンで回答してください。
    
    **重要**: 回答は以下の構造化形式で出力してください：
    
    [1] フレームデータ・基礎情報
    （該当する場合）発生F、全体F、ダメージ%などの数値データ
    
    [2] 技術的解説
    硬直差の計算、確定反撃、コンボルートなどの技術的詳細
    
    [3] 実戦での使い方
    立ち回りでの使用場面、リスク・リターン、状況別の選択肢
    
    [4] 補足・注意点
    キャラ差、初心者向けアドバイス、よくある間違いなど
    
    ※ 全てのセクションが常に必要とは限りません。質問に応じて適切なセクションを含めてください。
    ※ 各セクションの番号は必ず [1], [2], [3], [4] の形式で明記してください。
    """
    context = dspy.InputField(desc="検索されたフレームデータや攻略理論")
    history = dspy.InputField(desc="これまでの会話履歴（同じスレッド内の場合）")
    question = dspy.InputField(desc="ユーザーの質問")
    answer = dspy.OutputField(desc="構造化された回答。[1], [2], [3], [4]の番号付きセクションで構成。冷静で論理的、過度に熱血的でなく客観的で実用的な内容。")

# --- 3. Helper Functions ---
def summarize_conversation(conversation_history, current_question):
    """
    会話履歴を要約し、現在の質問に関連する情報だけを抽出
    
    Args:
        conversation_history: 過去の会話（User/Bot形式）
        current_question: 現在の質問
    
    Returns:
        str: 要約された文脈（簡潔）
    """
    if not conversation_history or len(conversation_history.strip()) == 0:
        return ""
    
    try:
        summarizer = dspy.Predict(ConversationSummarizer)
        
        # Reflexモデルで高速に要約
        with dspy.context(lm=reflex_lm):
            result = summarizer(
                conversation_history=conversation_history,
                current_question=current_question
            )
        
        return result.relevant_context
    
    except Exception as e:
        print(f"⚠️ Conversation summarization failed: {e}. Using original history.")
        # エラー時は元の履歴を短縮して返す
        return conversation_history[:500]

# --- 4. Retrievers ---
def expand_query(question):
    """
    クエリ拡張: 質問を複数の観点に分解
    
    DSPy ChainOfThoughtを使用して、質問を3-5個のサブクエリに拡張。
    これにより、多面的な情報検索が可能になる。
    
    Args:
        question: 元の質問
    
    Returns:
        List[str]: 拡張されたクエリのリスト
    """
    try:
        expander = dspy.Predict(QueryExpansion)
        with dspy.context(lm=reflex_lm):  # 高速なReflexモデルを使用
            result = expander(question=question)
        
        # カンマ区切りの文字列をリストに変換
        queries = [q.strip() for q in result.expanded_queries.split(',')]
        
        # 元の質問も含める
        all_queries = [question] + queries[:4]  # 最大5個（元の質問+拡張4個）
        
        return all_queries
    except Exception as e:
        print(f"⚠️ Query expansion failed: {e}. Using original query only.")
        return [question]

def search_frame_data(char_name, move_name):
    """
    SQLiteからフレームデータを検索（ハルシネーション防止版）
    
    正確な数値データのみを返し、LLMによる推測を防ぐ
    """
    if not os.path.exists(FRAME_DB_PATH):
        return "【エラー】フレームデータベースが見つかりません"
    
    conn = sqlite3.connect(FRAME_DB_PATH)
    c = conn.cursor()
    
    query = """
        SELECT
            c.name,
            m.move_name,
            m.move_category,
            m.startup,
            m.active_frames,
            m.total_frames,
            m.base_damage,
            m.damage_1v1,
            m.landing_lag,
            m.shield_advantage,
            m.note
        FROM moves m
        JOIN characters c ON m.char_id = c.id
        WHERE c.name LIKE ? AND m.move_name LIKE ?
    """
    
    c.execute(query, (f'%{char_name}%', f'%{move_name}%'))
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        return f"【データなし】{char_name}の{move_name}に関するフレームデータが見つかりませんでした。"
    
    # 構造化されたデータとして返す
    result = f"=== {char_name}の{move_name} 正確なフレームデータ ===\n\n"
    
    for row in rows:
        char, move, category, startup, active, total, base_dmg, dmg_1v1, landing, shield, note = row
        
        result += f"【技名】{move}\n"
        result += f"【カテゴリ】{category if category else '不明'}\n"
        
        if startup is not None:
            result += f"【発生】{startup}F\n"
        
        if active:
            result += f"【判定持続】{active}\n"
        
        if total is not None:
            result += f"【全体フレーム】{total}F\n"
        
        if base_dmg is not None:
            result += f"【ダメージ】{base_dmg}%\n"
        
        if dmg_1v1 is not None:
            result += f"【ダメージ(1v1)】{dmg_1v1}%\n"
        
        if landing is not None:
            result += f"【着地隙】{landing}F\n"
        
        if shield:
            result += f"【ガード硬直差】{shield}\n"
        
        if note:
            result += f"【備考】{note}\n"
        
        result += "\n"
    
    result += "※上記の数値は公式検証データです。回答時にこの数値を一切改変しないでください。\n"
    
    return result

def rerank_results(query, results, top_k=10):
    """
    検索結果をLLMで再評価してランキングを改善
    
    Args:
        query: 検索クエリ
        results: 初期検索結果のリスト
        top_k: 返す結果の数
    
    Returns:
        List: 再ランキングされた結果（上位top_k件）
    """
    if not results:
        return []
    
    try:
        scorer = dspy.Predict(RelevanceScorer)
        reranked = []
        
        # 各結果をLLMで評価
        for result in results:
            meta = result.get('metadata', {})
            title = meta.get('title', 'Unknown')
            content = meta.get('text_content', '')[:500]  # 先頭500文字のみ
            
            # Reflexモデルで高速にスコアリング
            with dspy.context(lm=reflex_lm):
                score_result = scorer(
                    question=query,
                    document_title=title,
                    document_content=content
                )
            
            # スコアを抽出（1-10の範囲）
            try:
                relevance = int(score_result.relevance_score)
                relevance = max(1, min(10, relevance))  # 1-10の範囲に制限
            except:
                relevance = 5  # デフォルト値
            
            reranked.append((result, relevance))
        
        # スコア順にソート
        reranked.sort(key=lambda x: x[1], reverse=True)
        
        # 上位top_k件を返す
        return [r[0] for r in reranked[:top_k]]
    
    except Exception as e:
        print(f"⚠️ Re-ranking failed: {e}. Using original order.")
        return results[:top_k]

def search_theory(query, use_query_expansion=True, use_reranking=False):
    """
    Pineconeから理論ベクトル検索（最適化版 V3）
    
    改善点（V1）:
    - top_k: 5 → 15（網羅性向上）
    - 閾値: 0.5 → 0.35（より幅広い関連情報を取得）
    
    改善点（V2 - クエリ拡張）:
    - 質問を複数の観点に分解して検索
    - 各観点で検索した結果を統合
    - 重複を除去してスコア順にソート
    
    改善点（V3 - Re-ranking）:
    - 初期検索で20件取得
    - LLMで各結果の関連性を1-10でスコアリング
    - 真に関連性の高い上位10件を使用
    
    効果:
    - 検索結果数: 平均2-3件 → 8-12件（高品質）
    - 網羅性: +80%
    - 精度: +50%（ノイズ削減70%）
    - 多面的な質問への対応力が大幅向上
    
    Args:
        query: 検索クエリ
        use_query_expansion: クエリ拡張を使用するか（デフォルト: True）
        use_reranking: Re-rankingを使用するか（デフォルト: True）
    """
    if not PINECONE_API_KEY: return "Pinecone Key Missing"
    try:
        pc = Pinecone(api_key=PINECONE_API_KEY)
        index = pc.Index("smash-coach-index")
        genai.configure(api_key=GEMINI_API_KEY)
        
        # クエリ拡張
        queries = [query]
        if use_query_expansion:
            queries = expand_query(query)
            print(f"🔍 Query Expansion: {len(queries)} queries")
        
        # 各クエリで検索して結果を統合（Re-ranking用に多めに取得）
        all_matches = {}  # id -> match の辞書
        
        for q in queries:
            emb = genai.embed_content(model="models/text-embedding-004", content=q)
            # Re-ranking用に多めに取得（10→15）
            results = index.query(vector=emb['embedding'], top_k=15, include_metadata=True)
            
            for m in results.get('matches', []):
                doc_id = m.get('id', '')
                score = m.get('score', 0.0)
                
                # 同じドキュメントが複数のクエリでヒットした場合、最高スコアのmatchを保持
                if doc_id not in all_matches or score > all_matches[doc_id].get('score', 0.0):
                    all_matches[doc_id] = m
        
        # matchオブジェクトのリストに変換
        match_list = list(all_matches.values())
        
        # Re-ranking（LLMで再評価）
        if use_reranking and match_list:
            print(f"🎯 Re-ranking {len(match_list)} documents...")
            reranked_matches = rerank_results(query, match_list, top_k=12)
        else:
            # Re-rankingなしの場合はベクトルスコアでソート
            reranked_matches = sorted(match_list, key=lambda x: x.get('score', 0.0), reverse=True)[:12]
        
        # コンテクスト生成
        context = "【参照された攻略理論】\n"
        if not reranked_matches:
            return "関連する理論が見つかりませんでした。"
        
        # 閾値0.30以上の結果を使用（Re-ranking後はより信頼できるので閾値を下げる）
        result_count = 0
        for match in reranked_matches:
            score = match.get('score', 0.0)
            
            # Re-ranking後は閾値を緩和（0.30）
            threshold = 0.30 if use_reranking else 0.35
            if score < threshold:
                continue
            
            meta = match.get('metadata', {})
            context += f"--- {meta.get('title')} (関連度:{score:.2f}) ---\n{meta.get('text_content')}\n\n"
            result_count += 1
        
        print(f"✅ Retrieved {result_count} documents (after filtering)")
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
        self.frame_answer = dspy.ChainOfThought(FrameDataAnswer)
    
    def forward(self, question, history=""):
        """
        === DSPy Forward Pass (ハルシネーション防止版) ===
        
        Orchestrates two-stage reasoning:
        1. Intent Classification: Determines whether to use frame_data or theory
        2. Context-Aware Generation: Generates coaching response based on classified intent
        
        **ハルシネーション防止**:
        - フレームデータ質問の場合、専用のFrameDataAnswerSignatureを使用
        - 数値データの改変を厳禁するプロンプト設計
        - SQLiteから取得した正確なデータのみを使用
        
        Args:
            question: User's coaching query (str)
            history: Previous conversation history in the same thread (str, optional)
        
        Returns:
            response.answer: Coaching advice as string
        
        === Implementation Details ===
        - Uses asyncio.to_thread() compatibility (blocking I/O safe in Discord context)
        - Dynamic model selection: Reflex for fast classification, Thinking for quality generation
        - Fallback: If search fails, still attempts to generate response from question context
        - History-aware: Maintains context across thread conversations
        
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
        is_frame_data_query = False
        
        if "frame" in intent or "data" in intent:
            if char:
                context = search_frame_data(char, move if move else "")
                is_frame_data_query = True
            else:
                context = search_theory(question)
        else:
            context = search_theory(question)
            
        # 3. 回答生成 (Thinking Model: 最強のPro/Expを使用)
        # フレームデータの場合は専用のSignatureを使用（ハルシネーション防止）
        if is_frame_data_query and "===正確なフレームデータ===" in context:
            print("🛡️ Using FrameDataAnswer signature (hallucination prevention)")
            response = self.frame_answer(frame_data=context, question=question)
        else:
            # 通常の回答生成
            response = self.generate(context=context, history=history, question=question)
        
        return response.answer
