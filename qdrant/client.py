from functools import lru_cache

from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

from config import (
    EMBEDDING_MODEL_NAME,
    QDRANT_URL,
)


@lru_cache(maxsize=1)
def get_client() -> QdrantClient:
    if not QDRANT_URL:
        raise RuntimeError(
            "QDRANT_URL not set - Qdrant server required, no local fallback"
        )

    return QdrantClient(url=QDRANT_URL)


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def encode(text: str) -> list[float]:
    return get_embedding_model().encode(text).tolist()
