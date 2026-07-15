import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"


def _load_environment() -> None:
    if ENV_FILE.exists():
        load_dotenv(dotenv_path=ENV_FILE, override=False)


_load_environment()


def _normalize_optional_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


@dataclass(frozen=True)
class LLMConfig:
    api_key: str | None = None
    base_url: str | None = None
    model: str = "gpt-4o-mini"
    temperature: float = 0.2
    timeout: int = 30

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            api_key=_normalize_optional_value(os.getenv("OPENAI_API_KEY")),
            base_url=_normalize_optional_value(os.getenv("OPENAI_BASE_URL")),
            model=os.getenv("OPENAI_MODEL") or "gpt-4o-mini",
            temperature=float(os.getenv("OPENAI_TEMPERATURE") or "0.2"),
            timeout=int(os.getenv("OPENAI_TIMEOUT") or "30"),
        )
