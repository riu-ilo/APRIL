import json
import os
import re
import sys
import time
import tempfile

FENCE_RE = re.compile(r"^\s*(```|~~~)")
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
QUOTE_RE = re.compile(r"^\s*>\s?")

IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
ITALIC_RE = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")

SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")

ABBREVIATIONS = ["e.g.", "i.e.", "etc.", "vs.", "approx.", "No."]
DOT_PLACEHOLDER = "\u0001"

def clean_inline(text):
    text = IMAGE_RE.sub(r"\1", text)
    text = LINK_RE.sub(r"\1", text)
    text = BOLD_RE.sub(r"\1", text)
    text = ITALIC_RE.sub(r"\1", text)
    text = text.replace("`", "")
    return re.sub(r"\s+", " ", text).strip()

def protect_abbreviations(text):
    for abbr in ABBREVIATIONS:
        text = text.replace(abbr, abbr.replace(".", DOT_PLACEHOLDER))
    return text

def split_sentences(text):
    protected = protect_abbreviations(text)
    pieces = []
    start = 0
    for match in SENTENCE_END_RE.finditer(protected):
        pieces.append((text[start:match.start()], start))
        start = match.end()
    pieces.append((text[start:], start))
    return [(p.strip(), off) for p, off in pieces if p.strip()]

def extract_sentences(markdown_text):
    results = []
    section = ""

    buffer_text = ""
    buffer_starts = []

    def line_at(offset):
        line = buffer_starts[0][1]
        for off, ln in buffer_starts:
            if off <= offset:
                line = ln
        return line

    def flush():
        nonlocal buffer_text, buffer_starts
        if buffer_text.strip():
            for sentence, offset in split_sentences(buffer_text):
                results.append({
                    "text": sentence,
                    "line": line_at(offset),
                    "section": section,
                    "kind": "sentence",
                })
        buffer_text = ""
        buffer_starts = []

    def add_to_buffer(text, line_no):
        nonlocal buffer_text
        if not text:
            return
        if buffer_text:
            buffer_text += " "
        buffer_starts.append((len(buffer_text), line_no))
        buffer_text += text

    in_code_block = False

    for line_no, raw in enumerate(markdown_text.splitlines(), start=1):

        if FENCE_RE.match(raw):
            flush()
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        if not raw.strip():
            flush()
            continue

        heading = HEADING_RE.match(raw)
        if heading:
            flush()
            section = clean_inline(heading.group(2))
            continue

        if TABLE_RE.match(raw):
            flush()
            if not TABLE_SEPARATOR_RE.match(raw):
                cells = [clean_inline(c) for c in raw.strip().strip("|").split("|")]
                row = " | ".join(c for c in cells if c)
                if row:
                    results.append({
                        "text": row,
                        "line": line_no,
                        "section": section,
                        "kind": "table_row",
                    })
            continue

        raw = QUOTE_RE.sub("", raw)
        item = LIST_RE.match(raw)
        if item:
            flush()
            add_to_buffer(clean_inline(item.group(1)), line_no)
            continue

        add_to_buffer(clean_inline(raw), line_no)

    flush()
    return results

def extract_from_file(path):
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    return {"file": path, "sentences": extract_sentences(text)}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WATCH_DIR = os.environ.get("April_WATCH_DIR", r"C:\Users\Asus\OneDrive\Desktop\april\Python_engine\input")
RAW_FILE = os.path.join(BASE_DIR, "raw.json")
POLL_SECONDS = float(os.environ.get("April_POLL_SECONDS", "1.0"))
IGNORED_DIRS = {".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "node_modules"}

def atomic_write_json(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    fd, temp_path = tempfile.mkstemp(prefix=".raw-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def markdown_files(root):
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".")]
        for filename in files:
            if filename.lower().endswith((".md", ".markdown")):
                yield os.path.join(current, filename)

def watch_for_markdown():
    seen = {}
    print("Extractor watching for .md files in: {}".format(os.path.abspath(WATCH_DIR)), flush=True)
    print("raw.json will be created only after a Markdown file is found.", flush=True)

    while True:
        try:
            for path in markdown_files(WATCH_DIR):
                try:
                    stat = os.stat(path)
                    signature = (stat.st_mtime_ns, stat.st_size)
                    if seen.get(path) == signature:
                        continue

                    result = extract_from_file(path)
                    atomic_write_json(RAW_FILE, result)
                    seen[path] = signature
                    print("Extracted {} statement(s) from {} -> {}".format(
                        len(result["sentences"]), os.path.relpath(path, WATCH_DIR), RAW_FILE
                    ), flush=True)
                except (OSError, UnicodeError) as exc:
                    print("Extractor skipped {}: {}".format(path, exc), flush=True)
        except Exception as exc:
            print("Extractor watcher error: {}".format(exc), flush=True)

        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    watch_for_markdown()