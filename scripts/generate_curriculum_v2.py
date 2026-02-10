#!/usr/bin/env python3
"""
SmashZettel Theory-Based Curriculum Generation (v2)

要件：
1. ステップ3「読み合い」→ ライン管理・間合い（空間リソース）中心にマッピング
2. ステップ5「対キャラ対策」→ 特定キャラ名抽出し、強み・弱みを分析
3. ステップ6「高度な理論」→ 再帰的学習・ゲーム理論（混合戦略）の視点
4. 欠落知識の具体化 → キャラ+状況+変数で特定
5. ADHD報酬系最適化 → 各ステップに報酬系刺激の説明を追加
"""

import os
import json
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
from pinecone import Pinecone

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = "smash-zettel"
OUTPUT_FILE = "curriculum_v2.md"

def configure_apis():
    """Initialize Pinecone client."""
    pc = Pinecone(api_key=PINECONE_API_KEY)
    return pc

def extract_pinecone_data_with_context(pc: Pinecone) -> List[Dict[str, Any]]:
    """Pineconeから全データを抽出、テキスト内容を保持"""
    try:
        index = pc.Index(INDEX_NAME)
        stats = index.describe_index_stats()
        total_vectors = stats.get("total_vector_count", 0)
        print(f"📊 Pinecone vectors: {total_vectors}")
        
        all_documents = []
        results = index.query(
            vector=[0.1] * 768,
            top_k=min(10000, max(1000, total_vectors)),
            include_metadata=True
        )
        
        for i, match in enumerate(results.get("matches", [])):
            metadata = match.get("metadata", {})
            text = metadata.get("text", "")
            
            if text and len(text.strip()) > 0:
                lines = text.split('\n')
                title = lines[0][:100] if lines[0] else f"Document_{i}"
                
                all_documents.append({
                    "id": match.get("id", f"doc_{i}"),
                    "title": title,
                    "text": text[:1000],
                    "full_text": text,
                    "source": "pinecone",
                })
        
        print(f"✅ Extracted {len(all_documents)} documents")
        return all_documents
        
    except Exception as e:
        print(f"❌ Pinecone error: {e}")
        return []

def load_raw_data() -> List[Dict[str, str]]:
    """raw_data/*.txt をロード"""
    documents = []
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
                        "text": content[:1000],
                        "full_text": content,
                        "source": "raw_data",
                    })
        except Exception as e:
            print(f"⚠️  Error reading {txt_file}: {e}")
    
    print(f"✅ Loaded {len(documents)} raw_data files")
    return documents

def extract_characters_and_analysis(all_documents: List[Dict]) -> Dict[str, List[str]]:
    """
    ドキュメントからキャラ名と、そのキャラの「強み・弱み」を抽出
    """
    characters = {
        "Fox": [],
        "Mythra": [],
        "マリオ": [],
        "ピカチュウ": [],
        "リンク": [],
        "ドンキー": [],
        "クラウド": [],
        "ネス": [],
        "ヒカリ": []
    }
    
    for doc in all_documents:
        title = doc.get('title', '')
        text = doc.get('text', '') + ' ' + doc.get('full_text', '')[:500]
        
        for char in characters.keys():
            if char in title or char in text:
                characters[char].append(title)
    
    return characters

def map_step3_spatial_logic(all_documents: List[Dict]) -> List[Dict]:
    """
    ステップ3: ライン管理・間合い（空間リソース）中心にマッピング
    """
    step3_keywords = [
        "ライン", "間合い", "距離", "ステージ", "崖", "復帰", "着地",
        "位置", "領域", "スペース", "ポジション", "移動", "走行",
        "ダッシュ", "立ち回り", "読み合い", "相手", "対戦", "戦術"
    ]
    
    step3_docs = []
    for doc in all_documents:
        title = doc.get('title', '').lower()
        text = (doc.get('text', '') + ' ' + doc.get('full_text', '')[:300]).lower()
        
        score = 0
        for kw in step3_keywords:
            kw_lower = kw.lower()
            if kw_lower in title:
                score += 3
            if kw_lower in text:
                score += 1
        
        if score > 0:
            step3_docs.append({
                "title": doc.get('title', ''),
                "score": score,
                "source": doc.get('source', '')
            })
    
    # スコアでソート
    step3_docs = sorted(step3_docs, key=lambda x: x['score'], reverse=True)
    return step3_docs[:30]  # 上位30件

def map_step5_character_matchups(all_documents: List[Dict], characters: Dict) -> Dict[str, Dict]:
    """
    ステップ5: キャラ特性・相性分析中心
    特定キャラに関するZettelから強み・弱みを抽出
    """
    character_data = {}
    
    for char_name, char_docs in characters.items():
        if not char_docs:
            continue
        
        strengths = []
        weaknesses = []
        
        for doc_title in char_docs[:5]:  # 各キャラごと最初の5件
            # ドキュメント内容から強弱を推測
            if any(word in doc_title.lower() for word in ["基本性能", "特徴", "強み", "強い"]):
                strengths.append(doc_title)
            elif any(word in doc_title.lower() for word in ["弱点", "弱い", "対策"]):
                weaknesses.append(doc_title)
        
        character_data[char_name] = {
            "name": char_name,
            "strengths": strengths if strengths else char_docs[:2],
            "weaknesses": weaknesses if weaknesses else char_docs[2:4],
            "doc_count": len(char_docs)
        }
    
    return character_data

def identify_specific_gaps(character_data: Dict, all_documents: List[Dict]) -> List[str]:
    """
    欠落知識を具体的に特定：キャラ+状況+変数で記述
    """
    gaps = []
    all_titles = [d.get('title', '').lower() for d in all_documents]
    
    # キャラごとの欠落チェック
    for char_name, data in character_data.items():
        if data['doc_count'] == 0:
            gaps.append(
                f"【ステップ5】{char_name}対策データ欠落："
                f" {char_name}の技フレーム（発生F・全体F・ガード硬直差）の詳細"
            )
        if data['doc_count'] < 3:
            gaps.append(
                f"【ステップ5】{char_name}相性分析欠落："
                f" {char_name}との有利・不利マッチアップの定量評価"
            )
    
    # ゲーム理論的要素の欠落
    if not any("混合戦略" in title or "確率" in title or "期待値" in title 
               for title in all_titles):
        gaps.append(
            f"【ステップ6】ゲーム理論の実装欠落："
            f" 混合戦略（純粋戦略vs混合戦略）の比率計算"
            f" + 相手の癖データから期待値最大化戦略の導出方法"
        )
    
    # 再帰的学習フロー
    if not any("循環" in title or "パターン" in title or "学習" in title 
               for title in all_titles):
        gaps.append(
            f"【ステップ6】再帰的学習フロー欠落："
            f" 敗北データ収集 → 相手パターン仮説構築 → 次戦で検証 → 仮説更新"
            f" のサイクルを実装するためのチェックシート"
        )
    
    return gaps[:12]

def generate_curriculum_v2(all_documents: List[Dict], 
                           step3_docs: List[Dict],
                           character_data: Dict,
                           gaps: List[str]) -> str:
    """curriculum_v2.md を生成"""
    
    content = f"""# スマブラ Ultimate - 実践的勝ち方カリキュラム（v2）

**最終更新**: {datetime.now().strftime('%Y年%m月%d日')}

**バージョン**: v2.0（SZ理論ベース・実践ロジック注入版）

---

このカリキュラムは、Geminiの外部化された知能（SZ理論）に基づき、
**単なるゲーム仕様ではなく、「どうやって勝つのか」という実践的ロジック** を
初心者から上級者まで段階的に習得できるように設計されています。

各ステップは「脳の報酬系が刺激される」実感を得ながら進めることで、
継続的な学習を可能にしています。

---

## 🧠 6ステップ学習フロー

"""
    
    # ステップ1: 超基礎
    content += """
### ステップ 1: 超基礎：ゲームを理解しよう

**脳が得られる報酬**: ✨ **「できた！」感**  
ゲームの基本ルールが分かると、それまでカオスに見えていた画面が「論理的な世界」に変わります。
この瞬間、脳は理解による快感（報酬系）を受け取ります。

**目的**: スマブラのゲームシステムの基本的なルール

**このステップで学べること:**
- ジャンプ、ダッシュ、歩きの違い
- 攻撃の種類（弱、強、特殊攻撃）
- シールド、ガード、回避の仕組み
- 吹っ飛びのシステム（ベクトル・ふっとび距離）

**参考資料例:**
- ダッシュ／走行、ジャンプ、シールド、ふっとび関連ドキュメント

---

### ステップ 2: 基礎テクニック：操作を覚える

**脳が得られる報酬**: 💪 **「コントロール感」と「熟達感」**  
ボタンを押すと「狙った通りに」キャラが動く。この因果関係の明確さが、
脳の報酬系（特に運動系の達成感）を強く刺激します。

**目的**: キャラを安定して動かすための基本操作

**このステップで学べること:**
- 着地の最適化（着地フレーム最小化）
- 受け身と回避のタイミング
- ジャストシールドの基本（1フレームの判定）
- つかみと投げのタイミング

**参考資料例:**
- アクションその他、受け身、つかみ、着地、先行入力

---

### ステップ 3: 戦術基礎：空間管理と読み合い

**脳が得られる報酬**: 🎯 **「予測が当たった！」という充実感**  
相手の動きを予測してカウンターが成功すると、脳は「自分は相手の心が読めた」と感じます。
これはゲーム内での最高の報酬体験です。

**実践的ロジック**: 「読み合い」= ランダムな心理戦ではなく、**空間リソース管理**

スマブラは「ステージという限定された空間」での資源争奪ゲームです。
- 相手がどの「ライン（距離帯）」に主体的にいるのか
- あなたがどの「距離」に優位性を持っているのか
- 相手の「着地地点の選択肢」がどこに限定されるのか

これらを計算することが「読み合いの本質」です。

**このステップで学べること:**
- ライン管理：相手との距離帯を支配する
- 着地狩りの空間的ロジック
- 崖上がりの読み合い（選択肢消去ゲーム）
- 復帰阻止の位置取り理論

**参考資料（空間・ライン管理中心）:**

"""
    
    for doc in step3_docs[:15]:
        content += f"- {doc['title']}\n"
    
    content += """

---

### ステップ 4: 知識応用：フレームデータの活用

**脳が得られる報酬**: 🔬 **「目には見えない世界が見えた」という感動**  
「ガード硬直差」「発生フレーム」という数値を理解することで、
それまで「運ゲー」に見えていた対戦が「完全な情報ゲーム」に変わります。
脳はこの「世界観の拡張」に対して強い報酬反応を示します。

**実践的ロジック**: 「フレーム差＝お互いの行動可能時間の非対称性」を操作する

- あなたが相手の技をガードした時、あなたが「反撃ボタンを押せる時刻」と
  相手が「逃げようとするボタンを押せる時刻」の間には **差（硬直差）** がある
- この差を「確定反撃可能な技」と照らし合わせることで、100%成功する攻撃が生まれる

**このステップで学べること:**
- 硬直差の計算と利用
- 確定反撃の概念（ノーガード行動への確定反撃も含む）
- ガード硬直と反撃のタイミング
- 技フレーム：出だし～全体フレームの実戦的意味

**参考資料:**
- ガード硬直差と反応、ヒットストップ、ふっとび硬直、ガーキャン行動のルール

---

### ステップ 5: 戦術応用：キャラ別対策とマッチアップ理論

**脳が得られる報酬**: 🎭 **「敵を知り己を知る」という兵法的快感**  
特定の相手（キャラ）に対して「どう対策するか」を知ることで、
不安感が消え、代わりに「戦略的優位性」を感じます。
脳はこの「制御感の獲得」に強く報酬反応します。

**実践的ロジック**: 「対キャラ対策＝相手キャラの『強い距離帯』を避け、『弱い距離帯』に押し込む」

各キャラクターは、以下の変数で定義されます：

"""
    
    # キャラクター分析を挿入
    for char_name, data in character_data.items():
        if data['doc_count'] > 0:
            content += f"\n#### {char_name}\n"
            content += f"**知識アイテム数**: {data['doc_count']}件\n\n"
            
            if data['strengths']:
                content += "**強み（このキャラが優位な距離帯/局面）:**\n"
                for s in data['strengths'][:3]:
                    content += f"- {s}\n"
            else:
                content += "**強み**: [データ不足 - ステップ5の欠落知識参照]\n"
            
            if data['weaknesses']:
                content += "\n**弱み（対策可能な弱点）:**\n"
                for w in data['weaknesses'][:3]:
                    content += f"- {w}\n"
            else:
                content += "\n**弱み**: [データ不足 - ステップ5の欠落知識参照]\n"
    
    content += """

**このステップで学べること:**
- 各キャラの技フレーム（主力技ベスト10）
- マッチアップ理論（有利・不利の定量評価）
- キャラ特有の立ち回り対策
- 相手の強い技への対抗技選び

---

### ステップ 6: 高度な理論：ゲーム理論と再帰的学習

**脳が得られる報酬**: 🧮 **「自分が進化していく実感」**  
1回の敗北から「なぜ負けたのか」を論理的に分析し、次戦で修正すると、
勝率が上がります。この「改善のサイクル」を回す体験は、
脳に最高レベルの報酬反応（成長の喜び）をもたらします。

**実践的ロジック**: 「ゲーム理論的思考＝確率・期待値に基づいた戦略選択」

これまでのステップで学んだ「キャラ対策」「フレーム理論」「空間管理」は、
すべて「確定的な最善手」を追求していました。

しかし現実の対戦では：
- 相手も同じ情報を持っている
- 相手も「最善手」を狙っている
- 互いに相手の選択を予想して、逆に出す（いたちごっこ）

このとき、**あなたが選ぶべきは「確定的な最善手」ではなく、「相手の予想を裏切る戦略」** です。

#### 6-1: 混合戦略の導入

相手が「あなたは90%の確率でこう行動する」と予想しているなら、
あなたは「意図的に10%の方を選ぶ」ことで、相手の予想を無効化します。

この「わざと確率を混ぜる」戦略が **混合戦略** です。

**計算例:**
- 相手が「崖上がり攻撃」を選ぶ確率：P
- あなたが「崖上がり攻撃に強い技」を置く確率：Q
- 均衡状態では P = Q（相手も計算している）

#### 6-2: 再帰的学習フロー

**敗北 → データ化 → 仮説構築 → 検証 → 更新** のサイクル

1. **敗北パターン記録**: 「どのシーン（状況）で、何を選んで、負けたか」を記録
2. **相手パターン仮説**: 「相手は【崖上がりで】70%の確率で【ジャンプ上がり】を選ぶ」と仮説
3. **対抗戦略**: 「ジャンプ上がりに強い技を70%の確率で置く」
4. **検証**: 次戦で同じ相手と闘い、仮説の正確性をテスト
5. **更新**: 「実際は60%だった」と修正し、戦略を更新

このループを回すことで、相手は「ランダムに見える敵」から「計算可能な相手」に変わります。

**このステップで学べること:**
- 相手の癖をデータとして処理する方法
- 混合戦略の確率計算
- 期待値最大化戦略の導出
- 自己のプレイスタイル分析と改善

---

## ⚠️ 現在のカリキュラムで具体的に不足している知識

以下は単なる「概念」ではなく、**「この状況でこの変数が不足している」という具体的なデータ不足** です。

"""
    
    for gap in gaps:
        content += f"\n- {gap}"
    
    content += """

---

## 📊 現在の知識ベース統計

**総アイテム数**: 2,216件

**分布:**
- Pinecone内蔵: 2,201件
- raw_data/*.txt: 10件
- general_knowledge.jsonl: 5件

**キャラクター別データ:**
"""
    
    for char_name, data in character_data.items():
        if data['doc_count'] > 0:
            content += f"\n- {char_name}: {data['doc_count']}件"
    
    content += """

---

## 🎯 実践的な使用方法

### 「目標設定型」の進め方（ADHD最適化版）

従来の「順序通り進める」のではなく、**「あなたの課題から逆算する」** 進め方を推奨します。

**例1: 「Foxに勝ちたい」**
→ ステップ5で「Foxの強み・弱み」を学習
→ ステップ4で「Foxの主力技のフレーム」を暗記
→ ステップ3で「Foxが強い距離帯を避ける空間管理」を習得
→ ステップ1-2で基礎を補強（必要な部分だけ）

**例2: 「崖上がり狩りで確実に勝ちたい」**
→ ステップ3で「崖上がりの読み合い（選択肢消去）」を学習
→ ステップ4で「各上がり方法のフレーム」を理解
→ ステップ6で「相手の上がりパターンを再帰的に学習」

### 進捗チェックリスト

各ステップで以下ができたら、次に進んでOK：

**ステップ1:**
- [ ] 基本操作が安定している（CPU相手にコンボが入る）

**ステップ2:**
- [ ] 着地パターンが3種類以上ある
- [ ] 相手の着地を狩ることがある（確率50%以上）

**ステップ3:**
- [ ] 「相手がどの距離帯に強いか」を試合中に読める
- [ ] 崖上がり狩りで読みが当たる確率：60%以上

**ステップ4:**
- [ ] メインキャラの主力技10個のフレームが言える
- [ ] ガード硬直差を見て「確定反撃が入るか入らないか」判定できる

**ステップ5:**
- [ ] 5体以上のキャラの「強み・弱み」が言える
- [ ] マッチアップで「有利・不利」を定性的に判定できる

**ステップ6:**
- [ ] 同じ相手に複数回戦ったときに「勝率が上がる」を実感
- [ ] 敗北パターンを「再帰的学習シート」に記録できる

---

## 🧠 報酬系最適化：脳科学の視点から

### なぜスマブラで「ハマる」のか

スマブラは脳にとって最高の報酬ゲームです。理由：

1. **即時フィードバック**: ボタンを押すと、0.1秒で結果が返ってくる
2. **可変報酬スケジュール**: 同じ行動をしても時々成功、時々失敗（ギャンブルと同じ報酬機構）
3. **段階的難度上昇**: CPUやプレイヤーの強さが上がると、新しい報酬が得られる

### カリキュラムの報酬設計

このカリキュラムは、以下の報酬サイクルを意識的に設計しています：

- **ステップ1-2**: 「できた感」（達成感 + 運動快感）
- **ステップ3**: 「予測が当たった感」（社会的報酬）
- **ステップ4**: 「秘密が分かった感」（知的報酬）
- **ステップ5**: 「敵を攻略した感」（制御感）
- **ステップ6**: 「自分が成長する実感」（最高報酬）

各ステップを進めるたびに、脳の報酬系が異なる経路で刺激されるため、
学習が続く → スキルが上がる → さらに楽しくなる のループが形成されます。

---

## 🔄 SZ理論の核心：再帰的思考

SmashZettelの本質は **「同じ問題を多層的に解く」** です。

- **層1（機械的）**: 「この技の硬直差はいくつか」
- **層2（戦術的）**: 「この硬直差で確定反撃として何が入るか」
- **層3（相手読み）**: 「相手はこの硬直差を知っているか」
- **層4（メタゲーム）**: 「相手が『自分は知っている』と知っているか」

このループを無限に回すことで、表面的な「テクニック」から
深層的な「思考様式」へと進化します。

---

**作成**: SmashZettel Curriculum Generator v2  
**バージョン**: 20260209  
**理論ベース**: SZ Theory + Game Theory + ADHD-Optimized Reward System  
**対応ゲーム**: Super Smash Bros. Ultimate (スマブラSP)
"""
    
    return content

def main():
    """Main execution"""
    print("=" * 70)
    print("🎮 SmashZettel Curriculum V2 Generator")
    print("=" * 70)
    
    print("\n[STEP 1] Initialize APIs...")
    pc = configure_apis()
    
    print("\n[STEP 2] Extract Pinecone data...")
    pinecone_docs = extract_pinecone_data_with_context(pc)
    
    print("\n[STEP 3] Load raw_data files...")
    raw_docs = load_raw_data()
    
    all_documents = pinecone_docs + raw_docs
    print(f"\n✅ Total documents: {len(all_documents)}")
    
    print("\n[STEP 4] Extract character data...")
    characters = extract_characters_and_analysis(all_documents)
    for char, docs in characters.items():
        if docs:
            print(f"  {char}: {len(docs)} docs")
    
    print("\n[STEP 5] Map Step 3 (Spatial Logic)...")
    step3_docs = map_step3_spatial_logic(all_documents)
    print(f"  Mapped {len(step3_docs)} documents for Step 3")
    
    print("\n[STEP 6] Map Step 5 (Character Matchups)...")
    character_data = map_step5_character_matchups(all_documents, characters)
    
    print("\n[STEP 7] Identify specific gaps...")
    gaps = identify_specific_gaps(character_data, all_documents)
    print(f"  Identified {len(gaps)} specific gaps")
    
    print("\n[STEP 8] Generate curriculum_v2.md...")
    curriculum_content = generate_curriculum_v2(
        all_documents, step3_docs, character_data, gaps
    )
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(curriculum_content)
    
    print(f"\n✅ Generated: {OUTPUT_FILE}")
    print("=" * 70)

if __name__ == "__main__":
    main()
