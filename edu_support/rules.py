"""Pure business rules shared by the data generator, the backend and the auditor.

* classify()      - keyword router: ticket text -> domain / category / ambiguity decision
* derive_priority - base priority of the category, raised by deadline proximity / urgency words
* match_topic()   - retrieval of the best KB topic by title-token coverage
* effective_article() - the article version in force at a given instant
"""
import re
from datetime import date, datetime

from .config import (MIN_TOP_SCORE, MIN_MARGIN, MIN_COVERAGE, MIN_MATCHED_TOKENS, PRIORITIES)

_WORD = re.compile(r"[a-z0-9]+(?:[-/][a-z0-9]+)*")
STOP = {"for", "of", "the", "a", "an", "on", "and", "to", "in", "my", "with", "at", "by", "is"}
URGENT_WORDS = {"urgent", "asap", "immediately", "emergency"}


def stem(w: str) -> str:
    """Very light stemmer: plural 's' / 'ies' only (applied identically to text and keywords)."""
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def words(text: str):
    return [stem(w) for w in _WORD.findall((text or "").lower())]


def padded(text: str) -> str:
    return " " + " ".join(words(text)) + " "


# --------------------------------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------------------------------
def prepare_categories(rows):
    """rows: category dicts (DB rows or generator rows).  Returns structures used by classify()."""
    prepared = []
    for r in rows:
        kws = [k for k in (r.get("routing_keywords") or "").split("|") if k.strip()]
        prepared.append({
            "category_id": r["category_id"],
            "domain": r["domain"],
            "level": int(r["level"]),
            "parent": r.get("parent_category_id") or None,
            "keywords": [" " + " ".join(words(k)) + " " for k in kws],
            "raw_keywords": kws,
        })
    return prepared


def classify(text: str, prepared, domain_cat_by_domain=None):
    """Return the routing decision for `text`.

    Scores = number of distinct keyword phrases found.  Domain score = generic (level 1) keywords +
    leaf-specific (level 2) keywords.  The leaf category is the best-scoring leaf of the winning domain;
    if no leaf-specific keyword hit, the domain-level category is used.

    ambiguous  <=>  top domain score < MIN_TOP_SCORE  or  (top - runner_up) < MIN_MARGIN.
    Ambiguous tickets are routed to the general triage category CAT-GEN.
    """
    p = padded(text)
    domain_scores, leaf_scores, matched = {}, {}, {}
    domain_cat = {}
    for c in prepared:
        if c["domain"] == "GEN":
            continue
        hits = [kw.strip() for kw in c["keywords"] if kw in p]
        domain_scores[c["domain"]] = domain_scores.get(c["domain"], 0) + len(hits)
        if c["level"] == 1:
            domain_cat[c["domain"]] = c["category_id"]
        else:
            leaf_scores[c["category_id"]] = (len(hits), c["domain"])
        if hits:
            matched[c["category_id"]] = hits
    ranked = sorted(domain_scores.items(), key=lambda kv: (-kv[1], kv[0]))
    top_domain, top = ranked[0] if ranked else (None, 0)
    second = ranked[1][1] if len(ranked) > 1 else 0
    total = sum(domain_scores.values())
    margin = top - second
    reason = None
    if total == 0:
        reason = "NO_SIGNAL"
    elif top < MIN_TOP_SCORE:
        reason = "LOW_SIGNAL"
    elif margin < MIN_MARGIN:
        reason = "DOMAIN_CONFLICT"
    ambiguous = reason is not None
    category_id, domain = "CAT-GEN", "GEN"
    if not ambiguous:
        domain = top_domain
        best = None
        for c in prepared:                      # prepared order = stable tie-break
            if c["level"] == 2 and c["domain"] == domain:
                n = leaf_scores[c["category_id"]][0]
                if n > 0 and (best is None or n > best[0]):
                    best = (n, c["category_id"])
        category_id = best[1] if best else domain_cat[domain]
    return {
        "ambiguous": ambiguous,
        "reason": reason,
        "domain": domain,
        "category_id": category_id,
        "domain_scores": domain_scores,
        "top_score": top,
        "margin": margin,
        "confidence": round(top / total, 2) if total else 0.0,
        "matched": matched,
    }


# --------------------------------------------------------------------------------------------------
# Priority
# --------------------------------------------------------------------------------------------------
def derive_priority(default_priority: str, created_at: datetime, deadline: date, text: str):
    """Return (priority, reasons).  Never lowers the category default."""
    idx = PRIORITIES.index(default_priority)
    reasons = ["category_default:%s" % default_priority]
    if deadline is not None:
        days = (deadline - created_at.date()).days
        if days <= 2:
            idx = max(idx, PRIORITIES.index("urgent"))
            reasons.append("deadline_within_2_days")
        elif days <= 7:
            idx = max(idx, PRIORITIES.index("high"))
            reasons.append("deadline_within_7_days")
    if URGENT_WORDS & set(_WORD.findall((text or "").lower())):
        idx = max(idx, PRIORITIES.index("high"))
        reasons.append("urgent_keyword")
    return PRIORITIES[idx], reasons


# --------------------------------------------------------------------------------------------------
# Retrieval
# --------------------------------------------------------------------------------------------------
def title_tokens(title: str):
    return [stem(w) for w in re.findall(r"[a-z0-9]+", title.lower()) if w not in STOP]


def prepare_topics(topic_rows):
    """topic_rows: dicts with topic_key, domain, title, category_id."""
    out = []
    for t in topic_rows:
        out.append({**t, "tokens": sorted(set(title_tokens(t["title"])))})
    return out


def match_topic(text: str, topics, domain: str = None):
    """Best KB topic for the text by title-token coverage. Returns dict with found flag."""
    toks = set(stem(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower()))
    best = None
    for i, t in enumerate(topics):
        if domain and t["domain"] != domain:
            continue
        matched = [x for x in t["tokens"] if x in toks]
        cov = len(matched) / len(t["tokens"]) if t["tokens"] else 0.0
        key = (cov, len(matched), -i)
        if best is None or key > best[0]:
            best = (key, t, matched, cov)
    if best is None:
        return {"found": False, "topic_key": None, "coverage": 0.0, "matched": []}
    _, t, matched, cov = best
    found = cov >= MIN_COVERAGE and len(matched) >= MIN_MATCHED_TOKENS
    return {"found": found, "topic_key": t["topic_key"] if found else None,
            "best_topic_key": t["topic_key"], "coverage": round(cov, 2), "matched": matched}


def effective_article(versions, at: datetime):
    """versions: article dicts of one topic (effective_from/effective_to as date objects)."""
    d = at.date()
    for a in versions:
        if a["effective_from"] <= d and (a["effective_to"] is None or d <= a["effective_to"]):
            return a
    return None


# --------------------------------------------------------------------------------------------------
# Claim checking (used by the auditor and by the live API's pre-send validation)
# --------------------------------------------------------------------------------------------------
_ID_RE = re.compile(r"\b(?:KB|POL|TKT|MSG|STF|REQ|SLA|ASG|EVT|FB|TEAM|CAT)-[A-Z0-9-]*\d[A-Z0-9-]*\b")
_VER_RE = re.compile(r"\b(?:version|v)\s?\d+\b", re.I)
_NUM_RE = re.compile(r"\$?\d[\d,]*(?:\.\d+)?")


def numeric_tokens(text: str):
    t = _ID_RE.sub(" ", text or "")
    t = _VER_RE.sub(" ", t)
    return {m.group(0).replace("$", "").replace(",", "") for m in _NUM_RE.finditer(t)}


def unsupported_numbers(answer_text: str, source_texts):
    """Numeric claims in the answer that appear in none of the cited sources."""
    allowed = set()
    for s in source_texts:
        allowed |= numeric_tokens(s)
    return sorted(numeric_tokens(answer_text) - allowed)
