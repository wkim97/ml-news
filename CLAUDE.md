# ml-news — project notes for Claude & collaborators

Daily **hot-only** AI/ML news digest. Collects from ~20 sources, lets Claude (headless `claude -p`)
pick & summarize only what matters, and emails it every morning via Gmail SMTP. Runs from cron on an
always-on Linux box; nothing needs to stay open.

## Pipeline (`python -m mlnews`)
1. **collect** (`mlnews/collect.py`, stdlib only) — RSS/Atom feeds + HN Algolia + HF trending models +
   HF daily papers + GitHub trending + Bluesky (public API) + X (official API, only if `X_BEARER_TOKEN` is set). Window = since last successful run (−3h overlap, max 72h), else `lookback_hours`.
   A failing source is logged and skipped; it never kills the run.
2. **dedupe** — drop URLs sent in the last 14 days (`state/sent.jsonl`); last 7 days of titles go to the prompt as "already sent".
3. **curate** (`mlnews/curate.py` + `prompts/curate.md`) — `claude -p --json-schema ... --allowedTools WebSearch,WebFetch --strict-mcp-config`.
   Uses the logged-in Claude subscription (no API key). Output is validated against `SCHEMA`.
   Each item has `field` ∈ {vision, nlp, robotics, general}, `category` ∈ {release, paper, tool, industry}, `must_read`.
   On failure → `fallback_digest()` (raw top items) so the day is not lost.
3b. **arXiv** (`mlnews/arxiv.py`, runs concurrently with curate) — top-5 most-viewed arXiv papers for the last
   3 / 7 / 30 days from alphaXiv (`api.alphaxiv.org/papers/v3/feed?sort=Views&interval=N Days`; arXiv has no view
   counts) + one Claude call writing a core message per paper. Only real arXiv ids tagged with a configured ML
   category are kept (alphaXiv also hosts non-arXiv reports with slug ids, and physics papers leak in otherwise).
   Optional `trend_enabled` (OFF): map-reduce over ALL abstracts of the daily mailing — measured 2026-09-28:
   548 papers → ~1.0M input / 145k output tokens, ~7 min (map calls re-send the whole chunk every turn). Off by user decision.
4. **render** (`mlnews/render.py`) — HTML with inline CSS only (Gmail strips `<style>`), plus plaintext part.
   Layout: headline + TL;DR → 🔥 must-read → 👁 Vision / 💬 NLP / 🤖 Robotics / 🧠 General ML (items, then radar one-liners)
   → 📈 arXiv top-5 for 3d / 7d / 30d (a paper already shown in a fresher window becomes a compact line).
5. **send** (`mlnews/send.py`) — Gmail SMTP_SSL with an App Password from `.env`.
6. **state** — `state/last_success.json` guards against double-sending the same day (override: `--force`).

Every run keeps `runs/YYYY-MM-DD/{candidates.json,prompt.md,digest.json,digest.html,usage.json}` — look there first when
debugging. `usage.json` has per-Claude-call model, seconds, input/output tokens and API-equivalent cost.
Typical run (2026-09-28, trend off): 2 calls, ~100 s, ~205k input / 13k output tokens.

**Models**: every Claude call uses the `opus` alias in `config.toml` = always the latest Opus (user decision,
2026-09-28; resolved to `claude-opus-5-5` then). Don't pin a versioned id, switch to "sonnet", or leave it empty
(empty = CLI default, which is not guaranteed to be Opus). `usage.json` records which model actually ran
(calls with WebFetch also list a Haiku model — Claude Code uses it internally to digest fetched pages).
Logs: `logs/YYYY-MM.log`.

## Where to change things
- **Sources / reader profile / limits / model** → `config.toml` (committed). Add a feed with an `[[rss]]` block.
- **Selection criteria, tone, length limits** → `prompts/curate.md`. Placeholders are `str.format` fields — escape literal braces as `{{ }}`.
- **Output shape / fields** → `SCHEMA`+`FIELDS` in `curate.py` *and* `FIELDS` in `render.py` together, plus the field definitions in `prompts/curate.md`.
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
- **X**: no free access as of 2026-09 (nitter instances dead, `syndication.twitter.com` rate-limits after 1 request).
  Official API is pay-per-use (~$0.005/post read, no free tier) → `x_api()` is opt-in via `X_BEARER_TOKEN`;
  `[x].max_reads` is the per-run cost cap. API v2 search has no `min_faves`, so popularity is filtered by the curator.
- **LinkedIn**: no public read API and scraping violates ToS → intentionally not collected; the curator's WebSearch
  sweep looks at x.com / linkedin.com instead.
- **Bluesky** handles in `config.toml` were verified active in 2026-09; many well-known ML people have left or never joined.
  Dead handles are logged and skipped. arXiv bot accounts (arxiv-cs-*.bsky.social) are too noisy — don't add them.
- The daily AINews recap (X/Reddit/Discord) moved from news.smol.ai to the Latent Space feed around 2026-09 — the smol.ai
  feed is stale and was removed. Latent Space gets a large `content_chars` because AINews is our best X proxy.
- Backtest lesson (Jev, launched 2026-09-15 by an unknown startup, HN 1984 pts): it WAS collected but the curator
  demoted it to radar (vague title + unfamiliar name + came with a funding round). The "Outliers" rules in
  `prompts/curate.md` exist to prevent this — keep them when editing the prompt.
- `claude -p` output with `--output-format json` puts the schema result in `structured_output`.
- Cron only fires if the machine is on at that time (no catch-up). A run takes ~1–3 min.
- The reference deployment lives on an NTFS (fuseblk) mount with no exec bits → scripts are always invoked as `bash scripts/...`.
