from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct

from sentence_transformers import SentenceTransformer


model = SentenceTransformer(
    "BAAI/bge-m3"
)

# client = QdrantClient(
#     path="./qdrant_data"
# )
# Docker 없이 코드 내에서 인메모리로 실행할 때
client = QdrantClient(":memory:")


logs = [
    "2026-07-13 08:00:01 INFO 192.168.0.10 GET /index.html 200",
    "2026-07-13 08:00:05 INFO 192.168.0.15 GET /login 200",
    "2026-07-13 08:00:08 INFO 192.168.0.15 POST /login 200 user=alice",
    "2026-07-13 08:00:11 INFO 192.168.0.21 GET /products 200",
    "2026-07-13 08:00:15 INFO 192.168.0.21 GET /products/101 200",
    "2026-07-13 08:00:18 INFO 192.168.0.21 GET /products/102 200",
    "2026-07-13 08:00:21 INFO 192.168.0.30 GET /products/103 200",
    "2026-07-13 08:00:25 WARN 192.168.0.44 GET /admin 403 Forbidden",
    "2026-07-13 08:00:28 INFO 192.168.0.18 GET /search?q=laptop 200",
    "2026-07-13 08:00:31 INFO 192.168.0.15 GET /cart 200",
    "2026-07-13 08:00:35 INFO 192.168.0.15 POST /checkout 200 order=54021",
    "2026-07-13 08:00:39 ERROR 192.168.0.55 GET /favicon.ico 404 Not Found",
    "2026-07-13 08:00:42 INFO 192.168.0.61 GET /api/products 200",
    "2026-07-13 08:00:46 INFO 192.168.0.61 GET /api/users 200",
    "2026-07-13 08:00:50 ERROR 192.168.0.61 POST /api/payment 500 Internal Server Error",
    "2026-07-13 08:00:55 INFO 192.168.0.91 GET /about 200",
    "2026-07-13 08:01:00 INFO 192.168.0.32 GET /contact 200",
    "2026-07-13 08:01:05 INFO 192.168.0.45 POST /feedback 201 Created",
    "2026-07-13 08:01:09 ERROR 192.168.0.53 GET /database/status 503 Service Unavailable",
    "2026-07-13 08:01:13 INFO 192.168.0.15 GET /logout 200",
    "2026-07-13 08:01:17 INFO 192.168.0.25 GET /news 200",
    "2026-07-13 08:01:20 INFO 192.168.0.26 GET /notice 200",
    "2026-07-13 08:01:23 INFO 192.168.0.27 GET /profile 200",
    "2026-07-13 08:01:27 WARN 192.168.0.90 GET /config.php 404 Not Found",
    "2026-07-13 08:01:31 INFO 192.168.0.70 GET /api/orders 200",
    "2026-07-13 08:01:35 INFO 192.168.0.71 GET /api/order/1001 200",
    "2026-07-13 08:01:40 INFO 192.168.0.72 GET /api/order/1002 200",
    "2026-07-13 08:01:45 ERROR 192.168.0.73 POST /api/order 500 Database Timeout",
    "2026-07-13 08:01:50 INFO 192.168.0.74 GET /images/logo.png 200",
    "2026-07-13 08:01:55 INFO 192.168.0.75 GET /css/style.css 200",
    "2026-07-13 08:02:00 INFO 192.168.0.76 GET /js/app.js 200",
    "2026-07-13 08:02:05 WARN 192.168.0.77 GET /.env 403 Forbidden",
    "2026-07-13 08:02:10 INFO 192.168.0.78 GET /download/manual.pdf 200",
    "2026-07-13 08:02:15 INFO 192.168.0.79 POST /upload 201",
    "2026-07-13 08:02:20 ERROR 192.168.0.80 POST /upload 500 Disk Full",
    "2026-07-13 08:02:25 INFO 192.168.0.81 GET /faq 200",
    "2026-07-13 08:02:30 INFO 192.168.0.82 GET /event 200",
    "2026-07-13 08:02:35 INFO 192.168.0.83 GET /coupon 200",
    "2026-07-13 08:02:40 INFO 192.168.0.84 GET /mypage 200",
    "2026-07-13 08:02:45 WARN 192.168.0.85 GET /backup.zip 404 Not Found",
    "2026-07-13 08:02:50 INFO 192.168.0.86 GET /api/recommend 200",
    "2026-07-13 08:02:55 INFO 192.168.0.87 GET /api/history 200",
    "2026-07-13 08:03:00 ERROR 192.168.0.88 GET /api/report 502 Bad Gateway",
    "2026-07-13 08:03:05 INFO 192.168.0.89 GET /search?q=iphone 200",
    "2026-07-13 08:03:10 INFO 192.168.0.90 GET /search?q=galaxy 200",
    "2026-07-13 08:03:15 INFO 192.168.0.91 GET /search?q=tablet 200",
    "2026-07-13 08:03:20 INFO 192.168.0.92 GET /search?q=headphone 200",
    "2026-07-13 08:03:25 INFO 192.168.0.93 POST /login 401 Unauthorized",
    "2026-07-13 08:03:30 INFO 192.168.0.94 POST /login 200 user=bob",
    "2026-07-13 08:03:35 INFO 192.168.0.95 POST /login 200 user=charlie",
    "2026-07-13 08:03:40 INFO 192.168.0.96 GET /orders 200",
    "2026-07-13 08:03:45 INFO 192.168.0.97 GET /orders/54021 200",
    "2026-07-13 08:03:50 INFO 192.168.0.98 POST /payment 200",
    "2026-07-13 08:03:55 ERROR 192.168.0.99 POST /payment 500 Payment Gateway Error",
    "2026-07-13 08:04:00 INFO 192.168.0.101 GET /logout 200",
    "2026-07-13 08:04:05 INFO 192.168.0.102 GET /health 200",
    "2026-07-13 08:04:10 INFO 192.168.0.103 GET /metrics 200",
    "2026-07-13 08:04:15 WARN 192.168.0.104 GET /phpmyadmin 403 Forbidden",
    "2026-07-13 08:04:20 INFO 192.168.0.105 GET /dashboard 200",
    "2026-07-13 08:04:25 INFO 192.168.0.106 GET /sales 200",
    "2026-07-13 08:04:30 INFO 192.168.0.107 GET /inventory 200",
    "2026-07-13 08:04:35 ERROR 192.168.0.108 GET /inventory 500 Database Error",
    "2026-07-13 08:04:40 INFO 192.168.0.109 GET /api/inventory 200",
    "2026-07-13 08:04:45 INFO 192.168.0.110 GET /api/customer 200",
    "2026-07-13 08:04:50 INFO 192.168.0.111 GET /customer/100 200",
    "2026-07-13 08:04:55 INFO 192.168.0.112 GET /customer/101 200",
    "2026-07-13 08:05:00 WARN 192.168.0.113 GET /tmp/test.txt 404 Not Found",
    "2026-07-13 08:05:05 INFO 192.168.0.114 POST /api/message 201",
    "2026-07-13 08:05:10 INFO 192.168.0.115 GET /api/message 200",
    "2026-07-13 08:05:15 ERROR 192.168.0.116 GET /api/analytics 504 Gateway Timeout",
    "2026-07-13 08:05:20 INFO 192.168.0.117 GET /analytics 200",
    "2026-07-13 08:05:25 INFO 192.168.0.118 GET /settings 200",
    "2026-07-13 08:05:30 INFO 192.168.0.119 POST /settings 200",
    "2026-07-13 08:05:35 WARN 192.168.0.120 GET /server-status 403 Forbidden",
    "2026-07-13 08:05:40 INFO 192.168.0.121 GET /blog 200",
    "2026-07-13 08:05:45 INFO 192.168.0.122 GET /blog/1 200",
    "2026-07-13 08:05:50 INFO 192.168.0.123 GET /blog/2 200",
    "2026-07-13 08:05:55 INFO 192.168.0.124 GET /blog/3 200",
    "2026-07-13 08:06:00 ERROR 192.168.0.125 POST /api/blog 500 Write Failed",
    "2026-07-13 08:06:05 INFO 192.168.0.126 GET /support 200",
    "2026-07-13 08:06:10 INFO 192.168.0.127 GET /support/ticket/1 200",
    "2026-07-13 08:06:15 INFO 192.168.0.128 POST /support/ticket 201",
    "2026-07-13 08:06:20 INFO 192.168.0.129 GET /api/logs 200",
    "2026-07-13 08:06:25 INFO 192.168.0.130 GET /robots.txt 200",
    "2026-07-13 08:06:30 WARN 192.168.0.131 GET /.git/config 403 Forbidden",
    "2026-07-13 08:06:35 INFO 192.168.0.132 GET /rss.xml 200",
    "2026-07-13 08:06:40 INFO 192.168.0.133 GET /sitemap.xml 200",
    "2026-07-13 08:06:45 INFO 192.168.0.134 GET /docs/api 200",
    "2026-07-13 08:06:50 ERROR 192.168.0.135 GET /docs/private 401 Unauthorized",
    "2026-07-13 08:06:55 INFO 192.168.0.136 GET /home 200",
    "2026-07-13 08:07:00 INFO 192.168.0.137 GET /home/news 200",
    "2026-07-13 08:07:05 INFO 192.168.0.138 GET /home/event 200",
    "2026-07-13 08:07:10 INFO 192.168.0.139 POST /register 201 user=david",
    "2026-07-13 08:07:15 INFO 192.168.0.140 POST /register 201 user=emma",
    "2026-07-13 08:07:20 INFO 192.168.0.141 GET /welcome 200",
    "2026-07-13 08:07:25 ERROR 192.168.0.142 GET /api/export 500 Export Failed",
    "2026-07-13 08:07:30 INFO 192.168.0.143 GET /logout 200",
    # 정상 서비스 로그
    "2026-07-13 09:10:01 INFO 192.168.1.10 GET /home 200",
    "2026-07-13 09:10:05 INFO 192.168.1.11 GET /products 200",
    "2026-07-13 09:10:10 INFO 192.168.1.12 GET /products/101 200",
    "2026-07-13 09:10:15 INFO 192.168.1.13 POST /login 200 user=kim",
    "2026-07-13 09:10:20 INFO 192.168.1.14 GET /dashboard 200",
    "2026-07-13 09:10:25 INFO 192.168.1.15 GET /api/users 200",
    "2026-07-13 09:10:30 INFO 192.168.1.16 POST /cart 201",
    "2026-07-13 09:10:35 INFO 192.168.1.17 POST /order 201 order=10001",
    "2026-07-13 09:10:40 INFO 192.168.1.18 GET /payment/history 200",
    "2026-07-13 09:10:45 INFO 192.168.1.19 GET /notice 200",

    # Database 오류
    "2026-07-13 09:11:01 ERROR 192.168.1.20 POST /api/payment 500 Database Connection Failed",
    "2026-07-13 09:11:05 ERROR 192.168.1.21 GET /api/users 500 Database Timeout",
    "2026-07-13 09:11:10 ERROR 192.168.1.22 POST /api/order 500 Deadlock Detected",
    "2026-07-13 09:11:15 ERROR 192.168.1.23 GET /api/report 503 Database Service Unavailable",

    # 인증 오류
    "2026-07-13 09:12:01 WARN 192.168.1.30 POST /login 401 Invalid Password",
    "2026-07-13 09:12:05 ERROR 192.168.1.31 POST /login 403 Account Locked",
    "2026-07-13 09:12:10 WARN 192.168.1.32 GET /admin 403 Access Denied",

    # API 오류
    "2026-07-13 09:13:01 ERROR 192.168.1.40 GET /api/payment 502 Bad Gateway",
    "2026-07-13 09:13:05 ERROR 192.168.1.41 POST /api/order 500 Internal Server Error",
    "2026-07-13 09:13:10 ERROR 192.168.1.42 GET /api/search 504 Gateway Timeout",

    # 네트워크 오류
    "2026-07-13 09:14:01 ERROR 192.168.1.50 GET /external/payment 504 Connection Timeout",
    "2026-07-13 09:14:05 ERROR 192.168.1.51 POST /external/api 502 Connection Refused",
    "2026-07-13 09:14:10 WARN 192.168.1.52 GET /health 408 Request Timeout",

    # 파일 오류
    "2026-07-13 09:15:01 ERROR 192.168.1.60 POST /upload 500 Disk Full",
    "2026-07-13 09:15:05 ERROR 192.168.1.61 GET /backup.zip 404 File Not Found",
    "2026-07-13 09:15:10 ERROR 192.168.1.62 POST /backup 500 Permission Denied",

    # 서버 리소스 오류
    "2026-07-13 09:16:01 ERROR 192.168.1.70 GET /health 503 Server Overloaded",
    "2026-07-13 09:16:05 ERROR 192.168.1.71 GET /api/data 500 Out Of Memory",
    "2026-07-13 09:16:10 WARN 192.168.1.72 GET /metrics 200 High Memory Usage",

    # Redis / Cache
    "2026-07-13 09:17:01 ERROR 192.168.1.80 GET /cache/user 500 Redis Connection Failed",
    "2026-07-13 09:17:05 ERROR 192.168.1.81 GET /cache/product 500 Redis Timeout",
    "2026-07-13 09:17:10 INFO 192.168.1.82 GET /cache/product 200 Cache Hit",

    # Message Queue
    "2026-07-13 09:18:01 ERROR 192.168.1.90 POST /queue/order 500 Kafka Connection Failed",
    "2026-07-13 09:18:05 ERROR 192.168.1.91 POST /queue/payment 500 Message Queue Timeout",
    "2026-07-13 09:18:10 INFO 192.168.1.92 GET /queue/status 200",

    # 보안 이벤트
    "2026-07-13 09:19:01 WARN 192.168.1.100 GET /.env 403 Forbidden",
    "2026-07-13 09:19:05 WARN 192.168.1.101 GET /.git/config 403 Forbidden",
    "2026-07-13 09:19:10 ERROR 192.168.1.102 POST /login 429 Too Many Requests",

    # 애플리케이션 오류
    "2026-07-13 09:20:01 ERROR 192.168.1.110 POST /checkout 500 Null Pointer Exception",
    "2026-07-13 09:20:05 ERROR 192.168.1.111 GET /dashboard 500 Application Crash",
    "2026-07-13 09:20:10 ERROR 192.168.1.112 POST /register 500 Validation Failed",

    # 정상 복구 로그
    "2026-07-13 09:21:01 INFO 192.168.1.120 GET /health 200 Service Recovery",
    "2026-07-13 09:21:05 INFO 192.168.1.121 GET /api/payment 200 Payment Service Normal",
    "2026-07-13 09:21:10 INFO 192.168.1.122 GET /database/status 200 Database Connected"
]

import re

pattern = r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) (\w+) ([\d.]+) (\w+) (\S+) (\d+) ?(.*)"

payloads = []

for log in logs:

    m = re.match(pattern, log)

    if m:
        date, time, level, ip, method, url, status, message = m.groups()

        payload = {
            "date": date,
            "time": time,
            "level": level,
            "ip": ip,
            "method": method,
            "url": url,
            "status": int(status),
            "message": message,
            "raw_log": log
        }

        payload["description"] = (
            f"{url} 서비스에서 "
            f"{method} 요청을 처리하였다. "
            f"HTTP 상태 코드는 {status}이며 "
            f"{message if message else '정상 처리'} "
            f"상황이다. "
            f"로그 레벨은 {level}이다."
        )

        payloads.append(payload)
        # print(payload)
    else:
        print("파싱 실패:", log)



points = []

for idx, p in enumerate(payloads):

    vector = model.encode(
        p["description"]
    )

    points.append(
        PointStruct(
            id=idx,
            vector=vector.tolist(),
            payload={
                "description": p["description"],
                "raw_log": p["raw_log"],
                "level": p["level"],
                "status": p["status"],
                "url": p["url"]
            }
        )
    )


# client.create_collection(
#     collection_name="server_log",
#     vectors_config=VectorParams(
#         size=384,
#         distance=Distance.COSINE
#     )
# )

client.delete_collection(
    collection_name="server_log"
)

from qdrant_client.models import VectorParams, Distance

#"paraphrase-multilingual-MiniLM-L12-v2" 모델은 size=768
# client.create_collection(
#     collection_name="server_log",
#     vectors_config=VectorParams(
#         size=768,
#         distance=Distance.COSINE
#     )
# )

# "BAAI/bge-m3" 모델 사이즈 1024
client.create_collection(
    collection_name="server_log",
    vectors_config=VectorParams(
        size=1024,
        distance=Distance.COSINE
    )
)

client.upload_points(
    collection_name="server_log",
    points=points
)


query = "로그인 오류"

query_vector = model.encode(query)


results = client.query_points(
    collection_name="server_log",
    query=query_vector,
    limit=10
).points


for r in results:
    print(r.payload["description"])
    print(r.score)
    print(r.payload["raw_log"])
    print()