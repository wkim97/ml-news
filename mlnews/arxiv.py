"""arXiv sections of the digest.

1. Most viewed (default on): top-N arXiv papers of the last 3 / 7 / 30 days by alphaXiv views
   (arXiv itself publishes no view counts), each with a one-line core message (one cheap Claude call).
2. Trend summary (default OFF, `trend_enabled`): read ALL abstracts of the latest arXiv mailing and map-reduce
   them into topic trends. Measured 2026-09-28: 548 papers → ~1.0M input / 145k output tokens, ~7 min.
"""
import json
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .collect import clean, fetch, parse_date
from .config import STATE_DIR
from .curate import FIELDS, run_claude

NS = {"arxiv": "http://arxiv.org/schemas/atom", "dc": "http://purl.org/dc/elements/1.1/"}
HISTORY = STATE_DIR / "arxiv_history.jsonl"
ARXIV_ID = re.compile(r"^\d{4}\.\d{4,5}$")


def log(msg: str) -> None:
    print(f"[arxiv] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------- mailing

def fetch_mailing(cfg: dict) -> tuple[str, list[dict]]:
    """Latest announced mailing → (mailing date YYYY-MM-DD, papers). Keeps new + cross-list only."""
    url = "https://rss.arxiv.org/rss/" + "+".join(cfg.get("categories", ["cs.LG"]))
    ch = ET.fromstring(fetch(url)).find("channel")
    mailing = parse_date(ch.findtext("pubDate"))
    papers, seen = [], set()
    for it in ch.findall("item"):
        if it.findtext("arxiv:announce_type", namespaces=NS) not in ("new", "cross"):
            continue
        pid = it.findtext("link", "").rstrip("/").rsplit("/", 1)[-1]
        if pid in seen:
            continue
        seen.add(pid)
        abstract = re.sub(r"^.*?Abstract:\s*", "", it.findtext("description") or "", flags=re.S)
        papers.append({
            "id": pid,
            "title": clean(it.findtext("title"), 300),
            "abstract": clean(abstract, cfg.get("abstract_chars", 2000)),
            "cats": [c.text for c in it.findall("category")],
            "url": f"https://arxiv.org/abs/{pid}",
        })
    return (mailing.strftime("%Y-%m-%d") if mailing else ""), papers


# ---------------------------------------------------------------- map / reduce

MAP_SCHEMA = {
    "type": "object", "required": ["topics", "standouts"], "additionalProperties": False,
    "properties": {
        "topics": {"type": "array", "items": {
            "type": "object", "required": ["label", "field", "count", "ids", "note"], "additionalProperties": False,
            "properties": {
                "label": {"type": "string"}, "field": {"type": "string", "enum": FIELDS},
                "count": {"type": "integer"}, "ids": {"type": "array", "items": {"type": "string"}, "maxItems": 4},
                "note": {"type": "string"},
            }}},
        "standouts": {"type": "array", "maxItems": 3, "items": {
            "type": "object", "required": ["id", "why"], "additionalProperties": False,
            "properties": {"id": {"type": "string"}, "why": {"type": "string"}}}},
    },
}

REDUCE_SCHEMA = {
    "type": "object", "required": ["overview", "trends", "standouts"], "additionalProperties": False,
    "properties": {
        "overview": {"type": "string"},
        "trends": {"type": "array", "items": {
            "type": "object", "required": ["field", "topic", "count", "what", "ids", "rising"], "additionalProperties": False,
            "properties": {
                "field": {"type": "string", "enum": FIELDS}, "topic": {"type": "string"},
                "count": {"type": "integer"}, "what": {"type": "string"},
                "ids": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
                "rising": {"type": "boolean"},
            }}},
        "standouts": {"type": "array", "maxItems": 3, "items": {
            "type": "object", "required": ["id", "why"], "additionalProperties": False,
            "properties": {"id": {"type": "string"}, "why": {"type": "string"}}}},
    },
}

MAP_PROMPT = """You are reading slice {k}/{n} ({m} papers) of today's arXiv mailing in ML-related categories.
Read every abstract and group the papers into research topics.

- Topics must be specific enough to be informative (e.g. "KV-cache compression for long-context inference",
  "diffusion-based VLA policies"), not generic ("LLMs", "computer vision").
- Count every paper in exactly one topic. Put stragglers in a single topic labeled "other".
- field: vision (CV, multimodal, image/video/3D generation) | nlp (LLMs, reasoning, agents, language) |
  robotics (embodied, VLA, manipulation, locomotion) | general (optimization, theory, architectures, infra, eval, safety, other ML).
- ids: up to 4 representative arXiv ids. note: one line (English) on what these papers converge on or what is new.
- standouts: up to 3 papers that look unusually novel or important, with a one-line reason.

Papers (JSON lines: id, title, cats, abstract):
{papers}
"""

REDUCE_PROMPT = """You are writing the arXiv trend section of a daily digest for this reader:
{profile}

Below are topic clusters extracted (in {n} slices) from ALL {total} new papers in the arXiv mailing of {mailing}
(categories: {cats}). The same topic may appear under different labels in different slices — merge them and sum counts.

Write, in {language}:
- overview: 2 short sentences — what dominated today and what is notably new/shifting. ≤ 120 {language} characters total.
- trends: the {max_trends} most informative merged topics (large AND/OR newly emerging), each with field, topic (≤ 30 chars),
  count (merged paper count), what (≤ 70 chars: what these papers are converging on / new idea), ids (1–2 best examples),
  rising (true if clearly larger or new compared with the recent history below). Skip "other".
  Cover multiple fields when the data supports it; don't force it.
- standouts: up to 3 papers from the slice standouts that the reader should actually open, why ≤ 60 chars.
Use only ids that appear in the input.

## Recent history (topic counts from previous mailings)
{history}

## Topic clusters from today's slices
{clusters}

## Slice standouts
{standouts}
"""


def _map(cfg: dict, papers: list[dict]) -> list[dict]:
    size = cfg.get("chunk_size", 120)
    chunks = [papers[i:i + size] for i in range(0, len(papers), size)]

    def one(args):
        k, chunk = args
        body = "\n".join(json.dumps({k2: p[k2] for k2 in ("id", "title", "cats", "abstract")}, ensure_ascii=False)
                         for p in chunk)
        prompt = MAP_PROMPT.format(k=k + 1, n=len(chunks), m=len(chunk), papers=body)
        res, _ = run_claude(prompt, MAP_SCHEMA, model=cfg.get("map_model", "opus"),
                            timeout=cfg.get("timeout_sec", 900), label=f"arxiv-map {k + 1}/{len(chunks)}")
        return res

    with ThreadPoolExecutor(max_workers=min(len(chunks), cfg.get("parallel", 10))) as ex:
        results = list(ex.map(one, enumerate(chunks)))
    log(f"mapped {len(papers)} papers in {len(chunks)} chunks")
    return results


def _history(days: int = 7) -> str:
    if not HISTORY.exists():
        return "(none yet)"
    recs = [json.loads(l) for l in HISTORY.read_text().splitlines() if l.strip()][-days:]
    return "\n".join(f"- {r['mailing']} ({r['total']} papers): "
                     + "; ".join(f"{t['topic']} {t['count']}" for t in r["topics"]) for r in recs) or "(none yet)"


def top_viewed(cfg: dict, interval_days: int) -> list[dict]:
    """alphaXiv's most-viewed arXiv papers for a window ("3 Days" / "7 Days" / "30 Days").

    alphaXiv restricts each window to papers published in it and orders by views over that window.
    Non-arXiv items hosted on alphaXiv (slug ids) and papers outside the configured categories are dropped.
    """
    cats, want, out = set(cfg.get("categories", [])), cfg.get("top_n", 5), []
    for page in range(cfg.get("max_pages", 4)):
        q = urllib.parse.urlencode({"sort": "Views", "interval": f"{interval_days} Days",
                                    "pageNum": page, "pageSize": 50})
        data = json.loads(fetch(f"https://api.alphaxiv.org/papers/v3/feed?{q}", timeout=60))["papers"]
        for p in data:
            pid = p.get("universal_paper_id", "")
            # arXiv papers only, and only if tagged with one of our ML categories (drops physics, math, …)
            if not ARXIV_ID.match(pid) or (cats and not cats & set(p.get("topics") or [])):
                continue
            visits = (p.get("metrics") or {}).get("visits_count") or {}
            out.append({
                "id": pid, "title": clean(p.get("title"), 200),
                # alphaXiv exposes only all-time + 7-day counts → all-time for the 30-day window
                "views": visits.get("all", 0) if interval_days > 7 else visits.get("last_7_days", 0),
                "published": (p.get("first_publication_date") or "")[:10],
                "abstract": clean(p.get("abstract"), 1500),
                "url": f"https://arxiv.org/abs/{pid}", "alphaxiv": f"https://www.alphaxiv.org/abs/{pid}",
            })
            if len(out) >= want:
                return out
        if not data:
            break
    return out


MESSAGE_SCHEMA = {
    "type": "object", "required": ["papers"], "additionalProperties": False,
    "properties": {"papers": {"type": "array", "items": {
        "type": "object", "required": ["id", "message"], "additionalProperties": False,
        "properties": {"id": {"type": "string"}, "message": {"type": "string"}}}}},
}

MESSAGE_PROMPT = """For each arXiv paper below, write its core message in {language}: 1–2 short sentences, ≤ 90 {language}
characters total — the key claim/idea and what it changes. Keep method/model names in their original form.
No filler, no restating the title. Return one entry per id.

{papers}
"""


def arxiv_section(cfg: dict, profile: str, language: str, last_state: dict) -> dict:
    """Build the arXiv part of the digest. Never raises; errors are reported in sec["errors"]."""
    sec = {"mailing": None, "total": 0, "trend": None, "windows": [], "papers": {}, "errors": []}

    # 1) most-viewed per window (freshest first) + one Claude call for the core messages
    try:
        for days in cfg.get("windows", [3, 7, 30]):
            sec["windows"].append({"days": days, "papers": top_viewed(cfg, days)})
        uniq = {p["id"]: p for w in sec["windows"] for p in w["papers"]}
        if uniq:
            body = "\n".join(json.dumps({"id": p["id"], "title": p["title"], "abstract": p["abstract"]},
                                        ensure_ascii=False) for p in uniq.values())
            res, _ = run_claude(MESSAGE_PROMPT.format(language=language, papers=body), MESSAGE_SCHEMA,
                                model=cfg.get("message_model", "opus"), timeout=cfg.get("timeout_sec", 900),
                                label="arxiv-top")
            msg = {x["id"]: x["message"] for x in res["papers"]}
            for w in sec["windows"]:
                for p in w["papers"]:
                    p["message"] = msg.get(p["id"])
                    p.pop("abstract", None)
    except Exception as e:  # noqa: BLE001
        sec["errors"].append(f"top-viewed: {type(e).__name__}: {e}")

    # 2) optional: trend summary over ALL abstracts of the latest mailing (expensive: ~1M tokens/day)
    if cfg.get("trend_enabled", False):
        try:
            mailing, papers = fetch_mailing(cfg)
            sec["mailing"], sec["total"] = mailing, len(papers)
            sec["papers"] = {p["id"]: {"title": p["title"], "url": p["url"]} for p in papers}
            if not papers:
                raise RuntimeError("empty mailing")
            if mailing and mailing == last_state.get("mailing"):
                sec["trend"] = {"skipped": f"새 arXiv 메일링 없음 (마지막: {mailing}, 주말/휴일)"}
            else:
                sliced = _map(cfg, papers)
                clusters = [t for r in sliced for t in r["topics"]]
                standouts = [s for r in sliced for s in r["standouts"]]
                prompt = REDUCE_PROMPT.format(
                    profile=profile, language=language, n=len(sliced), total=len(papers), mailing=mailing,
                    cats=", ".join(cfg.get("categories", [])), max_trends=cfg.get("max_trends", 8),
                    history=_history(), clusters="\n".join(json.dumps(c, ensure_ascii=False) for c in clusters),
                    standouts="\n".join(json.dumps(s, ensure_ascii=False) for s in standouts) or "(none)")
                sec["trend"], _ = run_claude(prompt, REDUCE_SCHEMA, model=cfg.get("reduce_model", "opus"),
                                             timeout=cfg.get("timeout_sec", 900), label="arxiv-reduce")
        except Exception as e:  # noqa: BLE001
            sec["errors"].append(f"trend: {type(e).__name__}: {e}")
    for err in sec["errors"]:
        log(err)
    return sec


def record(sec: dict) -> None:
    """Persist after a successful send: topic history for 'rising' detection + last summarized mailing."""
    STATE_DIR.mkdir(exist_ok=True)
    trend = sec.get("trend") or {}
    if trend.get("trends"):
        with HISTORY.open("a") as f:
            f.write(json.dumps({"mailing": sec["mailing"], "total": sec["total"],
                                "topics": [{"topic": t["topic"], "count": t["count"]} for t in trend["trends"]]},
                               ensure_ascii=False) + "\n")
    state = load_state()
    if trend.get("trends"):
        state["mailing"] = sec["mailing"]
    state["at"] = datetime.now().astimezone().isoformat()
    (STATE_DIR / "arxiv_state.json").write_text(json.dumps(state))


def load_state() -> dict:
    p = STATE_DIR / "arxiv_state.json"
    return json.loads(p.read_text()) if p.exists() else {}
