from elasticsearch import Elasticsearch

def get_client():
    return Elasticsearch(
        "https://localhost:9200",
        basic_auth=("elastic", "lcv8R4B0ZlJ3MbQgyg8J"),
        verify_certs=False
    )