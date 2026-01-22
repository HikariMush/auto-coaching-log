#!/usr/bin/env python3
"""
ヒカリのデータがPineconeに正しく格納されているか確認
"""
import os
from pinecone import Pinecone
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

def main():
    PINECONE_API_KEY = os.getenv('PINECONE_API_KEY')
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
    
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index('smash-coach-index')
    genai.configure(api_key=GEMINI_API_KEY)
    
    print("=== ヒカリのデータ検索テスト ===\n")
    
    # テスト1: ヒカリの空前を検索
    query = 'ヒカリの空前の発生フレーム'
    print(f"検索クエリ: {query}\n")
    
    emb = genai.embed_content(model='models/text-embedding-004', content=query)
    results = index.query(vector=emb['embedding'], top_k=10, include_metadata=True)
    
    print(f"検索結果: {len(results.get('matches', []))}件\n")
    
    hikari_found = False
    for i, match in enumerate(results.get('matches', [])):
        meta = match.get('metadata', {})
        title = meta.get('title', '')
        character = meta.get('character', '')
        section = meta.get('section', '')
        data_preview = meta.get('data_preview', '')
        score = match.get('score', 0)
        
        if 'ヒカリ' in character or 'ヒカリ' in title or 'ヒカリ' in data_preview:
            hikari_found = True
            print(f"✅ [{i+1}] スコア: {score:.3f}")
            print(f"   キャラクター: {character}")
            print(f"   セクション: {section}")
            print(f"   プレビュー: {data_preview[:200]}")
            print()
    
    if not hikari_found:
        print("⚠️ ヒカリに関するデータが見つかりませんでした\n")
        print("全検索結果:")
        for i, match in enumerate(results.get('matches', [])):
            meta = match.get('metadata', {})
            print(f"[{i+1}] {meta.get('character', 'N/A')} - {meta.get('section', 'N/A')} (score: {match.get('score', 0):.3f})")
    
    # テスト2: メタデータフィルタで直接検索
    print("\n=== メタデータフィルタでの検索 ===\n")
    
    # Pineconeの統計を取得
    stats = index.describe_index_stats()
    print(f"インデックス統計: {stats}\n")
    
    # ヒカリを含むベクトルを検索
    results2 = index.query(
        vector=emb['embedding'],
        top_k=20,
        include_metadata=True,
        filter={"character": {"$eq": "ヒカリ"}}
    )
    
    print(f"ヒカリのベクトル数: {len(results2.get('matches', []))}件")
    
    if results2.get('matches'):
        print("\nヒカリのデータサンプル:")
        for i, match in enumerate(results2.get('matches', [])[:5]):
            meta = match.get('metadata', {})
            print(f"[{i+1}] {meta.get('section', 'N/A')}: {meta.get('data_preview', 'N/A')[:100]}")

if __name__ == '__main__':
    main()
