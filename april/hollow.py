import json
import os
import re
import sys
import time
import tempfile

OPTIONAL_TOKENS = {"count", "level", "size", "num", "number", "val", "value", "setting", "config"}
UNIT_TOKENS = {"b", "kb", "mb", "gb", "tb", "ms", "sec", "secs", "second", "seconds", "min", "mins"}
VALID_UNITS = {
    "s", "sec", "secs", "second", "seconds",
    "ms", "millisecond", "milliseconds",
    "b", "kb", "mb", "gb", "tb",
    "user", "users", "file", "files", "time", "times", "request", "requests", "item", "items"
}

UNIT_CONVERSIONS = {
    "b": ("storage", 1 / (1024 * 1024)),
    "kb": ("storage", 1 / 1024),
    "mb": ("storage", 1.0),
    "gb": ("storage", 1024.0),
    "tb": ("storage", 1024.0 * 1024.0),
    "ms": ("time", 1.0),
    "s": ("time", 1000.0),
    "sec": ("time", 1000.0),
    "secs": ("time", 1000.0),
    "second": ("time", 1000.0),
    "seconds": ("time", 1000.0),
    "user": ("count", 1.0),
    "users": ("count", 1.0),
    "file": ("count", 1.0),
    "files": ("count", 1.0),
    "time": ("count", 1.0),
    "times": ("count", 1.0),
    "request": ("count", 1.0),
    "requests": ("count", 1.0),
    "item": ("count", 1.0),
    "items": ("count", 1.0),
}

DIMENSION_HINTS = {
    "size": "storage",
    "memory": "storage",
    "cache": "storage",
    "buffer": "storage",
    "timeout": "time",
    "delay": "time",
    "interval": "time",
    "duration": "time",
    "ttl": "time",
    "count": "count",
    "retries": "count",
    "retry": "count",
    "users": "count",
}

RELATION_WORDS = {
    "after", "before", "every", "since", "until", "within",
    "retry", "retries", "retried", "tried", "waits", "waited", "than"
}

ALIASES = {
    "max": ("max", "maximum", "up to", "at most", "larger than", "bigger than", "more than", "exceed", "exceeds", "limit"),
    "min": ("min", "minimum", "at least", "smaller than", "less than", "fewer than"),
}

def stem_word(w):
    w = w.lower()
    if len(w) <= 3:
        return w
    if w.endswith("ied") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("ing") and len(w) > 5:
        base = w[:-3]
        if len(base) >= 2 and base[-1] == base[-2]:
            base = base[:-1]
        return base
    if w.endswith("ed") and len(w) > 4:
        base = w[:-2]
        if len(base) >= 2 and base[-1] == base[-2]:
            base = base[:-1]
        return base
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        return w[:-1]
    return w

def symbol_words(symbol):
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", symbol)
    return [w.lower() for w in re.split(r"[_\s]+", spaced) if w]

def text_stems(text):
    tokens = re.findall(r"[a-z]+", text.lower())
    return set(tokens) | {stem_word(t) for t in tokens}

def symbol_in_text(symbol, text):
    if re.search(r"(?<![A-Za-z0-9_])" + re.escape(symbol) + r"(?![A-Za-z0-9_])", text):
        return "exact"
    if len(symbol) <= 2:
        return None

    low = text.lower()
    words = symbol_words(symbol)

    if "port" in words and re.search(r"[a-z][a-z0-9+.-]*://[^\s:/]+:\d+", low):
        return "words"

    non_unit_words = [w for w in words if w not in UNIT_TOKENS]
    core_words = [w for w in non_unit_words if w not in OPTIONAL_TOKENS] or non_unit_words
    stems = text_stems(low)

    def matches_concept(word):
        candidates = ALIASES.get(word, (word,))
        for cand in candidates:
            if " " in cand:
                if re.search(r"\b" + re.escape(cand) + r"\b", low):
                    return True
            else:
                if cand in stems or stem_word(cand) in stems:
                    return True
        return False

    if all(matches_concept(w) for w in core_words):
        return "words"
    return None

def infer_symbol_unit(symbol):
    words = symbol_words(symbol)
    if words and words[-1] in UNIT_CONVERSIONS:
        return words[-1]
    return ""

def infer_symbol_dimension(symbol):
    words = symbol_words(symbol)
    sym_unit = infer_symbol_unit(symbol)
    if sym_unit in UNIT_CONVERSIONS:
        return UNIT_CONVERSIONS[sym_unit][0]
    for w in reversed(words):
        if w in DIMENSION_HINTS:
            return DIMENSION_HINTS[w]
    return ""

def find_matched_value(target_value, text, symbol=""):
    if target_value is None:
        return False, None, ""

    val_str = str(target_value)
    expected_dim = infer_symbol_dimension(symbol)

    m = re.search(r"(?<![\w.])" + re.escape(val_str) + r"(?![\w]|\.\d)", text)
    if m:
        unit_m = re.search(re.escape(val_str) + r"\s+([A-Za-z]+)", text)
        raw_unit = unit_m.group(1) if (unit_m and unit_m.group(1).lower() in VALID_UNITS) else ""
        if raw_unit and expected_dim:
            doc_dim = UNIT_CONVERSIONS.get(raw_unit.lower(), ("", 0))[0]
            if doc_dim and doc_dim != expected_dim:
                return False, None, ""
        return True, val_str, raw_unit

    sym_unit = infer_symbol_unit(symbol)
    if sym_unit in UNIT_CONVERSIONS:
        try:
            target_num = float(val_str)
            target_dim, target_mult = UNIT_CONVERSIONS[sym_unit]
            target_base = target_num * target_mult

            for num_m in re.finditer(r"(?<![\w.])(\d+(?:\.\d+)?)\s*([A-Za-z]+)(?![\w])", text):
                doc_num = float(num_m.group(1))
                doc_unit_raw = num_m.group(2)
                doc_unit_low = doc_unit_raw.lower()
                if doc_unit_low in UNIT_CONVERSIONS:
                    doc_dim, doc_mult = UNIT_CONVERSIONS[doc_unit_low]
                    if doc_dim == target_dim and abs((doc_num * doc_mult) - target_base) < 1e-6:
                        return True, f"{num_m.group(1)} {doc_unit_raw}", doc_unit_raw
        except ValueError:
            pass

    return False, None, ""

def value_is_bound_to_symbol(symbol, value_display, text):
    low = text.lower()
    sym = None
    for cand in [symbol.lower()] + symbol_words(symbol):
        if cand in OPTIONAL_TOKENS or cand in UNIT_TOKENS:
            continue
        sym = re.search(r"(?<![a-z0-9])" + re.escape(stem_word(cand)), low)
        if sym:
            break

    num_part = str(value_display).split()[0]
    val = re.search(r"(?<![\w.])" + re.escape(num_part) + r"(?![\w]|\.\d)", low)
    if not sym or not val:
        return True

    a, b = sorted((sym.end() if sym.start() < val.start() else val.end(),
                   val.start() if sym.start() < val.start() else sym.start()))
    between = re.findall(r"[a-z]+", low[a:b])
    before_value = re.findall(r"[a-z]+", low[:val.start()])[-2:]
    context_words = set(between + before_value)

    if "than" in context_words and any(w in {"larger", "bigger", "more", "smaller", "less", "fewer"} for w in before_value):
        return True

    return not (RELATION_WORDS & context_words)

def is_phrase(value):
    return bool(value) and len(re.findall(r"[A-Za-z]+", str(value))) >= 2

def phrase_matches(phrase, text):
    if not phrase:
        return False, None

    words = [re.escape(w) for w in str(phrase).split()]
    pattern = r"(?<![A-Za-z0-9])" + r"\s+".join(words) + r"(?![A-Za-z0-9])"
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        return True, m.group(0)

    parts = str(phrase).strip().split()
    if len(parts) == 2 and all(p.isalpha() for p in parts):
        verb, obj = parts[0].lower(), re.escape(parts[1])
        past_verb = verb + ("d" if verb.endswith("e") else "ed")
        passive_re = r"\b" + obj + r"\b[^.!?]*?\b" + re.escape(past_verb) + r"\b"
        pm = re.search(passive_re, text, re.IGNORECASE)
        if pm:
            return True, pm.group(0)

    return False, None

def analyse_phrase(change, sentence, doc_file):
    text = sentence["text"]
    old, new = change.get("old_value"), change.get("new_value")
    has_old, matched_old = phrase_matches(old, text)
    has_new, matched_new = phrase_matches(new, text)

    if has_old == has_new:
        return None

    names_symbol = symbol_in_text(change["symbol"], text) == "exact"
    if has_new:
        status, suggestion = "no_drift", None
    else:
        status = "confirmed_drift" if names_symbol else "potential_drift"

        def keep_case(m):
            new_text = str(new)
            return (new_text[:1].upper() + new_text[1:]) if m.group(0)[:1].isupper() else new_text

        exact_pattern = re.escape(str(old)).replace(r"\ ", r"\s+")
        if re.search(exact_pattern, text, flags=re.IGNORECASE):
            fixed = re.sub(exact_pattern, keep_case, text, flags=re.IGNORECASE)
            suggestion = 'Update the text to: "{}"'.format(fixed)
        else:
            suggestion = 'Update "{}" to reflect "{}".'.format(matched_old, new)

    return {
        "file": doc_file,
        "line": sentence["line"],
        "documented_statement": text,
        "section": sentence.get("section", ""),
        "symbol": change["symbol"],
        "documented_value": matched_old if has_old else matched_new,
        "source_value": new,
        "source_file": change.get("file"),
        "match_type": "symbol+phrase" if names_symbol else "phrase",
        "status": status,
        "suggestion": suggestion,
    }

def analyse(change, sentence, doc_file):
    text = sentence["text"]
    change_type = change.get("change_type", "value_changed")
    old, new = change.get("old_value"), change.get("new_value")

    if change_type == "removed":
        how = symbol_in_text(change["symbol"], text)
        if how is None:
            return None
        return {
            "file": doc_file,
            "line": sentence["line"],
            "documented_statement": text,
            "section": sentence.get("section", ""),
            "symbol": change["symbol"],
            "documented_value": old,
            "source_value": None,
            "source_file": change.get("file"),
            "match_type": how,
            "status": "confirmed_drift" if how == "exact" else "potential_drift",
            "suggestion": "Remove or update documentation for deleted symbol {}.".format(change["symbol"]),
        }

    if is_phrase(old) or is_phrase(new):
        return analyse_phrase(change, sentence, doc_file)

    how = symbol_in_text(change["symbol"], text)
    if how is None:
        return None

    has_old, doc_old_disp, old_unit = find_matched_value(old, text, change["symbol"])
    has_new, doc_new_disp, _ = find_matched_value(new, text, change["symbol"])

    if has_new and not has_old:
        status = "no_drift"
    elif has_old and not has_new:
        strong = how == "exact" and sentence.get("kind") == "table_row"
        status = "confirmed_drift" if strong else "potential_drift"
        if not value_is_bound_to_symbol(change["symbol"], doc_old_disp, text):
            status = "needs_review"
    else:
        return None

    suggestion = None
    if status == "needs_review":
        suggestion = "Check manually: this sentence mentions {} and {}, but the {} may not be the {} setting.".format(
            change["symbol"], doc_old_disp, doc_old_disp, change["symbol"])
    elif status != "no_drift":
        if " " in str(doc_old_disp):
            sym_unit = infer_symbol_unit(change["symbol"]).upper()
            suggestion = "Update {} from {} ({} {}) to {} {}.".format(
                change["symbol"], doc_old_disp, old, sym_unit, new, sym_unit)
        else:
            suggestion = "Update {} from {} to {}{}.".format(
                change["symbol"], old, new, (" " + old_unit) if old_unit else "")

    return {
        "file": doc_file,
        "line": sentence["line"],
        "documented_statement": text,
        "section": sentence.get("section", ""),
        "symbol": change["symbol"],
        "documented_value": doc_old_disp if has_old else doc_new_disp,
        "source_value": new,
        "source_file": change.get("file"),
        "match_type": how,
        "status": status,
        "suggestion": suggestion,
    }

def find_findings(changes_json, docs_json):
    findings = []
    for change in changes_json["changes"]:
        for sentence in docs_json["sentences"]:
            f = analyse(change, sentence, docs_json["file"])
            if f:
                findings.append(f)
    return {"findings": findings}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHANGES_FILE = os.environ.get("April_CHANGES_FILE",r"C:\Users\Asus\OneDrive\Desktop\april\PS3_DocuGoSync\CPP_engine\output\changes.json")
RAW_FILE = os.environ.get("April_RAW_FILE", os.path.join(BASE_DIR, "raw.json"))
VERDICT_FILE = os.environ.get("April_VERDICT_FILE", os.path.join(BASE_DIR, "verdict.json"))
POLL_SECONDS = float(os.environ.get("April_POLL_SECONDS", "1.0"))

def file_signature(path):
    try:
        stat = os.stat(path)
        return (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None

def atomic_write_json(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    fd, temp_path = tempfile.mkstemp(prefix=".verdict-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

def load_ready_inputs():
    for path in (CHANGES_FILE, RAW_FILE):
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            return None

    with open(CHANGES_FILE, "r", encoding="utf-8") as handle:
        changes = json.load(handle)
    with open(RAW_FILE, "r", encoding="utf-8") as handle:
        docs = json.load(handle)

    if not isinstance(changes, dict) or not isinstance(changes.get("changes"), list):
        raise ValueError("changes.json must contain a 'changes' array")
    if not isinstance(docs, dict) or not isinstance(docs.get("sentences"), list):
        raise ValueError("raw.json must contain a 'sentences' array")

    if len(changes["changes"]) == 0 or len(docs["sentences"]) == 0:
        return None

    return changes, docs

def watch_for_inputs():
    last_processed_signature = None
    last_reported = None
    print("Comparer watching for inputs:", flush=True)
    print("  changes: {}".format(CHANGES_FILE), flush=True)
    print("  raw:     {}".format(RAW_FILE), flush=True)
    print("  output:  {}".format(VERDICT_FILE), flush=True)

    while True:
        try:
            changes_sig = file_signature(CHANGES_FILE)
            raw_sig = file_signature(RAW_FILE)
            current_signature = (changes_sig, raw_sig)

            if changes_sig is None or raw_sig is None:
                status = "Waiting for changes.json and non-empty raw.json..."
                if status != last_reported:
                    print(status, flush=True)
                    last_reported = status
            elif current_signature != last_processed_signature:
                ready = load_ready_inputs()
                if ready is None:
                    status = "Inputs found, but changes or extracted statements are empty; waiting..."
                    if status != last_reported:
                        print(status, flush=True)
                        last_reported = status
                else:
                    changes, docs = ready
                    result = find_findings(changes, docs)
                    atomic_write_json(VERDICT_FILE, result)
                    last_processed_signature = current_signature
                    last_reported = None
                    print("Compared {} change(s) against {} extracted statement(s); wrote {} finding(s).".format(
                        len(changes["changes"]), len(docs["sentences"]), len(result["findings"])
                    ), flush=True)
        except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            status = "Comparer waiting for valid input: {}".format(exc)
            if status != last_reported:
                print(status, flush=True)
                last_reported = status
        except Exception as exc:
            status = "Comparer watcher error: {}".format(exc)
            if status != last_reported:
                print(status, flush=True)
                last_reported = status

        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    watch_for_inputs()