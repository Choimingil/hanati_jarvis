import hmac
import json
import os
import socket
from flask import Flask, jsonify, request
from execution_agent.runtime import AgentRuntime


def create_app(manifest=None, journal_path=None, token=None, backend=None):
    token = token or os.environ.get("EXECUTION_AGENT_TOKEN", "")
    if len(token) < 32:
        raise ValueError("EXECUTION_AGENT_TOKEN must have at least 32 characters")
    if manifest is None:
        with open(os.environ["EXECUTION_AGENT_MANIFEST"]) as file:
            manifest = json.load(file)
        if manifest.get("host") != socket.gethostname():
            raise ValueError("manifest host must match the actual hostname")
    runtime = AgentRuntime(
        manifest,
        journal_path
        or os.getenv("EXECUTION_AGENT_JOURNAL", "agent-state/executions.sqlite"),
        backend=backend,
    )
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 65536
    app.extensions["runtime"] = runtime

    @app.before_request
    def authenticate_machine():
        supplied = request.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied, "Bearer " + token):
            return jsonify(status="denied"), 401

    @app.get("/identity")
    def identity():
        return jsonify(target=runtime.identity(), policy_digest=runtime.digest)

    @app.post("/<operation>")
    def operation(operation):
        handler = {
            "preflight": runtime.preflight,
            "execute": runtime.execute,
            "verify": runtime.verify,
        }.get(operation)
        if handler is None:
            return jsonify(status="not_found"), 404
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(status="invalid_request"), 400
        try:
            return jsonify(handler(body))
        except ValueError as exc:
            return jsonify(status="blocked", reason=str(exc)), 409

    @app.get("/executions/<execution_id>")
    def execution(execution_id):
        result = runtime.result(execution_id)
        return (jsonify(result), 200) if result else (jsonify(status="not_found"), 404)

    return app


if __name__ == "__main__":
    create_app().run(
        host=os.getenv("EXECUTION_AGENT_BIND", "127.0.0.1"),
        port=int(os.getenv("EXECUTION_AGENT_PORT", "8090")),
    )
