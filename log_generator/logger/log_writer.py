from abc import ABC, abstractmethod

# Abstract interface for writing formatted logs.


class LogWriter(ABC):

    @abstractmethod
    def write(self, log: str):
        pass