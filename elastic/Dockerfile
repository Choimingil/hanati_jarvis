FROM python:3.11-slim
WORKDIR /workspace
COPY elastic/requirements.txt /workspace/elastic/requirements.txt
RUN pip install --no-cache-dir -r /workspace/elastic/requirements.txt
COPY . /workspace
ENV PYTHONPATH=/workspace
