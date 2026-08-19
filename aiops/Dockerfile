FROM python:3.11-slim

WORKDIR /workspace
COPY aiops/requirements.txt /workspace/aiops/requirements.txt
RUN pip install --no-cache-dir -r /workspace/aiops/requirements.txt

COPY . /workspace

ENV PYTHONPATH=/workspace
CMD ["python", "/workspace/app.py"]
