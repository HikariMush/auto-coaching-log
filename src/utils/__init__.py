"""
SmashZettel Utilities

Utility modules for data ingestion, database management, and analysis.

MODULES:
- ingest: Raw data vectorization and Pinecone upload (DSPy-aware).
- notion_sync: Notion Theory DB → Pinecone synchronization pipeline.
- analyze_raw_data: Quality analysis and gap identification for knowledge base.

DSPy Context:
- These are not DSPy reasoning components themselves.
- They support the DSPy pipeline by preparing and maintaining knowledge stores.
- Enable data orchestration and monitoring.
"""

from . import ingest
from . import notion_sync
from . import analyze_raw_data

__all__ = ["ingest", "notion_sync", "analyze_raw_data"]

