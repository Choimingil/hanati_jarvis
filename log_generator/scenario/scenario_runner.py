import random

# Runs normal logs and occasionally injects a failure scenario.
import time
from typing import Iterable, List, Optional

from logger.log_constants import LogLevel
from scenario.log_event import LogEvent


class ScenarioRunner:

    def __init__(self, writer, formatter, system):

        self.writer = writer
        self.formatter = formatter
        self.system = system
        self._normal_message_index = 0

    def _emit_event(self, event):
        log = self.formatter.format(
            event.level,
            event.message,
            self.system,
            event
        )
        self.writer.write(log)

    def _emit_normal_log(self):
        if not self.system.normal_log_pattern:
            return False

        pattern = self.system.normal_log_pattern
        if not pattern.messages:
            return False

        if pattern.messages:
            message = pattern.messages[self._normal_message_index % len(pattern.messages)]
            self._normal_message_index += 1
        else:
            return False

        event = LogEvent(
            delay=pattern.delay,
            level=LogLevel.INFO,
            message=message,
        )
        self._emit_event(event)
        return True

    def _select_scenario(self, scenarios):
        if not scenarios:
            return None

        if len(scenarios) == 1:
            return scenarios[0]

        weights = [getattr(scenario, "probability", 1.0) for scenario in scenarios]
        total_weight = sum(weights)
        if total_weight <= 0:
            return None

        pick = random.uniform(0, total_weight)
        cumulative = 0.0
        for scenario, weight in zip(scenarios, weights):
            cumulative += weight
            if pick <= cumulative:
                return scenario

        return scenarios[-1]

    def _emit_failure_events(self, scenario):
        behavior = self.system.failure_behavior
        if not behavior:
            return False

        scenario_to_run = scenario or behavior.scenario
        if not scenario_to_run:
            return False

        if behavior.probability < 1.0 and random.random() > behavior.probability:
            return False

        for event in scenario_to_run.events():
            time.sleep(event.delay)
            self._emit_event(event)

        return getattr(scenario_to_run, "stop_after_failure", True)

    def _get_configured_scenarios(self):
        behavior = self.system.failure_behavior
        if not behavior:
            return []

        if behavior.scenarios:
            return [config.scenario for config in behavior.scenarios]
        
        return []

    def emit_once(self, scenario):
        """정상 로그 1건 + 지정된 시나리오의 장애 이벤트를 확정적으로(확률 무시)
        1회 내보낸다. 웹 콘솔의 "분석" 버튼처럼 특정 시나리오를 즉시
        재현하고 싶을 때 쓴다 (무한 루프인 run()과 별개)."""
        self._emit_normal_log()

        for event in scenario.events():
            time.sleep(event.delay)
            self._emit_event(event)

    def run(self, scenario=None):
        scenarios = self._get_configured_scenarios()
        if scenario is not None:
            if isinstance(scenario, list):
                scenarios = scenario
            else:
                scenarios = [scenario]

        while True:
            if not self._emit_normal_log():
                break

            behavior = self.system.failure_behavior
            if not behavior:
                break

            if behavior.trigger_after > 0:
                time.sleep(behavior.trigger_after)

            if scenarios:
                current_scenario = self._select_scenario(scenarios)
                should_stop = self._emit_failure_events(current_scenario)
                if should_stop:
                    break
            else:
                should_stop = self._emit_failure_events(None)
                if should_stop:
                    break

            if not behavior:
                break