"""Persistent state: what was sent (for dedupe/history) and when the last successful run was."""
import json
from datetime import datetime, timedelta

from .config import STATE_DIR

SENT = STATE_DIR / "sent.jsonl"
LAST = STATE_DIR / "last_success.json"


def _sent_records(days: int) -> list[dict]:
    if not SENT.exists():
        return []
    cutoff = (datetime.now().astimezone() - timedelta(days=days)).isoformat()
    recs = [json.loads(l) for l in SENT.read_text().splitlines() if l.strip()]
    return [r for r in recs if r["at"] >= cutoff]


def recent_urls(days: int = 14) -> set[str]:
    return {u.rstrip("/") for r in _sent_records(days) for u in r["urls"]}


def recent_titles(days: int = 7) -> list[str]:
    return [f'{r["at"][:10]} {r["title"]}' for r in _sent_records(days)]


def record_sent(digest: dict, now: datetime) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    with SENT.open("a") as f:
        for it in digest.get("items", []):
            f.write(json.dumps({"at": now.isoformat(), "title": it["title"],
                                "urls": [l["url"] for l in it["links"]]}, ensure_ascii=False) + "\n")
        for r in digest.get("radar", []):
            f.write(json.dumps({"at": now.isoformat(), "title": r["title"], "urls": [r["url"]]},
                               ensure_ascii=False) + "\n")
    LAST.write_text(json.dumps({"at": now.isoformat()}))


def last_success() -> datetime | None:
    if not LAST.exists():
        return None
    return datetime.fromisoformat(json.loads(LAST.read_text())["at"])
