from client import get_client


INDEX_NAME = "application-logs"

es = get_client()



# 전체 로그 조회
def get_all_logs():

    result = es.search(
        index=INDEX_NAME,
        query={
            "match_all": {}
        }
    )

    print("=== 전체 로그 ===")

    for hit in result["hits"]["hits"]:
        print(hit["_source"])




# ERROR 로그 검색
def search_error_logs():

    result = es.search(
        index=INDEX_NAME,
        query={
            "term": {
                "level": "ERROR"
            }
        }
    )


    print("=== ERROR 로그 ===")

    for hit in result["hits"]["hits"]:
        print(hit["_source"])




# 특정 서비스 검색
def search_service(service):

    result = es.search(
        index=INDEX_NAME,
        query={
            "term": {
                "service": service
            }
        }
    )


    print(f"=== {service} 로그 ===")

    for hit in result["hits"]["hits"]:
        print(hit["_source"])




# 키워드 검색
def search_keyword(keyword):

    result = es.search(
        index=INDEX_NAME,
        query={
            "match": {
                "message": keyword
            }
        }
    )


    print(f"=== '{keyword}' 검색 결과 ===")

    for hit in result["hits"]["hits"]:
        print(hit["_source"])





if __name__ == "__main__":

    get_all_logs()

    search_error_logs()

    search_service("auth-service")

    search_keyword("로그인")