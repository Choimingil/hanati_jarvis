from typing import Any

from flask import Blueprint, jsonify, request

from dependencies import log_processor


log_blueprint = Blueprint(
    "logs",
    __name__,
)


def _slim_result(result: dict[str, Any]) -> dict[str, Any]:
    """fluent-bit의 http 출력 플러그인은 응답 본문을 고정 버퍼(기본 4KB,
    설정 불가 - `fluent-bit -o http -h`에 버퍼 크기 옵션 자체가 없다)로
    읽는다. log_processor.process()의 전체 결과(runbooks/past_cases/진단
    stdout 포함)를 그대로 돌려주면 이 버퍼를 넘겨서
    "[http_client] cannot increase buffer" 경고가 남는다.
    fluent-bit은 상태 코드로만 재시도 여부를 판단하고, 상세 결과는 이미
    Elasticsearch에 저장돼 있어 웹 콘솔이 거기서 따로 조회한다 - 응답엔
    요약만 담는다."""
    slim = {"status": result.get("status")}
    for key in (
        "reason", "error_code", "diagnosis_count", "message",
    ):
        if key in result:
            slim[key] = result[key]
    return slim


@log_blueprint.post("/api/v1/logs")
def receive_logs():
    payload = request.get_json(silent=True)

    if payload is None:
        return jsonify({
            "status": "invalid_request",
            "reason": "JSON body is required",
        }), 400

    if isinstance(payload, dict):
        logs = [payload]
    elif isinstance(payload, list):
        logs = payload
    else:
        return jsonify({
            "status": "invalid_request",
            "reason": (
                "body must be a JSON object or array"
            ),
        }), 400

    responses: list[dict[str, Any]] = []

    for raw_log in logs:
        if not isinstance(raw_log, dict):
            responses.append({
                "status": "invalid_log",
            })
            continue

        try:
            result = log_processor.process(
                raw_log
            )
            responses.append(_slim_result(result))

        except Exception as exc:
            responses.append({
                "status": "processing_failed",
                "reason": str(exc),
            })

    return jsonify(responses), 200
