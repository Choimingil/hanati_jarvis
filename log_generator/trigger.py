"""웹 콘솔의 "분석" 버튼이 호출하는 진입점.

main.py는 무한 루프로 시나리오를 랜덤 발생시키지만, 여기서는 지정된
시나리오 하나만 확정적으로(probability=1.0) 즉시 1회 실행해서 main.py와
동일한 방식으로 fluentbit가 tail하는 파일에 쓴다. 이후 흐름(탐지/진단/
추천)은 main.py를 직접 실행했을 때와 완전히 동일하다 — fluent-bit가
tail해서 백엔드로 전달한다.
"""

from pathlib import Path

from logger.file_writer import FileWriter
from logger.json_formatter import JsonFormatter
from registry import SCENARIO_REGISTRY
from scenario.scenario_runner import ScenarioRunner
from system.system_info import (
    FailureBehavior,
    FailureScenarioConfig,
    NormalLogPattern,
    SystemInfo,
)

FLUENTBIT_LOG_PATH = (
    Path(__file__).resolve().parent.parent
    / "fluentbit"
    / "application.log"
)


def run_scenario(key: str) -> dict:
    if key not in SCENARIO_REGISTRY:
        raise KeyError(f"unknown scenario: {key}")

    scenario_cls, _, error_code = SCENARIO_REGISTRY[key]
    scenario = scenario_cls()

    writer = FileWriter(str(FLUENTBIT_LOG_PATH))
    formatter = JsonFormatter()

    normal_message = "System operating normally."
    system = SystemInfo(
        hostname="web01",
        ip="10.10.1.15",
        os="Ubuntu 22.04",
        cpu_core=8,
        memory_gb=32,
        web_server="nginx",
        application="order-api",
        node_name="worker-3",
        cluster="prod",
        normal_log_pattern=NormalLogPattern(
            delay=0,
            messages=[normal_message],
        ),
        failure_behavior=FailureBehavior(
            probability=1.0,
            trigger_after=0,
            scenarios=[
                FailureScenarioConfig(
                    scenario=scenario, probability=1.0
                )
            ],
        ),
    )

    runner = ScenarioRunner(writer, formatter, system)
    runner.emit_once(scenario)

    events = [{"level": "INFO", "message": normal_message}]
    events += [
        {"level": event.level, "message": event.message}
        for event in scenario.events()
    ]

    return {"error_code": error_code, "events": events}
