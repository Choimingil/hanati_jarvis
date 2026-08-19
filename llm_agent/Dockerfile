FROM python:3.11-slim

WORKDIR /workspace
COPY llm_agent/requirements.txt /workspace/llm_agent/requirements.txt
RUN pip install --no-cache-dir -r /workspace/llm_agent/requirements.txt

COPY . /workspace

ENV PYTHONPATH=/workspace
CMD ["uvicorn", "llm_agent.app:app", "--host", "0.0.0.0", "--port", "8000"]
