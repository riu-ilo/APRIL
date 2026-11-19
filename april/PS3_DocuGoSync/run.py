import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CPP_DIR = ROOT / "CPP_engine"
PY_DIR = ROOT / "Python_engine"

# ---> SET YOUR EXACT SCRIPT & OUTPUT PATHS HERE <---
EXTRACTOR_PATH = Path(r"C:\Users\Asus\OneDrive\Desktop\april\bringer.py")
COMPARER_PATH = Path(r"C:\Users\Asus\OneDrive\Desktop\april\hollow.py")
RAW_OUTPUT_PATH = Path(r"C:\Users\Asus\OneDrive\Desktop\april\raw.json")
VERDICT_OUTPUT_PATH = Path(r"C:\Users\Asus\OneDrive\Desktop\april\verdict.json")

INPUT_FILE = Path(os.environ.get("RUN_INPUT_FILE", r"C:\Users\Asus\OneDrive\Desktop\april\repo_output.txt"))
POLL_SECONDS = 1.0

CPP_CONST_RE = re.compile(
    r"^\s*(?:static\s+)?(?:constexpr|const)?\s*"
    r"(?:unsigned\s+|signed\s+|long\s+|short\s+|std::)?(?:int|float|double|bool|char|string|size_t|uint\d+_t|int\d+_t|auto)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;]+);"
)
CPP_DEFINE_RE = re.compile(r"^\s*#define\s+([A-Za-z_][A-Za-z0-9_]*)\s+(.+)$")


def load_module(mod_name, file_path):
    if not file_path.is_file():
        raise RuntimeError(f"Module not found at: {file_path}")
    spec = importlib.util.spec_from_file_location(mod_name, str(file_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def resolve_git():
    git_path = shutil.which("git")
    if git_path:
        return git_path
    for candidate in [
        r"C:\Program Files\Git\cmd\git.exe",
        r"C:\Program Files (x86)\Git\cmd\git.exe",
        Path.home() / r"AppData\Local\Programs\Git\cmd\git.exe",
    ]:
        if Path(candidate).is_file():
            return str(candidate)
    raise RuntimeError(
        "Git executable not found. Install Git for Windows or add Git\\cmd to PATH."
    )


def normalize_repo_url(url):
    if "/tree/" in url:
        url = url.split("/tree/", 1)[0]
    return url.rstrip("/")


def run_command(command, cwd=None, capture=True):
    if command and command[0] == "git":
        command = [resolve_git(), *command[1:]]
    result = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=capture
    )
    if result.returncode != 0:
        error = result.stderr if capture else "Command failed"
        raise RuntimeError(f"Command failed: {' '.join(map(str, command))}\n{error}")
    return result.stdout if capture else ""


def git_ref(repo, ref):
    candidates = [ref, f"origin/{ref}"]
    for candidate in candidates:
        result = subprocess.run(
            [resolve_git(), "rev-parse", "--verify", f"{candidate}^{{commit}}"],
            cwd=repo, text=True, capture_output=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
    raise RuntimeError(f"Could not find Git commit or branch: {ref}")


def git_file(repo, commit, path):
    result = subprocess.run(
        [resolve_git(), "show", f"{commit}:{path}"],
        cwd=repo, capture_output=True
    )
    if result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", errors="replace")


def get_language(path):
    ext = Path(path).suffix.lower()
    languages = {
        ".cpp": "C++", ".cc": "C++", ".cxx": "C++",
        ".h": "C++", ".hpp": "C++",
        ".py": "Python", ".js": "JavaScript",
        ".ts": "TypeScript", ".java": "Java",
        ".c": "C", ".go": "Go", ".rs": "Rust",
        ".html": "HTML", ".css": "CSS"
    }
    return languages.get(ext, "Other")


def find_readme(repo, commit):
    files = run_command(
        ["git", "ls-tree", "-r", "--name-only", commit],
        cwd=repo
    ).splitlines()

    candidates = [
        f for f in files
        if Path(f).name.lower().startswith("readme.")
        or Path(f).name.lower() == "readme"
    ]

    if not candidates:
        raise RuntimeError(
            "No README found in this commit. "
            "Choose a repository containing a README file."
        )

    candidates.sort(key=lambda p: ("/" in p, len(p)))
    return candidates[0]


def parse_cpp_constants(source_text):
    constants = {}
    for line in source_text.splitlines():
        line_clean = line.split("//", 1)[0].strip()
        if not line_clean:
            continue
        m = CPP_CONST_RE.match(line_clean) or CPP_DEFINE_RE.match(line_clean)
        if m:
            name, raw_val = m.group(1), m.group(2).strip()
            if len(raw_val) >= 2 and raw_val[0] == raw_val[-1] and raw_val[0] in ('"', "'"):
                raw_val = raw_val[1:-1]
            constants[name] = raw_val
    return constants


def analyse_cpp_files(repo, base, head, changed_cpp):
    if not changed_cpp:
        return []

    all_changes = []

    for item in changed_cpp:
        old_path = item.get("old_path", item["path"])
        new_path = item.get("new_path", item["path"])

        old_content = (
            git_file(repo, base, old_path)
            if item["status"] != "added" else ""
        )
        new_content = (
            git_file(repo, head, new_path)
            if item["status"] != "deleted" else ""
        )

        old_consts = parse_cpp_constants(old_content)
        new_consts = parse_cpp_constants(new_content)

        for sym in sorted(set(old_consts) | set(new_consts)):
            if sym in old_consts and sym not in new_consts:
                all_changes.append({
                    "file": item["path"],
                    "symbol": sym,
                    "old_value": old_consts[sym],
                    "new_value": None,
                    "change_type": "removed"
                })
            elif sym not in old_consts and sym in new_consts:
                all_changes.append({
                    "file": item["path"],
                    "symbol": sym,
                    "old_value": None,
                    "new_value": new_consts[sym],
                    "change_type": "added"
                })
            elif old_consts[sym] != new_consts[sym]:
                all_changes.append({
                    "file": item["path"],
                    "symbol": sym,
                    "old_value": old_consts[sym],
                    "new_value": new_consts[sym],
                    "change_type": "value_changed"
                })

    counts = {"added": 0, "removed": 0, "modified": 0}
    for change in all_changes:
        kind = change.get("change_type", "").lower()
        if kind == "value_changed":
            counts["modified"] += 1
        elif kind in counts:
            counts[kind] += 1

    return {
        "language": "cpp",
        "status": "success",
        "total_changes": len(all_changes),
        "summary": counts,
        "changes": all_changes
    }


def process_repo(repo_url, base_ref, head_ref):
    repo_url = normalize_repo_url(repo_url)
    print(f"\n[1/6] Cloning repository: {repo_url}", flush=True)
    with tempfile.TemporaryDirectory() as temp:
        repo = Path(temp) / "repo"
        run_command(["git", "clone", repo_url, str(repo)])
        run_command(["git", "fetch", "--all", "--tags"], cwd=repo)

        base = git_ref(repo, base_ref)
        head = git_ref(repo, head_ref)

        print("[2/6] Detecting changed files...", flush=True)
        diff = run_command(
            ["git", "diff", "--name-status", "--find-renames", base, head],
            cwd=repo
        )

        changed_files = []
        for line in diff.splitlines():
            parts = line.split("\t")
            if len(parts) < 2:
                continue

            git_status = parts[0]
            if git_status.startswith("R") or git_status.startswith("C"):
                old_path, new_path = parts[1], parts[2]
                path = new_path
            else:
                old_path = new_path = parts[1]
                path = parts[1]

            status = (
                "added" if git_status == "A" else
                "deleted" if git_status == "D" else
                "renamed" if git_status.startswith("R") else
                "modified"
            )

            changed_files.append({
                "path": path,
                "old_path": old_path,
                "new_path": new_path,
                "status": status,
                "language": get_language(path)
            })

        cpp_files = [
            f for f in changed_files
            if f["language"] == "C++"
        ]

        print(f"    Found {len(changed_files)} changed files.", flush=True)
        print(f"    C++ files to analyse: {len(cpp_files)}", flush=True)

        print("[3/6] Running C++ analysis...", flush=True)
        changes_json = analyse_cpp_files(repo, base, head, cpp_files)

        if not changes_json:
            changes_json = {
                "language": "cpp",
                "status": "success",
                "total_changes": 0,
                "summary": {"added": 0, "removed": 0, "modified": 0},
                "changes": []
            }

        changes_path = CPP_DIR / "output" / "changes.json"
        changes_path.parent.mkdir(parents=True, exist_ok=True)
        changes_path.write_text(
            json.dumps(changes_json, indent=2),
            encoding="utf-8"
        )

        print("[4/6] Extracting README documentation...", flush=True)
        readme_path = find_readme(repo, head)
        readme_content = git_file(repo, head, readme_path)

        input_dir = PY_DIR / "input"
        output_dir = PY_DIR / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        RAW_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        VERDICT_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

        current_readme = input_dir / "README_current.md"
        current_readme.write_text(readme_content, encoding="utf-8")

        bringer = load_module("bringer", EXTRACTOR_PATH)
        raw_data = bringer.extract_from_file(str(current_readme))
        RAW_OUTPUT_PATH.write_text(json.dumps(raw_data, indent=2), encoding="utf-8")

        print("[5/6] Comparing code changes with documentation...", flush=True)
        hollow = load_module("hollow", COMPARER_PATH)
        verdict = hollow.find_findings(changes_json, raw_data)
        VERDICT_OUTPUT_PATH.write_text(json.dumps(verdict, indent=2), encoding="utf-8")
        print("[6/6] Creating unified report...", flush=True)
        unsupported = [
            f for f in changed_files
            if f["language"] != "C++"
        ]

        report = {
            "repository": repo_url,
            "base_commit": base,
            "head_commit": head,
            "readme_used": readme_path,
            "changed_files": changed_files,
            "unsupported_files": unsupported,
            "summary": {
                "changed_files": len(changed_files),
                "cpp_files_analyzed": len(cpp_files),
                "code_changes": changes_json["total_changes"],
                "documentation_findings": len(verdict.get("findings", []))
            },
            "code_changes": changes_json.get("changes", []),
            "findings": verdict.get("findings", [])
        }

        report_json = json.dumps(report, indent=2)

        (ROOT / "report.json").write_text(report_json, encoding="utf-8")
        (output_dir / "report.json").write_text(report_json, encoding="utf-8")

        print("\nSUCCESS! Report generated:", flush=True)
        print(ROOT / "report.json", flush=True)
        print(json.dumps(report["summary"], indent=2), flush=True)


def main():
    last_signature = None
    print(f"Watching input file: {INPUT_FILE}", flush=True)

    while True:
        try:
            if INPUT_FILE.is_file():
                stat = INPUT_FILE.stat()
                signature = (stat.st_mtime_ns, stat.st_size)

                if signature != last_signature:
                    content = INPUT_FILE.read_text(encoding="utf-8").strip()
                    parts = content.split()

                    if len(parts) >= 3:
                        repo_url, base_ref, head_ref = parts[0], parts[1], parts[2]
                        process_repo(repo_url, base_ref, head_ref)
                    elif len(parts) == 2:
                        repo_url, base_ref, head_ref = parts[0], parts[1], "HEAD"
                        process_repo(repo_url, base_ref, head_ref)
                    elif len(parts) == 1:
                        repo_url, base_ref, head_ref = parts[0], "HEAD~1", "HEAD"
                        process_repo(repo_url, base_ref, head_ref)

                    last_signature = signature
        except Exception as error:
            print(f"\nERROR: {error}", flush=True)
            if INPUT_FILE.is_file():
                stat = INPUT_FILE.stat()
                last_signature = (stat.st_mtime_ns, stat.st_size)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped watching.")