FROM python:3.11-slim

WORKDIR /workspace

COPY qdrant/requirements.txt /workspace/qdrant/requirements.txt
RUN pip install --no-cache-dir \
      --index-url https://download.pytorch.org/whl/cpu torch && \
    pip install --no-cache-dir \
      -r /workspace/qdrant/requirements.txt

COPY . /workspace

ENV PYTHONPATH=/workspace
CMD ["python", "-m", "qdrant.seed"]
