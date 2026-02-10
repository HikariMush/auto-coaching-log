#!/usr/bin/env python3
"""
Pinecone Index → Curriculum Generation Pipeline

このスクリプトは以下を実行します：
1. Pineconeインデックス「smash-zettel」から全データを抽出
2. raw_data/*.txt と general_knowledge.jsonl をマージして知識ベースを統合
3. 各知識を「基礎・応用・戦術・キャラ特性」で自動分類
4. スマブラ初心者～上級者の学習ステップを定義し、Zettelをマッピング
5. カリキュラム成立に必要な欠落知識を識別
6. curriculum_draft.md を生成（非エンジニア向け実践的形式）
"""

import os
import json
import glob
from pathlib import Path
from typing import List, Dict, Any
import google.generativeai as genai
from pinecone import Pinecone
from datetime import datetime

# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = "smash-zettel"
OUTPUT_FILE = "curriculum_draft.md"

def configure_apis():
    """Initialize Gemini and Pinecone clients."""
    genai.configure(api_key=GEMINI_API_KEY)
    pc = Pinecone(api_key=PINECONE_API_KEY)
    return pc

def extract_pinecone_data(pc: Pinecone) -> List[Dict[str, Any]]:
    """
    Pineconeインデックスから全データを抽出
    メタデータの問題を回避するため、テキストベースに切り替え
    """
    try:
        index = pc.Index(INDEX_NAME)
        stats = index.describe_index_stats()
        total_vectors = stats.get("total_vector_count", 0)
        print(f"📊 Pinecone Index Stats: {total_vectors} vectors")
        
        all_documents = []
        
        # Pineconeからのクエリで複数回に分けてデータを取得
        # ダミーベクトルで全体的にスコアの高いものから取得
        try:
            results = index.query(
                vector=[0.1] * 768,  # ダミーベクトル
                top_k=min(10000, max(1000, total_vectors)),
                include_metadata=True
            )
            
            for i, match in enumerate(results.get("matches", [])):
                metadata = match.get("metadata", {})
                text = metadata.get("text", "")
                
                # テキストが存在する場合のみ取得
                if text and len(text.strip()) > 0:
                    # テキストから自動的にタイトルを抽出（最初の1行or最初の50文字）
                    lines = text.split('\n')
                    title = lines[0][:100] if lines[0] else f"Document_{i}"
                    
                    all_documents.append({
                        "id": match.get("id", f"doc_{i}"),
                        "title": title,
                        "text": text[:500],  # 最初の500文字を保持
                        "full_text": text,
                        "source": "pinecone",
                        "category": metadata.get("category", "")
                    })
            
            print(f"✅ Extracted {len(all_documents)} documents from Pinecone")
            return all_documents
        
        except Exception as e:
            print(f"⚠️  Pinecone query error: {e}")
            return []
        
    except Exception as e:
        print(f"❌ Pinecone connection error: {e}")
        return []

def load_local_documents() -> List[Dict[str, str]]:
    """
    ローカルファイルから知識を読み込み
    - src/brain/raw_data/*.txt
    - data/general_knowledge.jsonl
    """
    documents = []
    
    # 1. raw_data/*.txt
    raw_data_dir = Path("src/brain/raw_data")
    for txt_file in sorted(raw_data_dir.glob("*.txt")):
        if txt_file.name == "スマブラSP フレームデータ by検証窓.xlsx":
            continue
        try:
            with open(txt_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    documents.append({
                        "id": txt_file.stem,
                        "title": txt_file.stem,
                        "text": content[:500],
                        "full_text": content,
                        "source": "raw_data",
                        "category": classify_raw_data_category(txt_file.stem)
                    })
        except Exception as e:
            print(f"⚠️  Error reading {txt_file}: {e}")
    
    # 2. general_knowledge.jsonl
    gk_file = Path("data/general_knowledge.jsonl")
    if gk_file.exists():
        try:
            with open(gk_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        try:
                            entry = json.loads(line)
                            documents.append({
                                "id": f"gk_{entry.get('timestamp', 'unknown')}",
                                "title": entry.get("title", "Unknown"),
                                "text": entry.get("content", "")[:500],
                                "full_text": entry.get("content", ""),
                                "source": "general_knowledge",
                                "category": entry.get("category", "frame_theory")
                            })
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            print(f"⚠️  Error reading general_knowledge.jsonl: {e}")
    
    print(f"✅ Loaded {len(documents)} local documents")
    return documents

def classify_raw_data_category(filename: str) -> str:
    """raw_data/*.txt をカテゴリ分類"""
    mechanics = [
        "ジャンプ", "ダッシュ_走行", "Cスティック", "シールド", "ガード硬直",
        "ジャストシールド", "つかみ", "受け身", "回避", "着地",
        "ヒットストップ", "硬直差の計算", "攻撃判定", "相殺", "ふっとび",
        "ふっとび速度", "ふっとび加速演出", "ふっとび硬直", "ベクトル変更",
        "ずらし", "ふりむき_慣性反転", "先行入力", "レバガチャ",
        "転倒", "たおれ_ダウン", "ぬるり_押し合い", "踏み台ジャンプ",
        "急降下", "アーマー", "反射_吸収", "属性_攻撃判定"
    ]
    
    if any(m in filename for m in mechanics):
        return "mechanics"
    elif any(x in filename for x in ["撃墜", "致命", "バースト"]):
        return "advanced_strategy"
    elif any(x in filename for x in ["攻撃", "シフト", "判定", "相殺", "優先度"]):
        return "frame_theory"
    else:
        return "general"

def map_documents_to_curriculum_enhanced(all_documents: List[Dict]) -> Dict[int, List[Dict]]:
    """
    改善されたマッピング：テキスト内容ベース＋キーワードベース
    """
    
    step_keywords = {
        1: ["ジャンプ", "ダッシュ", "シールド", "ふっとび", "吹っ飛び", "ダウン", "歩き", "走行", "移動", "基本"],
        2: ["着地", "受け身", "ジャストシールド", "つかみ", "投げ", "アクション", "着地狩り", "無敵", "反撃"],
        3: ["崖", "復帰", "崖上がり", "読み合い", "着地狩り", "復帰阻止", "対戦", "立ち回り"],
        4: ["硬直", "フレーム", "ガード", "硬直差", "確定反撃", "全体フレーム", "発生", "ヒットストップ", "数値"],
        5: ["キャラ", "対策", "相手", "優先度", "属性", "判定", "強み", "弱み", "相性", "性能"],
        6: ["パターン", "心理", "ワンパターン", "相殺", "戦術", "優位性", "クセ", "読み", "メタ"]
    }
    
    mapping = {i: [] for i in range(1, 7)}
    
    for doc in all_documents:
        title = doc.get('title', '').lower()
        text = (doc.get('text', '') + ' ' + doc.get('full_text', '')[:300]).lower()
        
        # 各ステップでのマッチ度を計算
        step_scores = {}
        for step, keywords in step_keywords.items():
            score = 0
            for kw in keywords:
                kw_lower = kw.lower()
                if kw_lower in title:
                    score += 3  # タイトルでのマッチは高い
                if kw_lower in text:
                    score += 1  # テキストでのマッチ
            step_scores[step] = score
        
        # スコアが最も高いステップに割り当て
        best_step = max(step_scores, key=step_scores.get)
        if step_scores[best_step] > 0:  # スコアが0でない場合のみ
            mapping[best_step].append({
                "title": doc.get('title', 'Unknown'),
                "summary": doc.get('title', 'Unknown'),
                "source": doc.get('source', 'unknown'),
                "score": step_scores[best_step]
            })
        else:
            # デフォルトはステップ1
            mapping[1].append({
                "title": doc.get('title', 'Unknown'),
                "summary": doc.get('title', 'Unknown'),
                "source": doc.get('source', 'unknown'),
                "score": 0
            })
    
    # 各ステップをスコアでソート
    for step in mapping:
        mapping[step] = sorted(mapping[step], key=lambda x: x['score'], reverse=True)
    
    return mapping

def identify_gaps(mapped_docs: Dict, all_documents: List[Dict]) -> List[str]:
    """
    カリキュラム成立に必要な欠落知識を識別
    """
    gaps = []
    
    required_knowledge = {
        1: ["ジャンプ", "ダッシュ", "シールド", "ふっとび"],
        2: ["着地", "受け身", "ジャストシールド"],
        3: ["読み合い", "崖上がり", "復帰阻止"],
        4: ["硬直差", "フレームデータ", "確定反撃"],
        5: ["キャラ対策", "相手の技"],
        6: ["心理戦", "パターン認識"]
    }
    
    all_titles = [d.get('title', '').lower() for d in all_documents]
    
    for step, keywords in required_knowledge.items():
        for keyword in keywords:
            if not any(keyword.lower() in title for title in all_titles):
                gaps.append(f"【ステップ{step}】 {keyword} に関する詳細な説明")
    
    # キャラ特性の欠落チェック
    has_character_info = any(
        any(char in title for title in [d.get('title', '') for d in all_documents])
        for char in ["キャラ", "マリオ", "ピカチュウ", "リンク", "ドンキー"]
    )
    if not has_character_info:
        gaps.append("【ステップ5】各キャラクターの特性・強弱分析データ")
    
    return list(set(gaps))[:10]

def generate_curriculum_markdown(mapping: Dict, gaps: List[str], all_documents: List[Dict]) -> str:
    """
    curriculum_draft.md を生成（非エンジニア向け実践的形式）
    """
    
    steps_info = [
        {
            "step": 1,
            "name": "超基礎：ゲームを理解しよう",
            "description": "スマブラのゲームシステムの基本的なルール",
            "goals": [
                "ジャンプ、ダッシュ、歩きの違い",
                "攻撃の種類（弱、強、特殊攻撃）",
                "シールド、ガード、回避の仕組み",
                "吹っ飛びのシステム"
            ]
        },
        {
            "step": 2,
            "name": "基礎テクニック：操作を覚える",
            "description": "キャラを安定して動かすための基本操作",
            "goals": [
                "着地の最適化",
                "受け身と回避のタイミング",
                "ジャストシールドの基本",
                "つかみと投げのタイミング"
            ]
        },
        {
            "step": 3,
            "name": "戦術基礎：読み合いの基本",
            "description": "対戦で相手の行動を予測し、対抗する基本的な思考",
            "goals": [
                "相手の着地狩り",
                "崖上がり狩りの読み合い",
                "復帰阻止の基本",
                "立ち回りの基本（間合い、距離感）"
            ]
        },
        {
            "step": 4,
            "name": "知識応用：フレームデータの活用",
            "description": "硬直差を理解して、より正確な立ち回りを構築",
            "goals": [
                "硬直差の計算",
                "確定反撃の考え方",
                "ガード硬直と反撃のタイミング",
                "技の出だし～全体フレームの意味"
            ]
        },
        {
            "step": 5,
            "name": "戦術応用：対キャラ対策",
            "description": "特定キャラへの理解を深め、有利不利を覆す戦い方",
            "goals": [
                "相手キャラの強みと弱み",
                "対キャラ固有の立ち回り",
                "相手の主力技への対抗策",
                "キャラ性能を理解した動き"
            ]
        },
        {
            "step": 6,
            "name": "高度な理論：心理戦と読み合い",
            "description": "パターン認識、読み合い、メタゲームの深い理解",
            "goals": [
                "相手のクセ分析",
                "ワンパターン対策",
                "心理戦での優位性確保",
                "状況判断と柔軟な戦術変更"
            ]
        }
    ]
    
    content = f"""# スマブラ Ultimate - 誰でも上達するカリキュラム

**最終更新**: {datetime.now().strftime('%Y年%m月%d日')}

このカリキュラムは、初心者から上級者まで、体系的にスマブラが上達するために必要な知識と練習メニューをまとめています。

各ステップは段階的に構成されており、前のステップを理解してから次に進むことをお勧めします。

**ご利用について**: このカリキュラムは自動生成されています。ご自身の学習進度に合わせて、自由にアレンジしてご使用ください。

---

## 📚 カリキュラム構成（全6ステップ）

"""
    
    for step_info in steps_info:
        step_num = step_info["step"]
        content += f"""
### ステップ {step_num}: {step_info["name"]}

**目的**: {step_info["description"]}

**このステップで学べること:**
"""
        for goal in step_info["goals"]:
            content += f"\n- {goal}"
        
        # マッピングされたドキュメントを追加
        docs = mapping.get(step_num, [])
        if docs:
            # タイトルが空でないドキュメントのみを表示
            valid_docs = [d for d in docs if d.get('title', '').strip() and d.get('title', '') != '']
            if valid_docs:
                content += f"\n\n**参考資料（{len(valid_docs)}件）:**\n"
                for doc in valid_docs[:10]:
                    content += f"\n- {doc['title']}"
            else:
                content += "\n\n**参考資料**: このステップ向けの資料は現在準備中です。\n"
        else:
            content += "\n\n**参考資料**: このステップ向けの資料は現在準備中です。\n"
        
        content += "\n"
    
    # 欠落知識セクション
    content += """

---

## ⚠️ 現在のカリキュラムで不足している知識

以下の知識が追加されると、カリキュラムが更にお使いやすくなります：

"""
    
    if gaps:
        for gap in gaps:
            content += f"\n- {gap}"
    else:
        content += "\n✅ 現在のところ大きな欠落はありません。"
    
    # 知識ベースサマリー
    content += f"""

---

## 📊 知識ベース構成

**総知識アイテム数**: {len(all_documents)}

**データソース別内訳:**
"""
    
    source_count = {}
    for doc in all_documents:
        source = doc.get('source', 'unknown')
        source_count[source] = source_count.get(source, 0) + 1
    
    for source, count in sorted(source_count.items()):
        content += f"\n- {source}: {count}件"
    
    # 使用方法
    content += """

---

## 🎮 このカリキュラムの使い方

### 基本的な進め方

1. **ステップ1から順番に進める**  
   各ステップで紹介された「参考資料」を読み、その中から実際に練習する項目を選んでください。

2. **理解 → 練習 → 実戦のサイクル**
   - **理解**: 資料を読んで概念を把握
   - **練習**: Training Mode や CPU相手で繰り返し練習
   - **実戦**: オンライン対戦やフレンド戦で実際に試す

3. **自分のペースで進める**  
   急ぐ必要はありません。完全に理解できるまで何度も繰り返しましょう。

4. **上級段階への準備**  
   ステップ4以降は、キャラクター知識（フレームデータ）が重要になります。  
   ご使用のキャラクターの技フレームを学習資料と合わせて確認してください。

---

## 💡 効果的な練習のコツ

### Phase A: 基礎を固める（ステップ1-2）
- 毎日少なくとも30分、基本操作を意識して練習
- CPUとの練習で基本行動を習慣化
- 鏡戦(CPU同キャラ)で自分の動きを客観的に見直す

### Phase B: 対戦理解を深める（ステップ3-4）
- フレンド戦で基本的な立ち回りを習得
- 同じ相手と複数回戦い、相手のパターンを覚える
- 後述される「対キャラ対策」の準備段階

### Phase C: 対戦成長を加速（ステップ5-6）
- オンライン対戦で様々な相手と戦う経験
- 敗北パターンから相手の得意な行動を読み解く
- 自分のクセ・パターンを修正する意識的な練習

---

## 📊 進捗確認チェックリスト

各ステップで以下ができたら、次のステップに進む準備が整っています：

### ステップ1完了の目安
- [ ] 各操作入力の基本ができる
- [ ] ゲーム全体の流れが理解できた
- [ ] 相手の吹っ飛ぶ様子を観察できる

### ステップ2完了の目安
- [ ] 着地パターンが5種類以上ある
- [ ] 相手の着地を狩ることができる
- [ ] ガードキャンセルで反撃できる

### ステップ3完了の目安
- [ ] 崖上がりの読み合いで勝つことがある
- [ ] 復帰阻止で相手を撃墜できる
- [ ] 立ち回りで相手にプレッシャーをかけられる

### ステップ4完了の目安
- [ ] フレームデータを見て確定反撃が分かる
- [ ] 相手の技の隙を突ける
- [ ] ガード硬直差を意識した立ち回りができる

### ステップ5完了の目安
- [ ] メインキャラの主力技が10種類以上ある
- [ ] 相手キャラの主力技と対策方法が言える
- [ ] 有利・不利キャラの戦い方が変わる

### ステップ6完了の目安
- [ ] 同じ相手に複数回勝つことができる
- [ ] 相手のクセから次の行動が予測できる
- [ ] オンライン対戦でWin Rate 50%以上

---

## 💪 よくある質問

**Q1: 各ステップにはどのくらい時間がかかりますか？**

A: 個人差が大きいですが、一般的には：
- ステップ1-2: 2-4週間（毎日1-2時間練習の場合）
- ステップ3-4: 1-2ヶ月
- ステップ5-6: 3-6ヶ月以上

焦らず、確実に理解することを優先してください。

---

**Q2: 途中でつまずいた場合は？**

A: 
- 前のステップに戻って基礎を復習してください
- 同じ資料を何度も読むことは全く問題ありません
- フレンド戦で他プレイヤーからのアドバイスを受けるのも効果的です

---

**Q3: メインキャラを決めるべき時期は？**

A: 
- ステップ1-3では複数キャラを試すことをお勧めします
- ステップ4以降（フレームデータ学習開始時点）でメインキャラを決めましょう
- 一度決めたら、そのキャラで数ヶ月は継続することが上達の近道です

---

## 🔄 継続的な改善

このカリキュラムは、プレイヤーからのフィードバックで常に改善されています。

以下のような場合は、フィードバックをお願いします：
- 「このステップはもっと簡単/難しくすべき」
- 「この知識が足りない」
- 「この資料が分かりやすかった/分かりにくかった」

---

## 📖 付録：重要な用語集

- **フレーム**: ゲームの最小時間単位（1フレーム = 1/60秒）
- **硬直**: 技を出した後、次の行動まで待つ必要がある期間
- **硬直差**: ガード時に発生する両プレイヤー間の硬直時間の差
- **確定反撃**: 相手の技をガードした時、確実に入る反撃
- **ベクトル**: 吹っ飛びの方向と速度
- **復帰**: ステージ外から戻ること
- **崖狩り**: 相手の崖掴まりや崖上がりを攻撃すること
- **心理戦**: 相手のパターンを読み、予測に基づいた行動をすること

---

**作成**: SmashZettel Curriculum Generator  
**バージョン**: {datetime.now().strftime('%Y%m%d')}  
**対応ゲーム**: Super Smash Bros. Ultimate (スマブラSP)
"""
    
    return content

def main():
    """Main execution pipeline"""
    print("=" * 60)
    print("🎮 SmashBros Curriculum Generator")
    print("=" * 60)
    
    # Step 1: Pineconeから全データ抽出
    print("\n[STEP 1] データソース確認...")
    pc = configure_apis()
    pinecone_docs = extract_pinecone_data(pc)
    
    # Step 2: ローカルファイルから知識を読み込み
    print("\n[STEP 2] ローカル知識ファイル読み込み...")
    local_docs = load_local_documents()
    
    # 統合
    all_documents = pinecone_docs + local_docs
    
    # 重複削除（同じタイトルのものは一つに）
    seen_titles = set()
    unique_docs = []
    for doc in all_documents:
        title = doc.get('title', '').lower()
        if title and title not in seen_titles:
            unique_docs.append(doc)
            seen_titles.add(title)
    
    all_documents = unique_docs
    print(f"\n✅ 総知識アイテム数: {len(all_documents)} (重複削除後)")
    
    # Step 3: 改善されたマッピング
    print("\n[STEP 3] カリキュラムステップへのマッピング...")
    mapping = map_documents_to_curriculum_enhanced(all_documents)
    for step_num, docs in mapping.items():
        valid_docs = [d for d in docs if d.get('title', '').strip()]
        print(f"  ステップ {step_num}: {len(valid_docs)}件")
    
    # Step 4: 欠落知識を識別
    print("\n[STEP 4] 欠落知識の識別...")
    gaps = identify_gaps(mapping, all_documents)
    print(f"✅ 欠落知識数: {len(gaps)}")
    
    # Step 5: curriculum_draft.md を生成
    print("\n[STEP 5] curriculum_draft.md 生成中...")
    curriculum_content = generate_curriculum_markdown(mapping, gaps, all_documents)
    
    # ファイルに書き込み
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(curriculum_content)
    
    print(f"\n✅ カリキュラム生成完了: {OUTPUT_FILE}")
    print("=" * 60)

if __name__ == "__main__":
    main()
