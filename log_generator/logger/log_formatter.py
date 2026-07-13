from abc import ABC, abstractmethod

# Abstract interface for log formatting implementations.


class LogFormatter(ABC):

    @abstractmethod
    def format(self, level, message, system, event=None):
        pass