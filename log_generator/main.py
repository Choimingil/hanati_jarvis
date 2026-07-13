# Entry point for running the log generation workflow.
from pathlib import Path

from logger.file_writer import FileWriter
from logger.json_formatter import JsonFormatter
from scenario.dns_failure_scenario import DNSFailureScenario
from scenario.memory_leak_scenario import MemoryLeakScenario
from scenario.external_api_failure_scenario import ExternalAPIFailureScenario
from scenario.redis_cache_failure_scenario import RedisFailureScenario
from scenario.disk_full_scenario import DiskFullScenario
from scenario.database_connection_failure_scenario import DatabaseConnectionFailureScenario
from scenario.scenario_runner import ScenarioRunner
from system.system_info import FailureBehavior, FailureScenarioConfig, NormalLogPattern, SystemInfo


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
            FailureScenarioConfig(scenario=MemoryLeakScenario(), probability=0.05),
            FailureScenarioConfig(scenario=DNSFailureScenario(), probability=0.03),
            FailureScenarioConfig(scenario=ExternalAPIFailureScenario(), probability=0.03),
            FailureScenarioConfig(scenario=RedisFailureScenario(), probability=0.03),
            FailureScenarioConfig(scenario=DiskFullScenario(), probability=0.03),
            FailureScenarioConfig(scenario=DatabaseConnectionFailureScenario(), probability=0.03),
        ],
    ),
)

runner = ScenarioRunner(
    writer,
    formatter,
    system
)

runner.run()