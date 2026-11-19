import json
import logging
import os
import sys
from flask import Flask, jsonify
from flask_cors import CORS

logging.getLogger("werkzeug").disabled = True
sys.modules["flask.cli"].show_server_banner = lambda *args, **kwargs: None

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(BASE_DIR, "verdict.json")

@app.route("/api/findings", methods=["GET"])
def get_findings():
    if not os.path.exists(RESULTS_FILE):
        return jsonify({"findings": []})

    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))

if __name__ == "__main__":
    app.run(debug=False, port=5001)