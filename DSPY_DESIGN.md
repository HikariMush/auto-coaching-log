# SmashZettel-Bot: DSPy Architecture & Design Document

## 📋 Overview

This document specifies how SmashZettel-Bot leverages DSPy for **self-improving AI coaching**.

**Key Principle:** All code is redefinable and composable at runtime. Prompts are not strings; they are `dspy.Signature` instances.

---

## 🏗️ Architecture: Type B Coaching (Analysis → Advice)

```
User Question
    ↓
[asyncio.to_thread] ← Critical: Prevent event loop blocking
    ↓
SmashCoach.forward() ← dspy.Module (Student component)
    ├─ PineconeRetriever.forward() ← dspy.Retrieve subclass
    │  └─ Input: query string
    │  └─ Output: dspy.Context with retrieved passages
    │
    ├─ Phase 1: AnalysisSignature (dspy.ChainOfThought)
    │  ├─ Input: context + question
    │  ├─ Prompt: Dynamically constructed (not hardcoded)
    │  └─ Output: analysis field (situation diagnosis)
    │
    ├─ Phase 2: AdviceSignature (dspy.ChainOfThought)
    │  ├─ Input: context + question + analysis
    │  ├─ Prompt: Depends on Phase 1 output (CoT reasoning)
    │  └─ Output: advice field (actionable recommendations)
    │
    └─ Return: dspy.Prediction(analysis=..., advice=..., context=...)
        ↓
    [Format for Discord]
        ↓
    Send to user
        ↓
    [User provides /teach correction]
        ↓
    Save to data/training_data.jsonl
        ↓
    [Available for dspy.BootstrapFewShot optimization]
```

---

## 🔄 Component Breakdown

### 1. **PineconeRetriever** (src/brain/retriever.py)

**Role:** dspy.Retrieve subclass  
**DSPy Justification:**
```python
# This is a STUDENT component in DSPy terminology
# - Inherits from dspy.Retrieve (base class)
# - forward() returns dspy.Context (compatible with Signatures)
# - Parameters are instance attributes (redefinable)

class PineconeRetriever(dspy.Retrieve):
    """
    === DSPy Pipeline Role ===
    STUDENT: Knowledge retrieval engine
    REDEFINABLE: All parameters (index_name, top_k, threshold)
    OPTIMIZATION: Compatible with dspy.Optimizer
    """
```

**Methods:**
- `__init__()` - Initialize Pinecone client, validate API keys
- `_embed_query(query)` - Convert text to 768-dim vector (embedding-001)
- `forward(query, k)` - Semantic search, return `dspy.Context`

**Redefinability:**
- `top_k`: Change retrieval count (e.g., 3 vs 5 vs 10)
- `similarity_threshold`: Adjust relevance filtering
- `index_name`: Switch between multiple Pinecone indexes
- Embedding model: Can be switched to different providers

---

### 2. **SmashCoach** (src/brain/model.py)

**Role:** dspy.Module orchestrator  
**DSPy Justification:**
```python
# This is the main REASONING ENGINE
# - Composed of two dspy.ChainOfThought modules
# - All prompts are dspy.Signature instances (redefinable)
# - forward() implements the reasoning algorithm

class SmashCoach(dspy.Module):
    def forward(self, question: str) -> dspy.Prediction:
        # Phase 1: Analysis (ChainOfThought)
        analysis = self.analyze(context=context_text, question=question)
        
        # Phase 2: Advice (ChainOfThought, depends on Phase 1)
        advice = self.advise(
            context=context_text, 
            question=question,
            analysis=analysis.analysis  # Dependency
        )
        
        return dspy.Prediction(analysis=..., advice=..., context=...)
```

**Signature Classes:**

#### AnalysisSignature
```python
class AnalysisSignature(dspy.Signature):
    """Phase 1: Diagnostic Reasoning"""
    context = dspy.InputField(desc="...")  # From Retriever
    question = dspy.InputField(desc="...")  # User query
    analysis = dspy.OutputField(desc="...")  # Diagnostic output
```

**Redefinability:** Each field is independently tunable via dspy.Teleprompter.

#### AdviceSignature
```python
class AdviceSignature(dspy.Signature):
    """Phase 2: Action Generation (depends on Phase 1)"""
    context = dspy.InputField(desc="...")
    question = dspy.InputField(desc="...")
    analysis = dspy.InputField(desc="...")  # From Phase 1
    advice = dspy.OutputField(desc="...")
```

**Redefinability:** Can be optimized separately from AnalysisSignature.

---

### 3. **Discord Bot Interface** (src/main.py)

**DSPy Justification:**
```python
# Critical Pattern: Async/Sync Bridge

@bot.tree.command(name="ask")
async def ask_command(interaction: discord.Interaction, query: str):
    """
    === DSPy Inference via Thread Pool ===
    - Discord is async (event loop)
    - DSPy is blocking (LLM I/O)
    - Solution: asyncio.to_thread() runs DSPy in thread
    """
    prediction = await asyncio.to_thread(_run_coaching, query)
    # prediction is dspy.Prediction object
    await interaction.followup.send(format_response(prediction))
```

**Data Persistence:**
```python
@bot.tree.command(name="teach")
async def teach_command(interaction, query: str, correction: str):
    """
    === Learning from User Corrections ===
    - Saves correction to data/training_data.jsonl (JSONL format)
    - Format: {"question": "...", "gold_answer": "...", ...}
    - Future: Used by dspy.BootstrapFewShot for prompt optimization
    """
    await asyncio.to_thread(_append_training_data, entry)
```

---

## 📊 Data Pipeline: Notion → Pinecone

### Design Pattern: **Decoupled Synchronization**

```
Notion Theory DB
    ↓
[Scheduled: Every 1 hour or on-demand]
    ↓
src/utils/notion_sync.py
    ├─ Fetch all Theory pages
    ├─ Extract content (blocks)
    ├─ Embed with embedding-001
    └─ Upsert to Pinecone
        ↓
    Pinecone Index (smash-zettel)
        ↓
    PineconeRetriever (DSPy)
        ↓
    SmashCoach (Analysis/Advice)
        ↓
    Discord response
```

**Redefinability:**
- Sync frequency: Can be tuned (hourly, on-demand, etc)
- Batch size: Can be changed for rate limit handling
- Filtering: Can exclude/prioritize certain page types
- Enrichment: Can add domain-specific metadata

---

## 🧠 Raw Data Quality Management

### **src/utils/analyze_raw_data.py**

Analyzes `src/brain/raw_data/*.txt` for coverage and completeness.

**Metrics:**
- File size
- Presence of formulas ($...$)
- Presence of structured lists
- Presence of tables
- Overall completeness estimate (0.0-1.0)

**Output:**
```json
{
  "total_files": 42,
  "categories": {
    "攻撃系": ["攻撃判定.txt", ...],
    "防御系": ["シールド.txt", ...]
  },
  "identified_gaps": [
    "ふっとび.txt (completeness: 25.0%, size: 5.2KB)",
    ...
  ]
}
```

**Redefinability:**
- Completeness heuristics can be refined
- Category taxonomies can be customized
- Gap thresholds can be adjusted

---

## 🎯 Future Optimization Paths

### 1. **Prompt Optimization** (dspy.Teleprompter)
```python
# Auto-tune Analysis and Advice prompts
optimizer = dspy.Teleprompter(...)
optimized_coach = optimizer.compile(
    student=coach,
    trainset=gold_standards_from_training_data,
    metric=coaching_quality_metric
)
```

### 2. **Few-Shot Learning** (dspy.BootstrapFewShot)
```python
# Learn from user corrections in data/training_data.jsonl
bootstrap = dspy.BootstrapFewShot(metric=...)
coach = bootstrap.compile(
    student=SmashCoach(...),
    trainset=[...]  # From /teach corrections
)
```

### 3. **Multi-Model Composition**
```python
# Different models for different query types
fast_coach = SmashCoach(lm=dspy.Google("gemini-2.0-flash"))
deep_coach = SmashCoach(lm=dspy.Google("gemini-1.5-pro"))

# Routing logic: Choose based on query complexity
```

### 4. **Custom Metrics**
```python
# Evaluate coaching quality
def coaching_quality_metric(gold, pred, trace=None):
    # Score prediction against user corrections
    # Integrate with dspy.Evaluate for benchmarking
    pass
```

---

## 📝 DSPy Compliance Checklist

### Code Standards
- ✅ All prompts defined as `dspy.Signature` classes (not f-strings)
- ✅ All logic in `dspy.Module` subclasses (recomposable)
- ✅ All parameters instance attributes (runtime tunable)
- ✅ All classes have DSPy Justification docstrings
- ✅ Clear STUDENT/TEACHER/METRIC roles documented

### Data Flow
- ✅ dspy.Retrieve → dspy.Context → dspy.Signature
- ✅ dspy.ChainOfThought for multi-step reasoning
- ✅ dspy.Prediction for output aggregation

### Optimization Readiness
- ✅ Training data collected (data/training_data.jsonl)
- ✅ Metrics definable (quality evaluation)
- ✅ Teleprompter compatible (prompt optimization)
- ✅ Bootstrap-ready (few-shot learning)

---

## 🔗 Integration Points

### With Existing Legacy Code
- `src/brain/core.py` - Frame data retrieval (independent)
- `src/brain/build_axioms.py` - Knowledge extraction (feeds raw_data)
- `main.py`, `generalize.py` - Notion integration (legacy, being enhanced)

### With New Pipelines
- `notion_sync.py` - Scheduled data import from Notion
- `analyze_raw_data.py` - Quality monitoring
- `ingest.py` - Manual/automated Pinecone population

---

## 🚀 Quick Start: DSPy Development

### 1. Test Retriever
```bash
python -c "
from src.brain.retriever import create_retriever
r = create_retriever()
ctx = r.forward('復帰の最適なタイミングは？')
print(ctx.context[0]['title'])
"
```

### 2. Test Coach
```bash
python -c "
from src.brain.model import create_coach
coach = create_coach()
pred = coach.forward('ネスに勝つにはどうすればいい？')
print(pred.analysis)
print(pred.advice)
"
```

### 3. Analyze Data Quality
```bash
python -m src.utils.analyze_raw_data
```

### 4. Sync Notion Data
```bash
python -m src.utils.notion_sync
```

---

## 📚 References

- [DSPy Documentation](https://github.com/stanfordnlp/dspy)
- [dspy.Retrieve](https://github.com/stanfordnlp/dspy/blob/main/dspy/retrieval/retrieve.py)
- [dspy.Teleprompter](https://github.com/stanfordnlp/dspy/tree/main/dspy/teleprompt)
- [Type B Coaching Pattern](./IMPLEMENTATION_SUMMARY.md#3️⃣-type-b-coaching-logic-src-brain-modelpy)

---

**Last Updated:** 2026-01-21  
**Status:** Architecture Complete, Ready for Optimization
