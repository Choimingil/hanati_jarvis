from datetime import datetime

from logger.log_formatter import LogFormatter


class DefaultFormatter(LogFormatter):

    def format(self, level, message, system, event=None):

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = getattr(event, "status_after", None) or "UNKNOWN"

        return (
            f"[{now}] "
            f"[{level}] "
            f"[{system.hostname}] "
            f"[{status}] "
            f"{message}"
        )