from client import get_client

def main():
    es = get_client()

    try:
        print(es.info())
        print("Elasticsearch 연결 성공!")
    except Exception as e:
        print("연결 실패")
        print(e)

if __name__ == "__main__":
    main()