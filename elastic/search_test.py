from client import get_client


es = get_client()


result = es.search(
    index="application-logs",
    query={
        "match_all": {}
    }
)


for hit in result["hits"]["hits"]:
    print(hit["_source"])