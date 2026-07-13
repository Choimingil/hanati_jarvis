from functools import lru_cache

from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

from config import (
    EMBEDDING_MODEL_NAME,
    QDRANT_PATH,
    QDRANT_URL,
)


@lru_cache(maxsize=1)
def get_client() -> QdrantClient:
    if QDRANT_URL:
        return QdrantClient(url=QDRANT_URL)

    return QdrantClient(path=QDRANT_PATH)


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def encode(text: str) -> list[float]:
    return get_embedding_model().encode(text).tolist()
