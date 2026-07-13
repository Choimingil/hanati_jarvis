from abc import ABC, abstractmethod

# Base interface for all scenario definitions.


class Scenario(ABC):

    stop_after_failure: bool = True

    @abstractmethod
    def events(self):
        pass