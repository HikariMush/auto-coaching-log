"""
Data Ingestion Script: Vectorize and Upload SmashBros Knowledge to Pinecone

This script reads all .txt files from src/brain/raw_data/, embeds them using
Google's embedding-001 model, and uploads to Pinecone index.

DSPy Context:
- Not part of the DSPy pipeline itself, but enables data preparation.
- Creates the vector database that downstream Retriever modules query.
- Can be run as a standalone utility or integrated into CI/CD.

Usage:
    python -m src.utils.ingest
"""

import os
import glob
import time
from google import genai
from pinecone import Pinecone, ServerlessSpec
from typing import List, Dict, Any


def configure_apis() -> tuple:
    """
    Initialize Gemini and Pinecone clients.

    Returns:
    --------
    tuple
        (pinecone_client, pinecone_index)
    """
    # Gemini
    genai_key = os.getenv("GEMINI_API_KEY")
    if not genai_key:
        raise ValueError("GEMINI_API_KEY environment variable not set.")
    genai.configure(api_key=genai_key)

    # Pinecone
    pinecone_key = os.getenv("PINECONE_API_KEY")
    if not pinecone_key:
        raise ValueError("PINECONE_API_KEY environment variable not set.")

    pc = Pinecone(api_key=pinecone_key)
    return pc, genai_key


def ensure_index_exists(
    pc: Pinecone,
    index_name: str = "smash-zettel",
    dimension: int = 768,
) -> Any:
    """
    Create Pinecone index if it doesn't exist.

    Parameters:
    -----------
    pc : Pinecone
        Pinecone client instance.
    index_name : str
        Name of the index.
    dimension : int
        Vector dimension (Google embedding-001 uses 768).

    Returns:
    --------
    Any
        Pinecone Index object.
    """
    try:
        existing_indexes = [idx.name for idx in pc.list_indexes()]
    except Exception as e:
        print(f"[Error] Failed to list indexes: {e}")
        return None

    if index_name not in existing_indexes:
        print(f"📦 Creating index '{index_name}'...")
        pc.create_index(
            name=index_name,
            dimension=dimension,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
        print(f"⏳ Waiting for index creation (15s)...")
        time.sleep(15)
    else:
        print(f"✅ Index '{index_name}' already exists.")

    return pc.Index(index_name)


def load_documents(data_dir: str = "src/brain/raw_data") -> List[Dict[str, str]]:
    """
    Load all .txt files from the data directory.

    Parameters:
    -----------
    data_dir : str
        Path to directory containing .txt files.

    Returns:
    --------
    List[Dict[str, str]]
        List of dicts with 'filename', 'title', and 'text' keys.
    """
    documents = []
    file_paths = glob.glob(os.path.join(data_dir, "*.txt"))

    if not file_paths:
        print(f"[Warning] No .txt files found in {data_dir}")
        return []

    for file_path in sorted(file_paths):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read().strip()

            if not text:
                continue

            filename = os.path.basename(file_path)
            title = filename.replace(".txt", "")

            documents.append(
                {
                    "filename": filename,
                    "title": title,
                    "text": text,
                }
            )
            print(f"✅ Loaded: {filename}")

        except Exception as e:
            print(f"❌ Error loading {file_path}: {e}")

    print(f"\n📄 Total documents loaded: {len(documents)}")
    return documents


def embed_documents(
    documents: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    """
    Generate embeddings for all documents.

    Parameters:
    -----------
    documents : List[Dict[str, str]]
        List of documents with 'text' key.

    Returns:
    --------
    List[Dict[str, Any]]
        List of dicts with 'id', 'values' (embedding), and 'metadata'.
    """
    vectors = []

    print("\n🔄 Generating embeddings...")
    for i, doc in enumerate(documents):
        try:
            result = genai.embed_content(
                model="models/embedding-001",
                content=doc["text"],
                task_type="retrieval_document",
                title=doc["title"],
            )

            vectors.append(
                {
                    "id": doc["filename"],  # Use filename as unique ID
                    "values": result["embedding"],
                    "metadata": {
                        "title": doc["title"],
                        "text": doc["text"][:2000],  # Limit metadata text size
                    },
                }
            )

            progress = ((i + 1) / len(documents)) * 100
            print(f"  [{progress:.1f}%] {doc['filename']}")

        except Exception as e:
            print(f"  ❌ Embedding failed for {doc['filename']}: {e}")

    print(f"\n✅ Generated {len(vectors)} embeddings")
    return vectors


def upload_to_pinecone(
    index: Any,
    vectors: List[Dict[str, Any]],
    batch_size: int = 100,
) -> None:
    """
    Upload vectors to Pinecone in batches.

    Parameters:
    -----------
    index : Any
        Pinecone Index object.
    vectors : List[Dict[str, Any]]
        Vectors with 'id', 'values', 'metadata'.
    batch_size : int
        Number of vectors per batch.
    """
    if not vectors:
        print("[Warning] No vectors to upload.")
        return

    print(f"\n☁️ Uploading {len(vectors)} vectors to Pinecone...")

    for i in range(0, len(vectors), batch_size):
        batch = vectors[i : i + batch_size]
        try:
            index.upsert(vectors=batch)
            print(
                f"  ✅ Batch {i // batch_size + 1}/{(len(vectors) + batch_size - 1) // batch_size} uploaded"
            )
        except Exception as e:
            print(f"  ❌ Batch upload failed: {e}")

    print("\n🎉 All data uploaded successfully!")


def main():
    """
    Main ingestion workflow.
    """
    print("=" * 60)
    print("SmashZettel: Data Ingestion Pipeline")
    print("=" * 60)

    try:
        # Step 1: Initialize APIs
        print("\n1️⃣ Initializing APIs...")
        pc, _ = configure_apis()
        print("   ✅ APIs configured")

        # Step 2: Ensure index exists
        print("\n2️⃣ Ensuring Pinecone index...")
        index = ensure_index_exists(pc, index_name="smash-zettel")
        if not index:
            print("   ❌ Failed to get/create index")
            return

        # Step 3: Load documents
        print("\n3️⃣ Loading documents...")
        documents = load_documents()
        if not documents:
            print("   ❌ No documents to process")
            return

        # Step 4: Embed documents
        print("\n4️⃣ Embedding documents...")
        vectors = embed_documents(documents)
        if not vectors:
            print("   ❌ No embeddings generated")
            return

        # Step 5: Upload to Pinecone
        print("\n5️⃣ Uploading vectors...")
        upload_to_pinecone(index, vectors)

        print("\n" + "=" * 60)
        print("✅ Ingestion complete!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Ingestion failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    main()
