"""
Custom DSPy Retriever for Pinecone Vector Database

This module implements a PineconeRetriever class that extends dspy.Retrieve
and integrates with Pinecone v3 for semantic search over SmashBros knowledge.

Role in DSPy Pipeline:
- Student: Acts as the retrieval engine in the coaching pipeline.
- Retriever: Converts free-text queries into vector embeddings and searches
  Pinecone index for relevant documents.
- Responsibility: Providing context to downstream reasoning modules.

Physics/Theory Dependency:
- Uses Google's embedding-001 model for semantic vectorization.
- Preserves exact text content in Pinecone metadata for CoT reasoning.
"""

import os
import dspy
import google.generativeai as genai
from pinecone import Pinecone
from typing import List, Optional


class PineconeRetriever(dspy.Retrieve):
    """
    Custom DSPy Retriever using Pinecone v3 API.

    === DSPy Pipeline Role ===
    
    STUDENT COMPONENT: Acts as the "Knowledge Retrieval Engine" (Student in DSPy terminology).
    - Inherits from dspy.Retrieve base class for pipeline compatibility.
    - forward() returns dspy.Context objects that upstream dspy.Signature modules consume.
    - Signature-compatible: Output shape matches what AnalysisSignature.context expects.
    
    REDEFINABILITY (Core DSPy Principle):
    - All parameters (index_name, top_k, similarity_threshold) are instance attributes.
    - Can be modified at runtime for A/B testing or optimization passes.
    - Supports dspy.Optimizer composition for tuning retrieval behavior.
    
    PIPELINE INTEGRATION:
    - Used by SmashCoach.forward() as upstream of Analysis phase.
    - Retrieved context directly fed into AnalysisSignature input.
    - Enables semantic search decoupling from reasoning logic.

    Parameters:
    -----------
    index_name : str
        Pinecone index name (default: "smash-zettel").
        Redefinable: Can be changed for multi-index strategies.
    
    top_k : int
        Number of results per query (default: 5).
        Tuning dimension: Higher k = more context, higher latency.
    
    similarity_threshold : float
        Minimum cosine similarity (0.0-1.0, default: 0.5).
        Filter dimension: Separates relevant from marginal matches.
    """

    def __init__(
        self,
        index_name: str = "smash-zettel",
        top_k: int = 5,
        similarity_threshold: float = 0.5,
    ):
        """
        Initialize the PineconeRetriever.

        DSPy Context:
        - Called during module initialization.
        - Validates Pinecone and Gemini API availability.
        """
        super().__init__()

        self.index_name = index_name
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold

        # Initialize Pinecone
        api_key = os.getenv("PINECONE_API_KEY")
        if not api_key:
            raise ValueError("PINECONE_API_KEY environment variable not set.")

        self.pc = Pinecone(api_key=api_key)
        self.index = self.pc.Index(self.index_name)

        # Initialize Gemini for embeddings
        genai_key = os.getenv("GEMINI_API_KEY")
        if not genai_key:
            raise ValueError("GEMINI_API_KEY environment variable not set.")

        genai.configure(api_key=genai_key)

    def _embed_query(self, query: str) -> List[float]:
        """
        Convert query text to vector embedding using Google Gemini API.

        DSPy Context:
        - Helper method for forward().
        - Uses "retrieval_query" task type for semantic search optimization.

        Parameters:
        -----------
        query : str
            The search query text.

        Returns:
        --------
        List[float]
            768-dimensional embedding vector.
        """
        try:
            result = genai.embed_content(
                model="models/embedding-001",
                content=query,
                task_type="retrieval_query",
            )
            return result["embedding"]
        except Exception as e:
            raise RuntimeError(f"Embedding generation failed: {e}")

    def forward(self, query: str, k: Optional[int] = None) -> dspy.Retrieve:
        """
        Execute semantic search against Pinecone index.

        DSPy Context:
        - Called by upstream modules (e.g., dspy.ChainOfThought).
        - Returns dspy.Retrieve.Context object with retrieved passages.
        - The returned object is compatible with dspy.Signature input fields.

        Parameters:
        -----------
        query : str
            Search query string.
        k : Optional[int]
            Override top_k for this query.

        Returns:
        --------
        dspy.Retrieve
            Object with .context attribute containing list of retrieved passages.
        """
        k = k or self.top_k

        try:
            # Embed the query
            query_vector = self._embed_query(query)

            # Search Pinecone
            search_results = self.index.query(
                vector=query_vector,
                top_k=k,
                include_metadata=True,
            )

            # Extract and filter results
            passages = []
            for match in search_results.get("matches", []):
                score = match.get("score", 0.0)

                # Apply similarity threshold
                if score < self.similarity_threshold:
                    continue

                metadata = match.get("metadata", {})
                text_content = metadata.get("text", "")
                title = metadata.get("title", "Unknown")

                if text_content:
                    passages.append(
                        {
                            "long_text": text_content,
                            "title": title,
                            "score": score,
                        }
                    )

            # Return DSPy-compatible context
            return dspy.Retrieve.Context(context=passages)

        except Exception as e:
            # Fallback: return empty context
            print(f"[Warning] Pinecone search failed: {e}")
            return dspy.Retrieve.Context(context=[])


def create_retriever(
    index_name: str = "smash-zettel",
    top_k: int = 5,
    threshold: float = 0.5,
) -> PineconeRetriever:
    """
    Factory function to instantiate a PineconeRetriever.

    DSPy Justification:
    - Provides a clean interface for retriever initialization.
    - Encapsulates configuration logic, making the pipeline more readable.

    Parameters:
    -----------
    index_name : str
        Pinecone index name.
    top_k : int
        Number of results to retrieve.
    threshold : float
        Minimum similarity score.

    Returns:
    --------
    PineconeRetriever
        Initialized retriever instance.
    """
    return PineconeRetriever(
        index_name=index_name,
        top_k=top_k,
        similarity_threshold=threshold,
    )
