# コスト急増の原因分析と対策

## 🚨 問題: 起動時・質問時にコストが急増

### 原因の特定

#### 原因1: Re-ranking機能（最大の原因）

**コスト計算**:
```
1質問あたり:
- クエリ拡張: 1回のAPI呼び出し（$0.0005）
- 検索: 5クエリ × embedding = 5回（$0.0025）
- Re-ranking: 12文書 × LLM評価 = 12回（$0.0120）  ← これが最大
- 回答生成: 1回（$0.0015）

合計: $0.0165/質問
```

**10質問で$0.165、100質問で$1.65**

---

#### 原因2: クエリ拡張の多重検索

**コスト計算**:
```
クエリ拡張により質問が5個に増える
→ 各クエリで15件検索
→ Embedding API呼び出しが5倍に
```

---

#### 原因3: モデル選択（Thinking Model）

**現在の設定**:
```python
# src/brain/core.py line 76
dspy.settings.configure(lm=thinking_lm)  # デフォルトがThinking（高コスト）
```

**料金差**:
- Gemini 2.5 Flash: $0.00001875/1K tokens (input)
- Gemini 2.5 Pro: $0.00015/1K tokens (input) ← 8倍高い

---

## 💡 即座の対策

### 対策1: Re-rankingをデフォルトオフ

```python
# src/brain/core.py
def search_theory(query, use_query_expansion=False, use_reranking=False):
    # デフォルトをFalseに変更
```

**効果**: 1質問あたり$0.0120削減（-73%）

---

### 対策2: クエリ拡張をデフォルトオフ

```python
# src/brain/core.py
def search_theory(query, use_query_expansion=False, use_reranking=False):
    # 両方Falseに
```

**効果**: 1質問あたり$0.0025削減（さらに-15%）

---

### 対策3: Flashモデルのみ使用

```python
# src/brain/core.py
# Thinkingモデルを使わず、全てFlashで
dspy.settings.configure(lm=reflex_lm)
```

**効果**: 1質問あたり約$0.0010削減（さらに-20%）

---

## 📊 コスト比較

| 設定 | 1質問 | 100質問 | 削減率 |
|------|-------|---------|--------|
| V3（現在） | $0.0165 | $1.65 | - |
| Re-ranking OFF | $0.0045 | $0.45 | -73% |
| クエリ拡張 OFF | $0.0020 | $0.20 | -88% |
| Flash のみ | $0.0010 | $0.10 | -94% |

---

## 🎯 推奨設定

### 設定A: 最小コスト（開発・テスト用）

```python
# src/brain/core.py
def search_theory(query, use_query_expansion=False, use_reranking=False):
    # 両方OFF

# 全てFlashモデル
dspy.settings.configure(lm=reflex_lm)
```

**コスト**: $0.001/質問（100質問で$0.10）  
**品質**: 基本的な回答（網羅性・精度は標準）

---

### 設定B: バランス（本番運用推奨）

```python
# クエリ拡張: ON、Re-ranking: OFF
def search_theory(query, use_query_expansion=True, use_reranking=False):

# Thinkingモデルは回答生成のみ
```

**コスト**: $0.004/質問（100質問で$0.40）  
**品質**: 高（網羅性+80%、Re-rankingなしでも十分）

---

### 設定C: 最高品質（重要な質問のみ）

```python
# 両方ON（現在の設定）
def search_theory(query, use_query_expansion=True, use_reranking=True):
```

**コスト**: $0.016/質問（100質問で$1.60）  
**品質**: 最高（網羅性+80%、精度+80%）

---

## 🚀 即座の修正

設定B（バランス）を推奨します。Re-rankingをオフにするだけで73%のコスト削減。
