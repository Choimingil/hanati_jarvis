from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env", override=False)

from fastapi import FastAPI

from llm_agent.api.llm_api import router as recommendation_router

def create_app() -> FastAPI:
    app = FastAPI(title="LLM Agent API", version="0.1.0")
    app.include_router(recommendation_router)
    return app


app = create_app()
