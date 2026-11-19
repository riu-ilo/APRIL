"""
DocuGoSync - Stage 2/3: match code changes to documentation statements.
"""

import json
import re
import sys

OPTIONAL_TOKENS = {"count", "level", "size", "num", "number", "val", "value", "setting", "config"}
UNIT_TOKENS = {"b", "kb", "mb", "gb", "tb", "ms", "sec", "secs", "second", "seconds", "min", "mins"}
VALID_UNITS = {
    "s", "sec", "secs", "second", "seconds",
    "ms", "millisecond", "milliseconds",
    "b", "kb", "mb", "gb", "tb",
    "user", "users", "file", "files", "time", "times", "request", "requests", "item", "items"
}

UNIT_CONVERSIONS = {
    # Storage -> base MB
    "b": ("storage", 1 / (1024 * 1024)),
    "kb": ("storage", 1 / 1024),
    "mb": ("storage", 1.0),
    "gb": ("storage", 1024.0),
    "tb": ("storage", 1024.0 * 1024.0),
    # Time -> base ms
    "ms": ("time", 1.0),
    "s": ("time", 1000.0),
    "sec": ("time", 1000.0),
    "secs": ("time", 1000.0),
    "second": ("time", 1000.0),
    "seconds": ("time", 1000.0),
    # Count -> discrete items
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

    # 1. Exact whole-token match (guarding against conflicting unit dimensions like "10 files" for MAX_FILE_SIZE)
    m = re.search(r"(?<![\w.])" + re.escape(val_str) + r"(?![\w]|\.\d)", text)
    if m:
        unit_m = re.search(re.escape(val_str) + r"\s+([A-Za-z]+)", text)
        raw_unit = unit_m.group(1) if (unit_m and unit_m.group(1).lower() in VALID_UNITS) else ""
        if raw_unit and expected_dim:
            doc_dim = UNIT_CONVERSIONS.get(raw_unit.lower(), ("", 0))[0]
            if doc_dim and doc_dim != expected_dim:
                return False, None, ""
        return True, val_str, raw_unit

    # 2. Unit-equivalent numeric match (e.g., 512 MB in code vs 0.5 GB in doc)
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


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python comparer.py <changes.json> <docs.json>")
        sys.exit(1)
    with open(sys.argv[1], encoding="utf-8") as a, open(sys.argv[2], encoding="utf-8") as b:
        result = find_findings(json.load(a), json.load(b))
    with open("output/verdict.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"Done: wrote {len(result['findings'])} findings to verdict.json")