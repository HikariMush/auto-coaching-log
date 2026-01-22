# フレームデータのハルシネーション問題：根本原因分析

## 🔍 調査結果

### ✅ データの存在確認
- **Excelファイル**: ヒカリの空前データは存在（発生8F）
- **Pinecone**: ヒカリのデータ20件が保存されている（メタデータフィルタで確認）
- **ingestion_state.json**: 80. ヒカリは正常にingested

### ❌ 重大な問題

#### 問題1: データが非構造化
```
data_preview: "横強 | 8-9 | 25 | 5.5 | 6.6 | 6F"
```
- パイプ区切りの生データとして保存
- 技名、発生フレーム、ダメージなどが個別フィールド化されていない
- **空前が「空前」という名前で保存されていない可能性**

#### 問題2: メタデータ不足
現在のメタデータ構造：
```python
metadata = {
    'character': 'ヒカリ',
    'section': '行動フレーム',  # ← 技名が含まれていない！
    'source': 'excel_ingestion',
    'data_preview': '横強 | 8-9 | 25...'  # ← 生データ
}
```

**必要なメタデータ**：
```python
metadata = {
    'character': 'ヒカリ',
    'move_name': '空前',  # ← 技名を明示
    'startup_frame': 8,   # ← 数値として保存
    'total_frame': 37,
    'damage': 7.0,
    'damage_1v1': 8.4,
    'section': '空中攻撃',
    'source': 'excel_ingestion'
}
```

#### 問題3: セマンティック検索の限界
- ベクトル検索は**意味的類似性**を見る
- **正確な数値データ**の検索には不向き
- 「ヒカリの空前の発生フレーム」→「発生8F」という正確な対応が取れない

## 🎯 ハルシネーションの発生メカニズム

1. **ユーザーが質問**: 「ヒカリの空前の発生は？」
2. **検索結果**: パイプ区切りの生データ「横強 | 8-9 | 25 | 5.5...」が返される
3. **LLMの解釈**: 生データを見て推測 → **間違った数値を生成**
4. **ハルシネーション発生**: 正確なデータがないので、LLMが勝手に数値を作る

## 📋 解決策

### Phase 1: 技データの構造化抽出（最優先）

#### 1.1 Excelパース改善
```python
def extract_move_data(sheet, character_name):
    """
    技データを個別に抽出
    
    Returns:
        [
            {
                'character': 'ヒカリ',
                'move_name': '空前',
                'startup': 8,
                'total_frames': 37,
                'damage': 7.0,
                'damage_1v1': 8.4,
                'landing_lag': 10,
                'shield_advantage': 3,
                ...
            },
            ...
        ]
    """
```

#### 1.2 SQLiteデータベース構築
```sql
CREATE TABLE frame_data (
    id INTEGER PRIMARY KEY,
    character TEXT NOT NULL,
    move_name TEXT NOT NULL,
    move_category TEXT,  -- '弱攻撃', '空中攻撃', etc.
    startup_frame INTEGER,
    total_frames INTEGER,
    damage REAL,
    damage_1v1 REAL,
    landing_lag INTEGER,
    shield_advantage INTEGER,
    raw_data TEXT,  -- 元のExcelデータ
    UNIQUE(character, move_name)
);

CREATE INDEX idx_character ON frame_data(character);
CREATE INDEX idx_move ON frame_data(move_name);
```

#### 1.3 Pinecone メタデータ強化
```python
# 技データ専用のnamespace使用
namespace = "frame_data"

metadata = {
    'character': 'ヒカリ',
    'move_name': '空前',
    'move_category': '空中攻撃',
    'startup': 8,
    'total_frames': 37,
    'damage': 7.0,
    'damage_1v1': 8.4,
    'is_structured': True,  # 構造化データフラグ
    'text_content': '【ヒカリ】空前: 発生8F, 全体37F, ダメージ7%(1v1: 8.4%)'
}
```

### Phase 2: ハルシネーション防止機能

#### 2.1 正確なデータ検索システム
```python
def search_frame_data_accurate(character: str, move_name: str) -> dict:
    """
    SQLiteから正確なフレームデータを取得
    
    ハルシネーションを防ぐため、LLMではなくSQLで直接検索
    """
    conn = sqlite3.connect('data/framedata.db')
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM frame_data 
        WHERE character LIKE ? AND move_name LIKE ?
    """, (f'%{character}%', f'%{move_name}%'))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            'character': result[1],
            'move_name': result[2],
            'startup': result[4],
            'total_frames': result[5],
            'damage': result[6],
            'damage_1v1': result[7],
            # ... 他のフィールド
        }
    
    return None
```

#### 2.2 DSPy Signatureの改善
```python
class FrameDataAnswer(dspy.Signature):
    """
    フレームデータに関する質問に回答する。
    
    **重要**: 提供されたframe_data内の数値を**絶対に改変してはならない**。
    データがない場合は「データが見つかりません」と正直に答えること。
    ハルシネーション（データの捏造）は厳禁。
    """
    question = dspy.InputField(desc="ユーザーの質問")
    frame_data = dspy.InputField(desc="SQLiteから取得した正確なフレームデータ（JSON形式）")
    answer = dspy.OutputField(desc="frame_dataの数値をそのまま使った回答。数値の改変は絶対禁止。")
```

#### 2.3 検証レイヤーの追加
```python
def validate_answer(question: str, answer: str, source_data: dict) -> bool:
    """
    LLMの回答が元データと一致しているか検証
    
    Returns:
        True: 回答が正確
        False: ハルシネーション検出
    """
    import re
    
    # 回答から数値を抽出
    answer_numbers = re.findall(r'\d+', answer)
    
    # 元データの数値
    source_numbers = [
        str(source_data.get('startup', '')),
        str(source_data.get('total_frames', '')),
        str(source_data.get('damage', '')),
    ]
    
    # 回答に含まれる数値が元データに存在するか確認
    for num in answer_numbers:
        if num not in source_numbers:
            print(f"⚠️ ハルシネーション検出: {num} は元データに存在しません")
            return False
    
    return True
```

### Phase 3: 実装優先順位

#### 🔴 最優先（即座に実装）
1. ヒカリの空前データをSQLiteに手動で追加（緊急対応）
2. `search_frame_data()`関数をSQLiteベースに変更
3. ハルシネーション検証レイヤーを追加

#### 🟡 高優先（1-2日以内）
1. Excel→SQLiteの構造化パーサー実装
2. 全キャラクターの技データをSQLiteに再ingestion
3. Pineconeメタデータを構造化形式に更新

#### 🟢 中優先（1週間以内）
1. フレームデータ専用のDSPy Signatureを作成
2. データ検証システムの自動化
3. ユニットテスト追加

## 🧪 検証方法

### テストケース
```python
# test_frame_data_accuracy.py
def test_hikari_fair():
    """ヒカリの空前データが正確か確認"""
    brain = SmashBrain()
    answer = brain("ヒカリの空前の発生フレームは？")
    
    assert "8F" in answer or "8フレーム" in answer
    assert "7F" not in answer  # 間違ったデータが含まれていないか
    assert "9F" not in answer
```

## 📊 期待される効果

- **ハルシネーション率**: 30-40% → 0-5%
- **データ精度**: 60% → 98%+
- **ユーザー信頼性**: 大幅向上
- **保守性**: SQLiteベースで管理が容易

## 🎓 教訓

1. **数値データはLLMに任せない**: 正確な数値は必ずDBから取得
2. **構造化が重要**: 生データではなく、フィールドごとに分解
3. **検証レイヤー必須**: LLMの出力を常に検証
4. **適切な技術選択**: セマンティック検索 vs 構造化検索を使い分ける
