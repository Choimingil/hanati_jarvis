import random
import time

from logger.log_constants import LogLevel
from scenario.log_event import LogEvent


class ScenarioRunner:

    def __init__(self, writer, formatter, system):

        self.writer = writer
        self.formatter = formatter
        self.system = system

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

        message = random.choice(pattern.messages)
        event = LogEvent(
            delay=pattern.delay,
            level=LogLevel.INFO,
            message=message,
        )
        self._emit_event(event)
        return True

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

        return True

    def run(self, scenario):
        while True:
            if not self._emit_normal_log():
                break

            behavior = self.system.failure_behavior
            if not behavior:
                break

            if behavior.trigger_after > 0:
                time.sleep(behavior.trigger_after)

            if self._emit_failure_events(scenario):
                break

            if not behavior:
                break