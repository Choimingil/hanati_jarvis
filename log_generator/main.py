# Entry point for running the log generation workflow.
from logger.default_formatter import DefaultFormatter
from logger.file_writer import FileWriter
from scenario.dns_failure_scenario import DNSFailureScenario
from scenario.memory_leak_scenario import MemoryLeakScenario
from scenario.external_api_failure_scenario import ExternalAPIFailureScenario
from scenario.redis_cache_failure_scenario import RedisFailureScenario
from scenario.disk_full_scenario import DiskFullScenario
from scenario.database_connection_failure_scenario import DatabaseConnectionFailureScenario
from scenario.scenario_runner import ScenarioRunner
from system.system_info import FailureBehavior, FailureScenarioConfig, NormalLogPattern, SystemInfo


writer = FileWriter("app.log")

formatter = DefaultFormatter()

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