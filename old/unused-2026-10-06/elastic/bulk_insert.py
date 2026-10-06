from elasticsearch.helpers import bulk
from elastic.client import get_client
from elastic.log_generator import generate_log


es = get_client()


INDEX_NAME="application-logs"



logs=[]


for i in range(1000):

    logs.append({

        "_index": INDEX_NAME,

        "_source": generate_log()

    })


bulk(
    es,
    logs
)


print("1000개 로그 적재 완료")