FROM python:3.11-slim
WORKDIR /workspace
COPY collector/requirements.txt /workspace/collector/requirements.txt
RUN pip install --no-cache-dir -r /workspace/collector/requirements.txt
COPY . /workspace
ENV PYTHONPATH=/workspace
