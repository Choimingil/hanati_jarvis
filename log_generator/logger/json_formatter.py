import json
from datetime import datetime

# Formats log entries as single-line JSON so fluentbit's "app_json" tail
# parser (fluentbit/parser.conf) and the backend's log_normalizer can read them.

from logger.log_formatter import LogFormatter


class JsonFormatter(LogFormatter):

    def format(self, level, message, system, event=None):

        status = getattr(event, "status_after", None) or "UNKNOWN"
        source = getattr(event, "source", None)

        return json.dumps({
            "timestamp": datetime.now()
            .astimezone()
            .strftime("%Y-%m-%dT%H:%M:%S%z"),
            "level": level,
            "message": message,
            "host": system.hostname,
            "service": system.application,
            "status": status,
            "source": source,
        }, ensure_ascii=False)
