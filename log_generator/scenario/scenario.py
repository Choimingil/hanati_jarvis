from abc import ABC, abstractmethod


class Scenario(ABC):

    @abstractmethod
    def events(self):
        pass