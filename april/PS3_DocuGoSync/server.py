
import json
import subprocess
import sys
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"
REPORT = ROOT / "report.json"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND), **kwargs)

    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/status":
            return self.send_json({"status": "online"})
        return super().do_GET()

    
    def do_POST(self):
        if self.path != "/api/analyze":
            return self.send_json({
                "status": "error",
                "message": "Unknown endpoint"
            }, 404)

        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length))

            repo_url = payload.get("repo_url", "").strip()
            base_ref = payload.get("base_ref", "").strip()
            head_ref = payload.get("head_ref", "").strip()

            if not all([repo_url, base_ref, head_ref]):
                return self.send_json({
                    "status": "error",
                    "message": "Repository URL, base and target are required."
                }, 400)

            print(f"\nAnalyzing: {repo_url} ({base_ref} -> {head_ref})")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "run.py"),
                    repo_url,
                    base_ref,
                    head_ref
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode != 0:
                return self.send_json({
                    "status": "error",
                    "message": result.stderr or result.stdout or "Analysis failed."
                }, 500)

            if not REPORT.exists():
                return self.send_json({
                    "status": "error",
                    "message": "report.json was not generated."
                }, 500)

            report = json.loads(REPORT.read_text(encoding="utf-8"))

            summary = report.get("summary", {})

            report["status"] = "success"
            report["files_scanned"] = summary.get("changed_files", 0)
            report["issues_found"] = summary.get("documentation_findings", 0)
            report["confidence"] = (
                f'{summary.get("documentation_findings", 0)}/'
                f'{summary.get("documentation_findings", 0)}'
            )

            report["changes"] = report.get("code_changes", [])
            report["logs"] = result.stdout

            return self.send_json(report)

        except subprocess.TimeoutExpired:
            return self.send_json({
                "status": "error",
                "message": "Analysis timed out after 5 minutes."
            }, 504)

        except Exception as error:
            return self.send_json({
                "status": "error",
                "message": str(error)
            }, 500)



if __name__ == "__main__":
    print("DocuGoSync server running at http://127.0.0.1:8000")
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
