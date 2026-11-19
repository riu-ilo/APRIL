import logging
import os
import sys
from flask import Flask, request, jsonify
from flask_cors import CORS

logging.getLogger("werkzeug").disabled = True
sys.modules["flask.cli"].show_server_banner = lambda *args, **kwargs: None

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(BASE_DIR, "repo_output.txt")

@app.route("/api/status", methods=["GET"])
def status():
    return jsonify({"status": "running"})

@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.get_json(silent=True) or {}
    repo_name = (data.get("repo_name") or data.get("repo_path") or "").strip()

    if not repo_name:
        return jsonify({"status": "ignored"}), 204

    print(repo_name, flush=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(repo_name)

    return jsonify({"status": "saved", "repo_name": repo_name})

if __name__ == "__main__":
    app.run(debug=False, port=5000)