"""Lexical and semantic similarity pipeline for Lexis Mollis."""

from .config import SimilarityConfig
from .run import build

__all__ = ["SimilarityConfig", "build"]

