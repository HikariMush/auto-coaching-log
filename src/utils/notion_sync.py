"""
Notion → Pinecone Sync Pipeline

This module periodically syncs Theory pages from Notion database to Pinecone.

DSPy Context:
- Not part of DSPy reasoning pipeline.
- Enables data pipeline orchestration for knowledge base updates.
- Supports automatic reindexing when Theory DB is updated.

Design Philosophy:
- Decoupled from reasoning logic (single-responsibility principle).
- Scheduled job that can run independently (e.g., via Cloud Tasks).
- Maintains sync state to avoid duplicate embeddings.
"""

import os
import json
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

import requests
from google import genai
from pinecone import Pinecone

# Configuration
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
THEORY_DB_ID = os.getenv("THEORY_DB_ID", "2e21bc8521e38029b8b1d5c4b49731eb")
PINECONE_INDEX_NAME = "smash-zettel"

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


def fetch_theory_pages() -> List[Dict[str, Any]]:
    """
    Fetch all Theory pages from Notion database.

    DSPy Context:
    - Helper for data pipeline orchestration.
    - Retrieves structured knowledge from Notion (source of truth).

    Returns:
    --------
    List[Dict[str, Any]]
        List of pages with id, title, and content.
    """
    if not NOTION_TOKEN:
        raise ValueError("NOTION_TOKEN environment variable not set.")

    url = f"https://api.notion.com/v1/databases/{THEORY_DB_ID}/query"
    pages = []
    start_cursor = None

    while True:
        payload = {"page_size": 100}
        if start_cursor:
            payload["start_cursor"] = start_cursor

        try:
            response = requests.post(url, headers=NOTION_HEADERS, json=payload)
            response.raise_for_status()
            data = response.json()

            for page in data.get("results", []):
                page_id = page["id"]
                properties = page.get("properties", {})

                # Extract title (theory name)
                title_prop = properties.get("Theory Name", {})
                title_values = title_prop.get("title", [])
                title = (
                    title_values[0]["text"]["content"]
                    if title_values
                    else f"Theory_{page_id[:8]}"
                )

                pages.append(
                    {
                        "id": page_id,
                        "title": title,
                        "url": page.get("url"),
                    }
                )

            # Pagination
            if not data.get("has_more"):
                break

            start_cursor = data.get("next_cursor")

        except Exception as e:
            print(f"[Error] Failed to fetch Notion pages: {e}")
            break

    return pages


def fetch_page_content(page_id: str) -> str:
    """
    Fetch full content (blocks) of a Notion page.

    Parameters:
    -----------
    page_id : str
        Notion page ID.

    Returns:
    --------
    str
        Concatenated text content of all blocks.
    """
    url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"
    full_text = ""
    start_cursor = None

    while True:
        params = {}
        if start_cursor:
            params["start_cursor"] = start_cursor

        try:
            response = requests.get(url, headers=NOTION_HEADERS, params=params)
            response.raise_for_status()
            data = response.json()

            for block in data.get("results", []):
                block_type = block.get("type")
                block_data = block.get(block_type, {})

                if "rich_text" in block_data:
                    text_list = block_data["rich_text"]
                    line = "".join(
                        [t.get("text", {}).get("content", "") for t in text_list]
                    )
                    if line:
                        full_text += line + "\n"

            if not data.get("has_more"):
                break

            start_cursor = data.get("next_cursor")

        except Exception as e:
            print(f"[Warning] Failed to fetch page content {page_id}: {e}")
            break

    return full_text


def embed_and_upsert(pages: List[Dict[str, Any]]) -> int:
    """
    Embed Theory pages using Gemini and upsert to Pinecone.

    DSPy Context:
    - Prepares knowledge for downstream retriever.
    - Uses embedding-001 (same as Retriever for consistency).

    Parameters:
    -----------
    pages : List[Dict[str, Any]]
        List of pages to embed.

    Returns:
    --------
    int
        Number of successfully upserted pages.
    """
    if not pages:
        return 0

    # Initialize
    genai_key = os.getenv("GEMINI_API_KEY")
    if not genai_key:
        raise ValueError("GEMINI_API_KEY not set.")

    genai.configure(api_key=genai_key)

    pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
    index = pc.Index(PINECONE_INDEX_NAME)

    vectors = []
    successful = 0

    print(f"🔄 Processing {len(pages)} Theory pages...")

    for i, page in enumerate(pages):
        try:
            page_id = page["id"]
            title = page["title"]

            # Fetch full content
            content = fetch_page_content(page_id)

            if not content.strip():
                print(f"  ⚠️  {title}: No content")
                continue

            # Embed
            result = genai.embed_content(
                model="models/embedding-001",
                content=content,
                task_type="retrieval_document",
                title=title,
            )

            vectors.append(
                {
                    "id": f"notion_{page_id}",
                    "values": result["embedding"],
                    "metadata": {
                        "source": "notion",
                        "title": title,
                        "page_id": page_id,
                        "url": page.get("url"),
                        "text": content[:2000],  # Limit metadata
                        "synced_at": datetime.utcnow().isoformat(),
                    },
                }
            )

            progress = ((i + 1) / len(pages)) * 100
            print(f"  [{progress:.1f}%] ✅ {title}")
            successful += 1

        except Exception as e:
            print(f"  ❌ {title}: {e}")

    # Upsert in batches
    if vectors:
        print(f"\n☁️ Upserting {len(vectors)} vectors to Pinecone...")
        batch_size = 50
        for j in range(0, len(vectors), batch_size):
            batch = vectors[j : j + batch_size]
            try:
                index.upsert(vectors=batch)
                print(
                    f"  ✅ Batch {j // batch_size + 1}/{(len(vectors) + batch_size - 1) // batch_size}"
                )
            except Exception as e:
                print(f"  ❌ Batch upsert failed: {e}")

    return successful


def sync_notion_to_pinecone(verbose: bool = True) -> Dict[str, Any]:
    """
    Main sync function: Notion Theory DB → Pinecone.

    DSPy Context:
    - Orchestrator for knowledge base synchronization.
    - Can be called on-demand or scheduled (e.g., hourly via Cloud Tasks).

    Parameters:
    -----------
    verbose : bool
        Print progress messages.

    Returns:
    --------
    Dict[str, Any]
        Sync result metadata.
    """
    result = {
        "status": "pending",
        "timestamp": datetime.utcnow().isoformat(),
        "pages_fetched": 0,
        "pages_synced": 0,
        "errors": [],
    }

    try:
        if verbose:
            print("=" * 60)
            print("🔗 Notion → Pinecone Sync")
            print("=" * 60)

        # Fetch pages
        if verbose:
            print("\n1️⃣ Fetching Notion pages...")
        pages = fetch_theory_pages()
        result["pages_fetched"] = len(pages)

        if verbose:
            print(f"   Found {len(pages)} pages")

        # Embed and upsert
        if verbose:
            print("\n2️⃣ Embedding and upserting to Pinecone...")
        synced = embed_and_upsert(pages)
        result["pages_synced"] = synced

        result["status"] = "success"

        if verbose:
            print("\n" + "=" * 60)
            print(f"✅ Sync complete: {synced}/{len(pages)} pages synchronized")
            print("=" * 60)

    except Exception as e:
        result["status"] = "failed"
        result["errors"] = [str(e)]
        if verbose:
            print(f"\n❌ Sync failed: {e}")

    return result


def main():
    """
    Entry point for manual sync execution.
    """
    sync_notion_to_pinecone(verbose=True)


if __name__ == "__main__":
    main()
