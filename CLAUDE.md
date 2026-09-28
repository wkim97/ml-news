# ml-news — project notes for Claude & collaborators

Daily **hot-only** AI/ML news digest. Collects from ~20 sources, lets Claude (headless `claude -p`)
pick & summarize only what matters, and emails it every morning via Gmail SMTP. Runs from cron on an
always-on Linux box; nothing needs to stay open.

## Pipeline (`python -m mlnews`)
1. **collect** (`mlnews/collect.py`, stdlib only) — RSS/Atom feeds + HN Algolia + HF trending models +
   HF daily papers + GitHub trending. Window = since last successful run (−3h overlap, max 72h), else `lookback_hours`.
   A failing source is logged and skipped; it never kills the run.
2. **dedupe** — drop URLs sent in the last 14 days (`state/sent.jsonl`); last 7 days of titles go to the prompt as "already sent".
3. **curate** (`mlnews/curate.py` + `prompts/curate.md`) — `claude -p --json-schema ... --allowedTools WebSearch,WebFetch --strict-mcp-config`.
   Uses the logged-in Claude subscription (no API key). Output is validated against `SCHEMA`.
   On failure → `fallback_digest()` (raw top items) so the day is not lost.
4. **render** (`mlnews/render.py`) — HTML with inline CSS only (Gmail strips `<style>`), plus plaintext part.
5. **send** (`mlnews/send.py`) — Gmail SMTP_SSL with an App Password from `.env`.
6. **state** — `state/last_success.json` guards against double-sending the same day (override: `--force`).

Every run keeps `runs/YYYY-MM-DD/{candidates.json,prompt.md,digest.json,digest.html}` — look there first when debugging.
Logs: `logs/YYYY-MM.log`.

## Where to change things
- **Sources / reader profile / limits / model** → `config.toml` (committed). Add a feed with an `[[rss]]` block.
- **Selection criteria, tone, length limits** → `prompts/curate.md`. Placeholders are `str.format` fields — escape literal braces as `{{ }}`.
- **Output shape** → `SCHEMA` in `curate.py` *and* `render.py` together.
- **Secrets** → `.env` only (gitignored). See `.env.example`. Never put credentials in `config.toml` or commit `.env`.

## Commands
```bash
python3 -m mlnews --dry-run      # full pipeline, no email; prints digest + writes runs/<date>/digest.html
python3 -m mlnews --no-curate --dry-run   # collectors only (fast, no Claude)
python3 -m mlnews --force        # send again even if already sent today
bash scripts/install_cron.sh 08:40    # install/update the daily cron line (system timezone)
crontab -l | grep ml-news        # check schedule
```

## Gotchas (learned the hard way)
- Requires Python ≥ 3.11 (`tomllib`). `install_cron.sh` bakes the current `python3`/`claude` PATH into the cron line,
  because cron's PATH is minimal — re-run it if you move conda envs or reinstall `claude`.
- `deepmind.google/blog/rss.xml` returns gzip bytes **without** `Content-Encoding`; `fetch()` sniffs the gzip magic.
- Reddit `.json` endpoints return 403 for anonymous clients → use `/top/.rss?t=day`. Reddit also 429s parallel
  requests, so reddit feeds are fetched serially behind a lock with retry. Occasional 429 is expected and non-fatal.
- Anthropic and Meta AI have no official RSS — we use community mirrors (`Olshansk/rss-feeds`).
- There is no free X/Twitter feed. Proxies: smol.ai AI News (recaps X/Reddit/Discord; may go stale) + the curator's WebSearch sweep.
- `claude -p` output with `--output-format json` puts the schema result in `structured_output`.
- Cron only fires if the machine is on at that time (no catch-up). A run takes ~1–3 min.
- The reference deployment lives on an NTFS (fuseblk) mount with no exec bits → scripts are always invoked as `bash scripts/...`.
