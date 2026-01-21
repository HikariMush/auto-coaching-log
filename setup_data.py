import os
import glob
from pinecone import Pinecone, ServerlessSpec
import google.generativeai as genai
from dotenv import load_dotenv
import time

load_dotenv()

# 設定
INDEX_NAME = "smash-zettel"
DATA_DIR = "src/brain/raw_data"

# API初期化 (GitHub Codespacesのシークレットを使用)
try:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
except Exception as e:
    print(f"❌ API KEYの読み込みに失敗しました。環境変数を確認してください: {e}")
    exit()

def get_embedding(text):
    # Geminiでベクトル化
    result = genai.embed_content(
        model="models/embedding-001",
        content=text,
        task_type="retrieval_document",
        title="Smash Context"
    )
    return result['embedding']

def main():
    print("🚀 データ構築を開始します...")
    
    # インデックス確認・作成
    try:
        existing_indexes = [i.name for i in pc.list_indexes()]
    except Exception as e:
        print(f"❌ Pinecone接続エラー: {e}")
        return

    if INDEX_NAME not in existing_indexes:
        print(f"📦 インデックス '{INDEX_NAME}' を作成中...")
        pc.create_index(
            name=INDEX_NAME,
            dimension=768, 
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1")
        )
        time.sleep(15) # 作成待ち時間を少し延長
    
    index = pc.Index(INDEX_NAME)
    
    # ファイル読み込み
    files = glob.glob(os.path.join(DATA_DIR, "*.txt"))
    if not files:
        print("❌ エラー: .txtファイルが見つかりません。" + DATA_DIR)
        return

    vectors = []
    print(f"📄 {len(files)} 個のファイルを処理中...")
    
    for file_path in files:
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
            if not text.strip(): continue
            file_name = os.path.basename(file_path)
            
            try:
                emb = get_embedding(text)
                vectors.append({
                    "id": file_name,
                    "values": emb,
                    "metadata": {"text": text}
                })
                print(f"  ✅ OK: {file_name}")
            except Exception as e:
                print(f"  ⚠️ 失敗: {file_name} -> {e}")

    # アップロード
    if vectors:
        print("☁️ Pineconeにアップロード中...")
        batch_size = 100
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i+batch_size]
            index.upsert(vectors=batch)
        print("🎉 データの準備完了！")

if __name__ == "__main__":
    main()
