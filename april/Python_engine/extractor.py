"""
DocuGoSync - Stage 1: Markdown documentation reader.

Reads a Markdown file and returns a list of "statements" (mostly sentences),
each with the line number where it starts. Later stages (matching, drift
detection) work on this output.

Only the Python standard library is used, so nothing needs installing.

Usage:
    python extractor.py sample_README.md
"""

import json
import re
import sys

# ---------------------------------------------------------------------------
# Regular expressions (compiled once, reused for every line)
# ---------------------------------------------------------------------------

FENCE_RE = re.compile(r"^\s*(```|~~~)")              # start/end of a code block
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")  # "- item", "1. item"
TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")             # "| a | b |"
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")  # "|---|---|"
QUOTE_RE = re.compile(r"^\s*>\s?")                   # "> quoted"

# Inline Markdown clean-up
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")     # ![alt](url) -> alt
LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")       # [text](url) -> text
BOLD_RE = re.compile(r"\*\*(.+?)\*\*")               # **bold** -> bold
ITALIC_RE = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")

# A sentence ends at . ! or ? followed by whitespace and then a character that
# can start a new sentence. "1.5 seconds" is NOT split because there is no
# whitespace after the dot.
SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")

# Abbreviations whose dot must not end a sentence.
ABBREVIATIONS = ["e.g.", "i.e.", "etc.", "vs.", "approx.", "No."]
DOT_PLACEHOLDER = "\u0001"  # same length as "." so character offsets stay valid


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def clean_inline(text):
    """Remove Markdown decoration but keep the words.

    We deliberately keep underscores, because symbols like MAX_USERS contain
    them, and we drop backticks so `TIMEOUT` becomes TIMEOUT.
    """
    text = IMAGE_RE.sub(r"\1", text)
    text = LINK_RE.sub(r"\1", text)
    text = BOLD_RE.sub(r"\1", text)
    text = ITALIC_RE.sub(r"\1", text)
    text = text.replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def protect_abbreviations(text):
    """Hide the dots inside abbreviations so they do not split sentences."""
    for abbr in ABBREVIATIONS:
        text = text.replace(abbr, abbr.replace(".", DOT_PLACEHOLDER))
    return text


def split_sentences(text):
    """Split a block of text into (sentence, start_offset) pairs."""
    protected = protect_abbreviations(text)
    pieces = []
    start = 0
    for match in SENTENCE_END_RE.finditer(protected):
        pieces.append((text[start:match.start()], start))
        start = match.end()
    pieces.append((text[start:], start))
    return [(p.strip(), off) for p, off in pieces if p.strip()]


# ---------------------------------------------------------------------------
# Main extraction logic
# ---------------------------------------------------------------------------

def extract_sentences(markdown_text):
    """Return a list of dicts: {"text", "line", "section", "kind"}.

    kind is "sentence" (normal prose / list item) or "table_row".
    section is the nearest heading above the statement (useful context for
    matching later). Code blocks are skipped on purpose: they show examples,
    not claims about the current behaviour.
    """
    results = []
    section = ""

    # The "paragraph buffer": text collected so far, plus a map telling us
    # which source line each part of the text came from.
    buffer_text = ""
    buffer_starts = []  # list of (offset_in_buffer, line_number)

    def line_at(offset):
        """Which source line does this character offset belong to?"""
        line = buffer_starts[0][1]
        for off, ln in buffer_starts:
            if off <= offset:
                line = ln
        return line

    def flush():
        """Turn the buffered paragraph into sentences and store them."""
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

    # enumerate(..., start=1) because humans count lines from 1, not 0
    for line_no, raw in enumerate(markdown_text.splitlines(), start=1):

        # 1. Code fences: toggle on/off and ignore everything inside.
        if FENCE_RE.match(raw):
            flush()
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        # 2. Blank line ends a paragraph.
        if not raw.strip():
            flush()
            continue

        # 3. Headings: update the current section, never a statement itself.
        heading = HEADING_RE.match(raw)
        if heading:
            flush()
            section = clean_inline(heading.group(2))
            continue

        # 4. Table rows: one statement per row ("| TIMEOUT | 30 | seconds |").
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

        # 5. List items start a new statement; quotes lose their ">" marker.
        raw = QUOTE_RE.sub("", raw)
        item = LIST_RE.match(raw)
        if item:
            flush()
            add_to_buffer(clean_inline(item.group(1)), line_no)
            continue

        # 6. Normal prose line: add to the current paragraph.
        add_to_buffer(clean_inline(raw), line_no)

    flush()  # don't forget the last paragraph
    return results


def extract_from_file(path):
    """Read a Markdown file from disk and return {"file": ..., "sentences": [...]}."""
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    return {"file": path, "sentences": extract_sentences(text)}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python extractor.py <markdown-file>")
        sys.exit(1)
    with open("output/docs.json", "w", encoding="utf-8") as f:
        json.dump(extract_from_file(sys.argv[1]), f, indent=2)