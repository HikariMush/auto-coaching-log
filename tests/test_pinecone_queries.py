#!/usr/bin/env python3
"""
Pinecone テストスクリプト
ドンキーの弱1, 弱2、カズヤの風神拳、キャラクター性質を検索・表示
"""

import os
import google.generativeai as genai
from pinecone import Pinecone

# API 初期化
genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
pc = Pinecone(api_key=os.environ.get('PINECONE_API_KEY'))
index = pc.Index('smash-coach-index')

def search_and_display(query_text: str, title: str, top_k: int = 3):
    """クエリを検索して結果を表示"""
    print(f"\n{'='*80}")
    print(f"🔍 {title}")
    print(f"{'='*80}")
    print(f"検索: '{query_text}'\n")
    
    # クエリをベクトル化
    embedding_response = genai.embed_content(
        model="models/embedding-001",
        content=query_text,
        task_type="SEMANTIC_SIMILARITY"
    )
    query_vector = embedding_response['embedding']
    
    # 検索実行
    results = index.query(
        vector=query_vector,
        top_k=top_k,
        include_metadata=True
    )
    
    if not results['matches']:
        print("❌ 検索結果がありません\n")
        return
    
    print(f"✅ {len(results['matches'])} 件見つかりました\n")
    
    for i, match in enumerate(results['matches'], 1):
        print(f"{i}. スコア: {match['score']:.4f}")
        print(f"   ID: {match['id']}")
        
        if 'metadata' in match:
            meta = match['metadata']
            print(f"   タイトル: {meta.get('title', '(なし)')}")
            
            # コンテンツプレビュー
            if 'text' in meta:
                text = meta['text']
                if isinstance(text, str):
                    preview = text[:200] + "..." if len(text) > 200 else text
                    print(f"   内容: {preview}")
            
            # その他のメタデータ
            for key in ['character', 'section', 'source']:
                if key in meta:
                    print(f"   {key}: {meta[key]}")
        
        print()

def main():
    """メイン処理"""
    print("\n" + "="*80)
    print("📊 Pinecone データテスト")
    print("="*80)
    
    # Pinecone 統計を表示
    try:
        stats = index.describe_index_stats()
        print(f"\n📈 インデックス統計:")
        print(f"   ベクトル総数: {stats.total_vector_count}")
        print(f"   ネームスペース: {list(stats.namespaces.keys())}")
    except Exception as e:
        print(f"⚠️  統計取得エラー: {e}")
    
    # 検索 1: ドンキーの弱1, 弱2
    search_and_display(
        "ドンキーコング 弱1 弱2 ジャブ フレーム",
        "【1】ドンキーコング - 弱1, 弱2 データ"
    )
    
    # 検索 2: カズヤの風神拳
    search_and_display(
        "カズヤ 風神拳 最速 上B 発生フレーム 打撃",
        "【2】カズヤ - 最速風神拳 データ"
    )
    
    # 検索 3: ドンキーの性質
    search_and_display(
        "ドンキーコング 重い 落下速度 重量 能力値 성质",
        "【3】ドンキーコング - キャラクター性質"
    )
    
    # 検索 4: 総合テスト - 複数キャラ検索
    search_and_display(
        "スマブラ フレームデータ 技 性質",
        "【4】全般 - フレームデータ検索",
        top_k=5
    )

if __name__ == '__main__':
    main()
