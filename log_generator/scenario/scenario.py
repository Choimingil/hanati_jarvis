from abc import ABC, abstractmethod

# Base interface for all scenario definitions.


class Scenario(ABC):

    @abstractmethod
    def events(self):
        pass