from functools import lru_cache
from elasticsearch import Elasticsearch

from config import (
    ELASTICSEARCH_PASSWORD,
    ELASTICSEARCH_URL,
    ELASTICSEARCH_USER,
    ELASTICSEARCH_VERIFY_CERTS,
)


@lru_cache(maxsize=1)
def get_client():
    return Elasticsearch(
        ELASTICSEARCH_URL,
        basic_auth=(
            ELASTICSEARCH_USER,
            ELASTICSEARCH_PASSWORD,
        ),
        verify_certs=ELASTICSEARCH_VERIFY_CERTS,
    )
