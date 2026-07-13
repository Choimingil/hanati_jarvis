from abc import ABC, abstractmethod


class LogFormatter(ABC):

    @abstractmethod
    def format(self, level, message, system):
        pass