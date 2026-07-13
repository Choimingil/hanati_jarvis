"""Qdrant/Elasticsearch 양쪽에 동일하게 시딩하는 과거 장애 대응 사례 fixture.

`qdrant/seed.py`와 `elastic/seed_cases.py`가 이 목록을 공유해서, 두 백엔드가
같은 "학습 데이터"를 갖도록 한다.
"""

INCIDENT_CASES = [
    {
        "incident_id": "TEST-001",
        "error_code": "DISK_FULL",
        "summary": "로그 파일 증가로 디스크 부족",
        "root_cause": "오래된 로그 미정리",
        "resolution": "오래된 로그 압축",
    },
    {
        "incident_id": "TEST-002",
        "error_code": "DISK_FULL",
        "summary": "업로드 디렉토리 용량 초과로 디스크 풀",
        "root_cause": "대용량 업로드 파일 미삭제",
        "resolution": "오래된 업로드 파일 정리 및 보관 정책 적용",
    },
    {
        "incident_id": "TEST-003",
        "error_code": "ORA-28040",
        "summary": "JDBC 드라이버 버전 불일치로 인증 실패",
        "root_cause": "구버전 JDBC 드라이버 사용",
        "resolution": "JDBC 드라이버 최신 버전으로 업데이트",
    },
    {
        "incident_id": "TEST-004",
        "error_code": "ORA-28040",
        "summary": "sqlnet.ora 설정 오류로 접속 거부",
        "root_cause": "SQLNET.ALLOWED_LOGON_VERSION_SERVER 설정 누락",
        "resolution": "sqlnet.ora 설정 수정 후 리스너 재기동",
    },
]
