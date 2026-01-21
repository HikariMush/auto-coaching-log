"""
SmashZettel Brain Module

Core AI coaching logic and knowledge retrieval.
"""

from .model import SmashCoach, create_coach
from .retriever import PineconeRetriever, create_retriever

__all__ = ["SmashCoach", "create_coach", "PineconeRetriever", "create_retriever"]
