#!/usr/bin/env python3
"""Monitor Excel ingestion progress"""

import os
import json
from pathlib import Path
from pinecone import Pinecone
import time

DATA_DIR = Path(__file__).parent / 'data'
INGESTION_STATE_FILE = DATA_DIR / 'excel_ingestion_state.json'

def check_progress():
    """Check ingestion progress"""
    
    print("\n" + "="*70)
    print("📊 Ingestion Progress Monitor")
    print("="*70 + "\n")
    
    # Check state file
    if INGESTION_STATE_FILE.exists():
        with open(INGESTION_STATE_FILE, 'r') as f:
            state = json.load(f)
        
        print(f"✅ Sheets ingested: {len(state.get('ingested_sheets', []))}")
        if state.get('ingested_sheets'):
            print(f"   Last: {state['ingested_sheets'][-1]}")
    else:
        print("❌ No state file found (ingestion not started)")
        return
    
    # Check Pinecone
    try:
        pc = Pinecone(api_key=os.environ.get('PINECONE_API_KEY'))
        index = pc.Index("smash-coach-index")
        stats = index.describe_index_stats()
        
        print(f"\n📈 Pinecone index status:")
        print(f"   Total vectors: {stats.total_vector_count}")
        print(f"   Dimension: {stats.dimension}")
        
        # Count Excel vectors
        results = index.query(
            vector=[0]*768,  # Dummy vector
            top_k=100,
            include_metadata=True
        )
        
        excel_count = sum(1 for m in results['matches'] if m.get('metadata', {}).get('source') == 'excel_ingestion')
        print(f"   Excel vectors: {excel_count}")
    
    except Exception as e:
        print(f"⚠️  Cannot connect to Pinecone: {e}")
    
    print("\n" + "="*70 + "\n")

if __name__ == '__main__':
    # Monitor every 30 seconds
    try:
        while True:
            check_progress()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\n✋ Stopped monitoring")
