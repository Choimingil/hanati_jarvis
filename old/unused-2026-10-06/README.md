# 미사용 코드 보관 — 2026-10-06

이 디렉토리는 복구·비교용 기록이며 실행·배포 대상이 아닙니다. 원래 위치에서는 제거했고 Docker 빌드에서도 제외합니다. old까지 다시 삭제하면 보관 목적이 없어지므로 보관본은 유지합니다.

| 보관 위치(원래 경로 유지) | 미사용 구간과 정리 이유 |
|---|---|
| loggenerator_example.py | Compose 대신 subprocess로 생성기를 실행하는 수동 예제 |
| elastic/search_test.py, search_log.py, insert_log.py | 서비스에서 참조하지 않는 수동 ES 조회·입력 예제 |
| elastic/bulk_insert.py, log_generator.py | 별도 1000건 로그 입력과 그 전용 생성기; 현재 시나리오 생성 경로와 분리 |
| llm_agent/app.py, api/, builder/, dto/, model/, services/ai_engine.py | 별도 HTTP LLM Agent 전용 코드. Worker 직접 호출을 선택해 별도 서버 경로를 제거 |
| llm_agent/Dockerfile, requirements.txt | 제거된 독립 LLM Agent 이미지 전용 빌드 파일 |
| reference-snapshots/dependencies.py | 제거 전 원본. 미사용 부분은 RecoveryVerifier import와 recovery_verifier 인스턴스만 해당. 나머지는 활성 코드였음 |
| reference-snapshots/config.py | 제거 전 원본. 미사용 부분은 auto_diagnose/auto_remediate 규칙 속성, 고정 백엔드 상수. 나머지는 활성 설정이었음 |

llm_agent/config.py와 services/llm_service.py는 직접 LLM 호출에 사용하므로 유지합니다. recommendation_ranker.py는 fallback 추천에 사용합니다. aiops/recovery_verifier.py는 테스트되는 자원 비교 기능이므로 클래스는 유지하고 미사용 전역 인스턴스만 제거했습니다. metric_retention.py는 미사용 삭제 대상으로 처리하지 않고 Worker 유지보수 작업에 연결했습니다. list_operational_incidents는 API 경로에 연결했습니다.

reference-snapshots/client_latest_run.js는 제거한 Client의 최신 테스트 시나리오 자동 추종 함수입니다. Client는 실제 incident 목록 선택으로 상세 결과를 표시하도록 변경했습니다.
