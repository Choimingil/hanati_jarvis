from flask import Flask, jsonify

from config import API_HOST, API_PORT
from routes.log_routes import log_blueprint


def create_app() -> Flask:
    app = Flask(__name__)

    app.register_blueprint(log_blueprint)

    @app.get("/health")
    def health():
        return jsonify({
            "status": "healthy",
            "storage": "mock",
            "case_search": "mock",
            "recommendation": "mock",
        })

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host=API_HOST,
        port=API_PORT,
        debug=False,
    )
