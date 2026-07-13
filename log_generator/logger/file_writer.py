import threading

# Appends log lines to a file using a lock for safe concurrent writes.

from logger.log_writer import LogWriter


class FileWriter(LogWriter):

    def __init__(self, filename):
        self.filename = filename
        self.lock = threading.Lock()

    def write(self, log: str):

        with self.lock:
            with open(self.filename, "a", encoding="utf8") as f:
                f.write(log + "\n")