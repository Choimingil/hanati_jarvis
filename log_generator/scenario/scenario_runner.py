import time


class ScenarioRunner:

    def __init__(self, writer, formatter, system):

        self.writer = writer
        self.formatter = formatter
        self.system = system

    def run(self, scenario):

        for event in scenario.events():

            time.sleep(event.delay)

            log = self.formatter.format(
                event.level,
                event.message,
                self.system,
                event
            )

            self.writer.write(log)