# 검증 안내

변경 검증은 외부 서비스나 모델을 시작하지 않는 단위 검사로 수행합니다. `tests/test_phase_one.py`는 fake Redis와 fake Docker backend를 사용해 대상 결합, 사전 검증, 승인·중복 실행, 응답 유실, 상태 복원 실패, 복구 확인, 마스킹과 큐 처리를 검증합니다. 실제 호스트 명령을 실행하지 않습니다.

현재 AIOps 이미지를 사용하는 검사 예시:

```sh
docker compose run --rm --no-deps aiops sh -c 'pip install "fakeredis[lua]" && python -m unittest discover -s tests -q'
```

실제 Docker 재시작·이미지 권한·이중화·네트워크·복구 probe는 격리된 개발 Compose 환경에서 별도로 검증해야 합니다. 이 저장소의 기본 단일 인스턴스에서 재시작이 차단되는 것은 의도한 동작입니다. 전체 스택 초기화나 장시간 모델 다운로드를 단위 검사에 포함하지 않습니다.
