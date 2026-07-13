from client import get_client


INDEX_NAME = "application-logs"


es = get_client()



def create_log_index():

    if es.indices.exists(index=INDEX_NAME):
        print(f"{INDEX_NAME} already exists")
        return


    mapping = {

        "mappings": {

            "properties": {

                "timestamp": {
                    "type": "date"
                },

                "service": {
                    "type": "keyword"
                },

                "level": {
                    "type": "keyword"
                },

                "message": {
                    "type": "text"
                },

                "user_id": {
                    "type": "keyword"
                },

                "request_url": {
                    "type": "keyword"
                },

                "method": {
                    "type": "keyword"
                },

                "error": {
                    "type": "text"
                },

                "host": {
                    "type": "keyword"
                }
            }
        }
    }


    es.indices.create(
        index=INDEX_NAME,
        body=mapping
    )


    print("로그 인덱스 생성 완료")



if __name__ == "__main__":
    create_log_index()