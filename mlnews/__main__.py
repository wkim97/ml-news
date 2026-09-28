"""Entry point: python -m mlnews [--dry-run] [--force] [--no-curate]

collect -> dedupe against sent history -> curate with Claude -> render -> send -> record state.
Artifacts for each run are kept in runs/YYYY-MM-DD/ for debugging.
"""
import argparse
import fcntl
import json
import sys
import traceback
from datetime import datetime, timedelta

from concurrent.futures import ThreadPoolExecutor

from . import arxiv, state
from .collect import collect_all
from .config import RUNS_DIR, STATE_DIR, load_config, load_env
from .curate import USAGE, build_prompt, curate
from .render import subject, to_html, to_text
from .send import send_email

MAX_WINDOW_H = 72  # if the PC was off for days, don't dig further back than this


def fallback_digest(candidates: list[dict], err: str) -> dict:
    """Used when curation fails: raw, uncurated top picks so the day isn't lost."""
    def top(src, key, n):
        xs = [c for c in candidates if c["source"] == src]
        xs.sort(key=lambda c: (c.get("extra") or {}).get(key) or 0, reverse=True)
        return xs[:n]
    picks = [c for c in candidates if c["kind"] == "lab"][:5]
    picks += top("HF Daily Papers", "upvotes", 5) + top("Hacker News", "points", 5) + top("HF Trending Models", "trending", 3)
    return {
        "headline": "⚠️ 큐레이션 실패 — 원본 상위 항목",
        "tldr": [f"Claude 큐레이션 실패: {err[:150]}"],
        "items": [],
        "radar": [{"title": f'[{c["source"]}] {c["title"]}', "url": c["url"]} for c in picks],
    }


def main() -> int:
    ap = argparse.ArgumentParser(prog="mlnews")
    ap.add_argument("--dry-run", action="store_true", help="don't send email; write runs/<date>/digest.html")
    ap.add_argument("--force", action="store_true", help="run even if today's digest was already sent")
    ap.add_argument("--no-curate", action="store_true", help="skip Claude; use raw fallback digest")
    args = ap.parse_args()

    load_env()
    cfg = load_config()
    STATE_DIR.mkdir(exist_ok=True)
    lock = open(STATE_DIR / ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("another run is in progress; exiting", file=sys.stderr)
        return 0

    now = datetime.now().astimezone()
    last = state.last_success()
    if last and last.date() == now.date() and not (args.force or args.dry_run):
        print(f"already sent today at {last:%H:%M}; use --force to resend", file=sys.stderr)
        return 0

    run_dir = RUNS_DIR / now.strftime("%Y-%m-%d")
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        if last:
            since = max(now - timedelta(hours=MAX_WINDOW_H), last - timedelta(hours=3))
        else:
            since = now - timedelta(hours=cfg["digest"].get("lookback_hours", 36))
        window = f"from {since:%Y-%m-%d %H:%M} to {now:%Y-%m-%d %H:%M %Z}"
        print(f"[main] window {window}", file=sys.stderr, flush=True)

        candidates, status = collect_all(cfg, since)
        sent = state.recent_urls()
        candidates = [c for c in candidates if c["url"].rstrip("/") not in sent]
        (run_dir / "candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=1))
        print(f"[main] {len(candidates)} candidates", file=sys.stderr, flush=True)

        # news curation and the arXiv section are independent Claude jobs → run them concurrently
        ax_cfg = cfg.get("arxiv", {})
        pool = ThreadPoolExecutor(max_workers=2)
        ax_future = None
        if ax_cfg.get("enabled", True) and not args.no_curate:
            ax_future = pool.submit(arxiv.arxiv_section, ax_cfg, cfg["profile"]["description"].strip(),
                                    cfg["profile"].get("language", "English"), arxiv.load_state())

        meta, digest = {}, None
        if not args.no_curate:
            prompt = build_prompt(cfg, candidates, state.recent_titles(), window)
            (run_dir / "prompt.md").write_text(prompt)
            try:
                digest, meta = curate(cfg, prompt)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                digest = fallback_digest(candidates, str(e))
        else:
            digest = fallback_digest(candidates, "--no-curate")
        ax = ax_future.result() if ax_future else None
        pool.shutdown()
        if ax:
            digest["arxiv"] = ax
        (run_dir / "digest.json").write_text(json.dumps(digest, ensure_ascii=False, indent=1))
        (run_dir / "usage.json").write_text(json.dumps(USAGE, indent=1))
        tok_in = sum(u["input_tokens"] for u in USAGE)
        tok_out = sum(u["output_tokens"] for u in USAGE)
        print(f"[main] claude: {len(USAGE)} calls, in {tok_in:,} / out {tok_out:,} tokens", file=sys.stderr, flush=True)

        failed = [k for k, v in status.items() if isinstance(v, str)] + (["arXiv"] if ax and ax["errors"] else [])
        footer = (f"{len(candidates)} candidates from {len(status) - len(failed)}/{len(status)} sources"
                  + (f" · failed: {', '.join(failed)}" if failed else "")
                  + (f" · {meta.get('num_turns')} turns, {(meta.get('duration_ms') or 0) / 1000:.0f}s" if meta else ""))
        subj = subject(cfg, digest, now)
        html, text = to_html(digest, now, footer), to_text(digest, now, footer)
        (run_dir / "digest.html").write_text(html)
        print(f"[main] subject: {subj}", file=sys.stderr, flush=True)

        if args.dry_run:
            print(f"[main] dry run — wrote {run_dir / 'digest.html'}", file=sys.stderr)
            print(text)
            return 0
        send_email(subj, html, text)
        state.record_sent(digest, now)
        if ax:
            arxiv.record(ax)
        print("[main] sent", file=sys.stderr)
        return 0
    except Exception:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        if not args.dry_run:
            try:
                send_email("[ML News] ⚠️ 실행 실패", f"<pre>{tb}</pre>", tb)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
