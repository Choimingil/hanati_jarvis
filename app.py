from flask import Flask, jsonify

from config import (
    API_HOST,
    API_PORT,
    CASE_SEARCHER_BACKEND,
    LOG_REPOSITORY_BACKEND,
    RECOMMENDATION_BACKEND,
)
# NOTE: mock 백엔드 없음. LOG_REPOSITORY_BACKEND="elastic",
# RECOMMENDATION_BACKEND="llm" 고정값 (config.py 참고).
from routes.log_generator_routes import (
    log_generator_blueprint,
)
from routes.log_routes import log_blueprint
from routes.remediation_routes import (
    remediation_blueprint,
)
from routes.web_routes import web_blueprint


def create_app() -> Flask:
    app = Flask(__name__)

    app.register_blueprint(log_blueprint)
    app.register_blueprint(remediation_blueprint)
    app.register_blueprint(log_generator_blueprint)
    app.register_blueprint(web_blueprint)

    @app.get("/health")
    def health():
        return jsonify({
            "status": "healthy",
            "storage": LOG_REPOSITORY_BACKEND,
            "case_search": CASE_SEARCHER_BACKEND,
            "recommendation": RECOMMENDATION_BACKEND,
        })

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=API_HOST,
        port=API_PORT,
        debug=False,
    )
