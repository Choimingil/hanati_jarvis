from abc import ABC, abstractmethod


class LogWriter(ABC):

    @abstractmethod
    def write(self, log: str):
        pass