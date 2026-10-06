from fastapi import APIRouter

from llm_agent.dto.diagnosis import DiagnosisRequest, DiagnosisResponse
from llm_agent.dto.recommendation import RecommendationRequest, RecommendationResponse
from llm_agent.services.ai_engine import AiEngine

router = APIRouter()
engine = AiEngine()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "llm-agent"}


@router.post("/api/v1/recommend", response_model=RecommendationResponse)
def get_recommendation(request: RecommendationRequest) -> RecommendationResponse:
    return engine.get_recommendation(request)


@router.post("/api/v1/diagnose", response_model=DiagnosisResponse)
def get_diagnosis(request: DiagnosisRequest) -> DiagnosisResponse:
    return engine.get_diagnosis(request)
