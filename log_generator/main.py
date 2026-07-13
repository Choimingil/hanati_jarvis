from logger.default_formatter import DefaultFormatter
from logger.file_writer import FileWriter
from scenario.dns_failure_scenario import DNSFailureScenario
from scenario.scenario_runner import ScenarioRunner
from system.system_info import FailureBehavior, NormalLogPattern, SystemInfo


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
        scenario=DNSFailureScenario(),
    ),
)

runner = ScenarioRunner(
    writer,
    formatter,
    system
)

runner.run(DNSFailureScenario())