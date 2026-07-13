from dataclasses import dataclass


@dataclass
class LogEvent:

    delay: float

    level: str

    message: str

    # TODO- Add additional fields for more detailed log information, such as timestamp, source, etc.