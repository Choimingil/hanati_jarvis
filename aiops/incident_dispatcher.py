"""장애 분석을 비동기로 실행하고, 같은 장애 그룹은 하나로 묶는 디스패처.

`LogProcessor.submit()`은 로그를 정규화·집계(=incident 접수)만 마친 뒤 무거운
분석(진단 스크립트 실행 + 과거 사례 검색 + LLM 추천 생성)을 이 디스패처에
위임한다. 디스패처는 다음 두 가지를 보장한다.

1. **비동기** — 접수 스레드(HTTP 요청 스레드)를 막지 않고, 별도 워커 스레드
   풀에서 분석을 실행한다.
2. **그룹 묶음(coalescing)** — 같은 장애 그룹(`incident_id`)에 대한 분석 요청이
   짧은 시간에 여러 번 들어오면 개별로 다 돌리지 않고 하나의 분석으로 묶는다.
   대기 중이거나 처리 중인 그룹에 새 로그가 유입되면 최신 컨텍스트만 남기고
   중복 분석은 생략하되, 처리 도중 새로 유입된 건이 있으면 끝난 뒤 한 번 더
   돌려 최종 집계 상태를 반영한다.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable


logger = logging.getLogger(__name__)

# 워커 스레드에게 종료를 알리는 센티널.
_SHUTDOWN = object()


class IncidentAnalysisDispatcher:

    def __init__(
        self,
        worker: Callable[[dict[str, Any]], Any],
        max_workers: int = 2,
    ) -> None:
        self._worker = worker
        self._queue: queue.Queue = queue.Queue()
        # incident_id -> 아직 실행되지 않았거나(대기), 처리 중 새로 유입돼
        # 재실행이 필요한 최신 job.
        self._pending: dict[str, dict[str, Any]] = {}
        # 현재 워커가 처리 중인 incident_id 집합.
        self._inflight: set[str] = set()
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []

        for index in range(max(1, max_workers)):
            thread = threading.Thread(
                target=self._run,
                name=f"incident-analysis-{index}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def submit(self, job: dict[str, Any]) -> str:
        """분석 job을 접수한다.

        같은 `incident_id`가 이미 대기/처리 중이면 최신 컨텍스트로 묶고
        ``"coalesced"``를, 새 그룹이면 큐에 넣고 ``"queued"``를 반환한다.
        """
        incident_id = job["incident_id"]
        with self._lock:
            already_pending = incident_id in self._pending
            already_inflight = incident_id in self._inflight
            # 항상 최신 job을 남긴다(가장 최근 대표 메시지/에러코드 반영).
            self._pending[incident_id] = job
            if not already_pending and not already_inflight:
                self._queue.put(incident_id)
                return "queued"
            return "coalesced"

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _SHUTDOWN:
                    return
                self._process(item)
            finally:
                self._queue.task_done()

    def _process(self, incident_id: str) -> None:
        with self._lock:
            job = self._pending.pop(incident_id, None)
            if job is None:
                return
            self._inflight.add(incident_id)
        try:
            self._worker(job)
        except Exception:  # noqa: BLE001 - 워커 실패가 스레드를 죽이면 안 된다.
            logger.exception(
                "incident analysis failed: %s", incident_id
            )
        finally:
            with self._lock:
                self._inflight.discard(incident_id)
                # 처리 중 같은 그룹이 새로 유입돼 pending에 다시 쌓였으면
                # 최종 상태 반영을 위해 한 번 더 실행한다.
                if incident_id in self._pending:
                    self._queue.put(incident_id)

    def join(self, timeout: float | None = None) -> None:
        """대기 중인 모든 분석이 끝날 때까지 블록한다(주로 테스트용)."""
        if timeout is None:
            self._queue.join()
            return
        # Queue.join()은 timeout을 지원하지 않으므로 unfinished 카운트를
        # 직접 폴링한다.
        import time

        deadline = time.monotonic() + timeout
        while self._queue.unfinished_tasks:
            if time.monotonic() >= deadline:
                raise TimeoutError("dispatcher did not drain in time")
            time.sleep(0.005)

    def shutdown(self) -> None:
        """워커 스레드를 정리한다(주로 테스트용)."""
        for _ in self._threads:
            self._queue.put(_SHUTDOWN)
        for thread in self._threads:
            thread.join(timeout=1)
