import threading
import sys

# Appends log lines to a file and also prints them to stdout so Docker
# container logs show the generated entries in real time.

from logger.log_writer import LogWriter


class FileWriter(LogWriter):

    def __init__(self, filename):
        self.filename = filename
        self.lock = threading.Lock()

    def write(self, log: str):

        with self.lock:
            with open(self.filename, "a", encoding="utf8") as f:
                f.write(log + "\n")

            print(log, flush=True)
            sys.stdout.flush()