# Entry point for running the log generation workflow.
from pathlib import Path

from logger.file_writer import FileWriter
from logger.json_formatter import JsonFormatter
from registry import SCENARIO_REGISTRY
from scenario.scenario_runner import ScenarioRunner
from system.system_info import FailureBehavior, FailureScenarioConfig, NormalLogPattern, SystemInfo


def _scenario(key: str):
    return SCENARIO_REGISTRY[key][0]()


# fluentbit/fluent-bit.conf가 tail하는 파일에 직접 쓴다. CWD와 무관하게
# 항상 같은 경로를 가리키도록 이 파일 위치 기준 절대경로로 계산한다.
FLUENTBIT_LOG_PATH = (
    Path(__file__).resolve().parent.parent
    / "fluentbit"
    / "application.log"
)

writer = FileWriter(str(FLUENTBIT_LOG_PATH))

# fluentbit의 app_json 파서(fluentbit/parser.conf)가 읽을 수 있도록
# JSON 한 줄짜리 포맷으로 출력한다.
formatter = JsonFormatter()

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
        delay=0.5,
        messages=[
            "System operating normally.",
            "No service anomalies detected.",
            "Traffic is within expected range.",
        ],
    ),
    failure_behavior=FailureBehavior(
        probability=0.1,
        trigger_after=1.0,
        scenarios=[
            FailureScenarioConfig(scenario=_scenario("memory_leak"), probability=0.05),
            FailureScenarioConfig(scenario=_scenario("dns_failure"), probability=0.03),
            FailureScenarioConfig(scenario=_scenario("external_api_failure"), probability=0.03),
            FailureScenarioConfig(scenario=_scenario("redis_failure"), probability=0.03),
            FailureScenarioConfig(scenario=_scenario("disk_full"), probability=0.03),
            FailureScenarioConfig(scenario=_scenario("db_connection_failure"), probability=0.03),
        ],
    ),
)

runner = ScenarioRunner(
    writer,
    formatter,
    system
)

runner.run()