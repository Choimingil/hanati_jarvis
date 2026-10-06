from flask import Flask, jsonify

from config import (
    API_HOST,
    API_PORT,
)
from routes.log_generator_routes import (
    log_generator_blueprint,
)
from routes.log_routes import log_blueprint
from routes.guidance_routes import guidance_blueprint
from routes.metrics_routes import metrics_blueprint
from routes.remediation_routes import (
    remediation_blueprint,
)
from routes.web_routes import web_blueprint
from routes.operations_routes import operations_blueprint
from operations.health import cached_service_status as service_status
from operations.privacy import redact


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
    app.register_blueprint(operations_blueprint)

    app.register_blueprint(log_blueprint)
    app.register_blueprint(guidance_blueprint)
    app.register_blueprint(metrics_blueprint)
    app.register_blueprint(remediation_blueprint)
    app.register_blueprint(log_generator_blueprint)
    app.register_blueprint(web_blueprint)

    @app.after_request
    def redact_json_output(response):
        if response.is_json:
            response.set_data(app.json.dumps(redact(response.get_json())))
        return response

    @app.get("/health")
    def health():
        result = service_status()
        return jsonify(result), 200 if result["ready"] else 503

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=API_HOST,
        port=API_PORT,
        debug=False,
    )
