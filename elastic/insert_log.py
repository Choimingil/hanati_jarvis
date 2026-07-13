from elastic.client import get_client
from datetime import datetime


INDEX_NAME = "application-logs"


es = get_client()



def insert_log(log):

    response = es.index(
        index=INDEX_NAME,
        document=log
    )

    print("로그 저장 완료")
    print("ID:", response["_id"])




if __name__ == "__main__":


    log_data = {

        "timestamp": datetime.now(),

        "service": "auth-service",

        "level": "ERROR",

        "message": "로그인 실패",

        "user_id": "user123",

        "request_url": "/login",

        "method": "POST",

        "error": "Invalid password",

        "host": "server01"

    }


    insert_log(log_data)