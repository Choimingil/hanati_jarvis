from datetime import datetime

from logger.log_formatter import LogFormatter


class DefaultFormatter(LogFormatter):

    def format(self, level, message, system):

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return (
            f"[{now}] "
            f"[{level}] "
            f"[{system.hostname}] "
            f"{message}"
        )