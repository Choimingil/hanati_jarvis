FROM python:3.11-slim

WORKDIR /workspace
COPY . /workspace

ENV PYTHONPATH=/workspace/log_generator:/workspace
CMD ["python", "/workspace/log_generator/main.py"]
