#!/usr/bin/env python3
"""
一般知識をPineconeに登録するスクリプト

使用方法:
    python ingest_general_knowledge.py
    
このスクリプトは data/general_knowledge.jsonl を読み込み、
Pineconeに高優先度の一般知識として登録します。
"""

import os
import json
from pathlib import Path
import google.generativeai as genai
from pinecone import Pinecone
from datetime import datetime

# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
GENERAL_KNOWLEDGE_FILE = Path("data/general_knowledge.jsonl")
INGESTION_STATE_FILE = Path("data/general_knowledge_ingestion_state.json")

def load_ingestion_state():
    """ingestion状態を読み込み"""
    if INGESTION_STATE_FILE.exists():
        with open(INGESTION_STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"ingested_timestamps": []}

def save_ingestion_state(state):
    """ingestion状態を保存"""
    INGESTION_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(INGESTION_STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def load_general_knowledge():
    """一般知識を読み込み（未処理のみ）"""
    if not GENERAL_KNOWLEDGE_FILE.exists():
        print(f"❌ General knowledge file not found: {GENERAL_KNOWLEDGE_FILE}")
        return []
    
    state = load_ingestion_state()
    ingested_timestamps = set(state.get("ingested_timestamps", []))
    
    entries = []
    skipped = 0
    with open(GENERAL_KNOWLEDGE_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                try:
                    entry = json.loads(line)
                    timestamp = entry.get('timestamp', '')
                    
                    # すでに処理済みの場合はスキップ
                    if timestamp in ingested_timestamps:
                        skipped += 1
                        continue
                    
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue
    
    if skipped > 0:
        print(f"⏭️  Skipped {skipped} already ingested entries")
    
    return entries

def ingest_to_pinecone(entries):
    """
    一般知識をPineconeに登録（重複処理を防ぐ）
    
    メタデータ:
    - is_general_knowledge: True（検索時に高優先度）
    - category: frame_theory/mechanic/strategy/character_specific
    - priority: 10（通常のドキュメントより高い）
    """
    if not PINECONE_API_KEY or not GEMINI_API_KEY:
        print("❌ API keys not found")
        return
    
    # Pinecone初期化
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index("smash-coach-index")
    
    # Gemini初期化
    genai.configure(api_key=GEMINI_API_KEY)
    
    # ingestion状態を読み込み
    state = load_ingestion_state()
    ingested_timestamps = state.get("ingested_timestamps", [])
    
    print(f"\n📊 Ingesting {len(entries)} general knowledge entries...")
    
    success_count = 0
    for i, entry in enumerate(entries, 1):
        try:
            title = entry.get('title', 'Unknown')
            content = entry.get('content', '')
            category = entry.get('category', 'general')
            timestamp = entry.get('timestamp', datetime.now().isoformat())
            
            # Embedding生成
            combined_text = f"{title}\n\n{content}"
            emb = genai.embed_content(
                model="models/text-embedding-004",
                content=combined_text
            )
            
            # Pineconeに登録
            vector_id = f"general_knowledge_{timestamp}_{i}"
            
            index.upsert(vectors=[{
                "id": vector_id,
                "values": emb['embedding'],
                "metadata": {
                    "title": title,
                    "text_content": content,
                    "category": category,
                    "is_general_knowledge": True,
                    "priority": 10,  # 高優先度
                    "type": "general_knowledge",
                    "timestamp": timestamp
                }
            }])
            
            # ingestion成功：タイムスタンプを記録
            if timestamp not in ingested_timestamps:
                ingested_timestamps.append(timestamp)
            
            print(f"  [{i}/{len(entries)}] ✅ {title}")
            success_count += 1
            
        except Exception as e:
            print(f"  [{i}/{len(entries)}] ❌ Error: {e}")
    
    # ingestion状態を保存
    state["ingested_timestamps"] = ingested_timestamps
    state["last_ingestion"] = datetime.now().isoformat()
    state["total_ingested"] = len(ingested_timestamps)
    save_ingestion_state(state)
    
    print(f"\n✅ Ingestion complete! ({success_count}/{len(entries)} succeeded)")
    print(f"📋 Total knowledge entries: {len(ingested_timestamps)}")

def main():
    print("="*70)
    print("🧠 General Knowledge → Pinecone Ingestion")
    print("="*70)
    
    # 一般知識を読み込み
    entries = load_general_knowledge()
    
    if not entries:
        print("\n❌ No general knowledge found.")
        print("   Use /add_knowledge command in Discord to add knowledge.")
        return 1
    
    print(f"\n✅ Loaded {len(entries)} general knowledge entries")
    
    # Pineconeに登録
    ingest_to_pinecone(entries)
    
    print(f"""
✅ General knowledge has been ingested!

Next steps:
1. Restart Discord bot (if running)
2. Ask questions related to the knowledge
3. The bot will now reference this high-priority general knowledge

Example:
- If you added "ガーキャンの例外ルール"
- Any question about ガーキャン will now get accurate info
- The bot will prioritize this general knowledge over other documents

📝 Note: You can run this script anytime new general knowledge is added:
   python ingest_general_knowledge.py
""")
    
    return 0

if __name__ == '__main__':
    import sys
    sys.exit(main())
