# 검증 안내

변경 검증은 외부 서비스나 모델을 시작하지 않는 단위 검사로 수행합니다. `tests/test_phase_one.py`는 fake Redis와 fake Docker backend를 사용해 대상 결합, 사전 검증, 승인·중복 실행, 응답 유실, 상태 복원 실패, 복구 확인, 마스킹과 큐 처리를 검증합니다. 실제 호스트 명령을 실행하지 않습니다.

현재 AIOps 이미지를 사용하는 검사 예시:

```sh
docker compose run --rm --no-deps aiops sh -c 'pip install "fakeredis[lua]" && python -m unittest discover -s tests -q'
```

실제 Docker 재시작·이미지 권한·이중화·네트워크·복구 probe는 격리된 개발 Compose 환경에서 별도로 검증해야 합니다. 이 저장소의 기본 단일 인스턴스에서 재시작이 차단되는 것은 의도한 동작입니다. 전체 스택 초기화나 장시간 모델 다운로드를 단위 검사에 포함하지 않습니다.

업무 개선 1~4번 검사:

- `tests/test_business_operations.py`: 업무 우선순위, 반복 장애의 분석 재사용과 승인 버전 유지, 영향 상승·새 호스트·재발, 기동 검사 OOM, 읽기 전용 업무 지표의 신선도·거래 표본·잘못된 업무·리다이렉트 차단
- 실제 서버의 짧은 기동/부하 명령은 OPERATIONS.md 참고. 결과를 측정하기 전에는 처리량이나 기동 성공을 보장하지 않습니다.

실제 구성 요소 전달 경로 검사(기존 이미지 사용):

```sh
docker compose --profile verification run --rm deployment-check python -m operations.integration_check --wait-seconds 20
```

검사 범위: API→Redis→Worker→Elasticsearch, 공유 로그→Fluent Bit→API→Worker→Elasticsearch, Qdrant 컬렉션·384차원 저장 벡터·필터 검색, 최근 메트릭 접수, LLM Agent health. INFO 표식 두 건을 남기며 오류 분석·조치·업무 거래는 실행하지 않습니다. Fluent Bit의 파일 발견을 기다린 뒤 표식을 쓰고 경로별 제한 시간 내 도착을 확인합니다. 검사 컨테이너에 기존 로그 volume을 연결합니다. 기본 Fluent Bit 설정은 로그를 stdout에도 출력합니다.

이 검사는 모델 임베딩 추론이나 외부 LLM 생성의 정상 여부까지 보장하지 않습니다. Qdrant 검색은 이미 저장된 실제 벡터를 재사용합니다. 실제 Docker 실행 환경에서 위 명령을 수행해야 연동을 검증했다고 말할 수 있습니다. 초기화·수집 모듈이 공통 config를 import하므로 elastic/collector/qdrant 각 requirements에 python-dotenv를 명시합니다.
