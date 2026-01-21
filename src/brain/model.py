"""
SmashBros Coaching Logic using DSPy Chain-of-Thought

This module implements the core AI coaching logic for SmashZettel-Bot.
Architecture: Type B (Analysis → Advice)

DSPy Pipeline:
- Student: This module acts as the primary reasoning engine.
- Input: User question + Retrieved context from Pinecone.
- Output: Two separate fields: Analysis (situation diagnosis) and Advice (specific action).
- Redefinability: All prompts are defined as dspy.Signature classes,
  making them updatable during optimization/distillation.
"""

import os
import dspy
from google import genai
from typing import Optional
from .retriever import PineconeRetriever


class AnalysisSignature(dspy.Signature):
    """
    === DSPy Analysis Phase (Phase 1/2) ===
    
    RESPONSIBILITY: Situation Diagnosis via Chain-of-Thought
    - Input reasoning step: Contextual understanding of the game situation.
    - Output requirement: Identify key frame situations, player psychology, risk/reward factors.
    
    REDEFINABILITY:
    - All field descriptions are prompt instructions (not hardcoded strings).
    - Can be dynamically replaced with optimized prompts via dspy.Teleprompter.
    - Each input/output field is independently tunable.
    
    PIPELINE POSITION:
    - Upstream: Receives context from PineconeRetriever (knowledge base).
    - Downstream: Passes analysis to AdviceSignature in Phase 2.
    - Independent evaluation: Can be tested/optimized separately.
    
    INPUT FIELDS:
    - context: Semantic search results (3-5 relevant mechanics descriptions).
    - question: User's coaching question (natural language, Japanese).
    
    OUTPUT FIELD:
    - analysis: Diagnostic output (3-5 sentences of structured reasoning).
      * Frame situation identification.
      * Player psychology/decision factors.
      * Risk-reward tradeoff analysis.
    """

    context = dspy.InputField(
        desc="スマブラの理論データベースから検索された背景情報（日本語）"
    )
    question = dspy.InputField(desc="ユーザーからのコーチング質問（日本語）")
    analysis = dspy.OutputField(
        desc=(
            "フレーム状況、心理状態、リスク・リワードを分析した結果。"
            "3～5文で論理的かつ簡潔に記述。日本語。"
        )
    )


class AdviceSignature(dspy.Signature):
    """
    === DSPy Advice Phase (Phase 2/2) ===
    
    RESPONSIBILITY: Action Generation via Chain-of-Thought
    - Depends on prior reasoning (analysis from Phase 1).
    - Outputs concrete, frame-perfect action recommendations.
    
    PIPELINE POSITION (Type B Coaching Pattern):
    - Upstream: Receives analysis from AnalysisSignature.
    - Also receives: Original context + original question (for triangulation).
    - Downstream: Final output to Discord user.
    - Optimization metric: User adoption rate (tracked via /teach corrections).
    
    REDEFINABILITY:
    - Each field is independently redefinable for prompt engineering.
    - Supports multi-step CoT (Chain-of-Thought reasoning trace).
    - Compatible with dspy.BootstrapFewShot for learning from training_data.jsonl.
    
    INPUT FIELDS:
    - context: Same knowledge base as Phase 1 (ensures consistency).
    - question: Original user query (required for grounding).
    - analysis: Phase 1 output (directly builds upon this reasoning).
    
    OUTPUT FIELD:
    - advice: Numbered action items with:
      * Specific technique names (日本語スマブラ用語).
      * Frame windows (発生F、全体F etc).
      * Situational conditions (e.g., when to apply).
      * Risk-reward justification.
    """

    context = dspy.InputField(desc="参照データベース（日本語）")
    question = dspy.InputField(desc="ユーザーの質問（日本語）")
    analysis = dspy.InputField(desc="前段階で実施した状況分析（日本語）")
    advice = dspy.OutputField(
        desc=(
            "具体的で実行可能なアドバイス。番号付きリストで箇条書き。"
            "技名、フレーム数、操作方法を含む。日本語。"
        )
    )


class SmashCoach(dspy.Module):
    """
    === DSPy Orchestrator: Type B Coaching Architecture ===
    
    STUDENT COMPONENT: Coordinates two-phase reasoning pipeline.
    - Acts as the primary reasoning "brain" (dspy.Module).
    - Composes two separate dspy.ChainOfThought modules (Analysis + Advice).
    
    ARCHITECTURE (Type B = Analysis → Advice):
    1. RETRIEVAL: PineconeRetriever.forward(query)
       └─ Returns: List[Dict] with 'long_text', 'title', 'score' keys.
    
    2. ANALYSIS PHASE: dspy.ChainOfThought(AnalysisSignature)
       Input: context (retrieved) + question (user)
       Output: analysis (diagnostic reasoning)
       Purpose: Explain frame situation, psychology, risk-reward.
       Redefinable: Can be swapped with different signature.
    
    3. ADVICE PHASE: dspy.ChainOfThought(AdviceSignature)
       Input: context (retrieved) + question (user) + analysis (Phase 1 output)
       Output: advice (concrete actions)
       Purpose: Provide frame-perfect recommendations.
       Redefinable: Can be optimized with dspy.Teleprompter.
    
    OPTIMIZATION TARGETS:
    - Can be optimized via dspy.Teleprompter (auto-prompt tuning).
    - Can be distilled via dspy.BootstrapFewShot using training_data.jsonl.
    - Each phase independently evaluable (enables multi-metric optimization).
    
    REDEFINABILITY GUARANTEES:
    - All prompts are dspy.Signature instances (not f-strings).
    - Retriever, analyzer, advisor all swappable at runtime.
    - Parameters (top_k, threshold) exposed and tunable.
    """

    def __init__(self, retriever: Optional[PineconeRetriever] = None):
        """
        Initialize the coaching module.

        Parameters:
        -----------
        retriever : Optional[PineconeRetriever]
            Custom Pinecone retriever. If None, uses default configuration.
        """
        super().__init__()

        self.retriever = retriever or PineconeRetriever()
        self.analyze = dspy.ChainOfThought(AnalysisSignature)
        self.advise = dspy.ChainOfThought(AdviceSignature)

    def forward(self, question: str) -> dspy.Module:
        """
        === Type B Coaching Pipeline Execution ===
        
        EXECUTION FLOW:
        1. Semantic Search (Retrieval)
           - Query embedded with embedding-001
           - Top-5 passages retrieved from Pinecone
           - Concatenated into context string
        
        2. Analysis (ChainOfThought reasoning)
           - Input: context + question
           - Model: Uses LLM (Google Gemini) to generate diagnostic reasoning
           - Output: analysis field (3-5 sentences)
           - Optimization: Can be tuned with dspy.Teleprompter
        
        3. Advice (Dependent ChainOfThought)
           - Input: context + question + analysis (from Phase 2)
           - Model: Uses analysis to generate concrete actions
           - Output: advice field (numbered list with frame data)
           - Learning: Corrections saved to training_data.jsonl
        
        4. Response Aggregation
           - Returns dspy.Prediction with fields:
             * analysis: Diagnostic reasoning
             * advice: Actionable recommendations
             * context: Retrieved knowledge (for transparency)
        
        REDEFINABILITY:
        - Each phase independently replaceable.
        - Retriever: Can substitute different vector stores (Weaviate, Milvus, etc).
        - Analyzer: Can use different Signature/LM combinations.
        - Advisor: Can include few-shot examples from training_data.jsonl.
        
        DSPy OPTIMIZATION PATHS:
        - BootstrapFewShot: Learn from user /teach corrections.
        - Teleprompter: Auto-optimize prompts for coaching quality.
        - Signature-based metric: Define success criteria for each phase.

        Parameters:
        -----------
        question : str
            User's coaching question (natural language, Japanese).

        Returns:
        --------
        dspy.Prediction
            Object with .analysis and .advice fields (both strings).
        """

        # Step 1: Retrieve context
        retrieval_result = self.retriever.forward(question, k=5)
        context_passages = retrieval_result.context

        # Prepare context text
        context_text = ""
        if context_passages:
            context_text = "\n\n".join(
                [
                    f"【{p.get('title', 'Unknown')}】\n{p.get('long_text', '')}"
                    for p in context_passages
                ]
            )
        else:
            context_text = "（関連データベース情報なし）"

        # Step 2: Generate Analysis
        analysis_result = self.analyze(context=context_text, question=question)

        # Step 3: Generate Advice (using analysis from Step 2)
        advice_result = self.advise(
            context=context_text,
            question=question,
            analysis=analysis_result.analysis,
        )

        # Return combined result
        return dspy.Prediction(
            analysis=analysis_result.analysis,
            advice=advice_result.advice,
            context=context_text,
        )


def create_coach(
    gemini_api_key: Optional[str] = None,
    pinecone_index: str = "smash-zettel",
) -> SmashCoach:
    """
    Factory function to instantiate SmashCoach with configured LM.

    DSPy Justification:
    - Encapsulates LM setup (Google Gemini).
    - Provides clean initialization interface.

    Parameters:
    -----------
    gemini_api_key : Optional[str]
        Gemini API key. If None, uses GEMINI_API_KEY env var.
    pinecone_index : str
        Pinecone index name.

    Returns:
    --------
    SmashCoach
        Initialized coaching module.
    """
    # Set up Gemini LM
    api_key = gemini_api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not provided or set in environment.")

    # Use google-genai SDK to select best available model dynamically
    client = genai.Client(api_key=api_key)
    try:
        all_models = list(client.models.list())
        candidates = [
            m.name.replace("models/", "")
            for m in all_models
            if "gemini" in m.name and "vision" not in m.name and "embedding" not in m.name
        ]

        # Select best model (prefer pro/thinking over flash)
        best_model = "gemini-1.5-pro"  # Safe default
        for name in candidates:
            if "pro" in name or "thinking" in name:
                best_model = name
                break

        lm = dspy.Google(model=f"models/{best_model}", api_key=api_key)
    except Exception as e:
        print(f"[Warning] Dynamic model selection failed: {e}. Using default.")
        lm = dspy.Google(model="models/gemini-1.5-pro", api_key=api_key)

    dspy.settings.configure(lm=lm)

    # Create retriever and coach
    retriever = PineconeRetriever(index_name=pinecone_index)
    return SmashCoach(retriever=retriever)
