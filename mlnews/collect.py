"""Fetch candidate items from all configured sources. Stdlib only.

Every candidate is a dict: source, kind, title, url, published (ISO or ""), summary, extra.
A failing source is logged and skipped — it never kills the run.
"""
import gzip
import html
import json
import time
import re
import sys
import urllib.parse
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

UA = "Mozilla/5.0 (X11; Linux x86_64) ml-news-digest/0.1 (+https://github.com)"
TIMEOUT = 20


def log(msg: str) -> None:
    print(f"[collect] {msg}", file=sys.stderr, flush=True)


def fetch(url: str, retries: int = 3, timeout: int = TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            # some servers (e.g. deepmind.google) send gzip without Content-Encoding
            return gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < retries - 1:
                time.sleep(10 * (attempt + 1))
                continue
            raise
        except TimeoutError:
            if attempt < retries - 1:
                continue
            raise
    raise RuntimeError("unreachable")


def clean(text: str | None, limit: int = 400) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el, *names):
    for c in el:
        if _local(c.tag) in names:
            return c
    return None


_reddit_lock = __import__("threading").Lock()


def rss(src: dict, since: datetime) -> list[dict]:
    if "reddit.com" in src["url"]:
        with _reddit_lock:  # reddit rate-limits parallel anonymous requests
            raw = fetch(src["url"])
            time.sleep(6)
    else:
        raw = fetch(src["url"])
    root = ET.fromstring(raw)
    entries = [e for e in root.iter() if _local(e.tag) in ("item", "entry")]
    content_chars = src.get("content_chars", 400)
    out = []
    for e in entries:
        title = _child(e, "title")
        link = _child(e, "link")
        url = ""
        if link is not None:
            url = link.get("href") or (link.text or "")
        date_el = _child(e, "pubDate", "published", "updated", "date")
        published = parse_date(date_el.text if date_el is not None else None)
        if published and published < since:
            continue
        body = _child(e, "encoded", "content", "description", "summary")
        out.append({
            "source": src["name"],
            "kind": src.get("kind", "newsletter"),
            "title": clean(title.text if title is not None else "", 200),
            "url": url.strip(),
            "published": published.isoformat() if published else "",
            "summary": clean(body.text if body is not None else "", content_chars),
        })
    return out[: src.get("max_items", 12)]


def hackernews(cfg: dict, since: datetime) -> list[dict]:
    q = urllib.parse.urlencode({
        "tags": "story",
        "numericFilters": f"created_at_i>{int(since.timestamp())},points>{cfg.get('min_points', 100)}",
        "hitsPerPage": 100,
    })
    data = json.loads(fetch(f"https://hn.algolia.com/api/v1/search?{q}"))
    return [{
        "source": "Hacker News",
        "kind": "community",
        "title": h["title"],
        "url": h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}",
        "published": h.get("created_at", ""),
        "summary": "",
        "extra": {"points": h["points"], "comments": h.get("num_comments"),
                  "discussion": f"https://news.ycombinator.com/item?id={h['objectID']}"},
    } for h in data["hits"]]


def hf_models(cfg: dict, since: datetime) -> list[dict]:
    q = {"sort": "trendingScore", "limit": cfg.get("limit", 40)}
    if cfg.get("pipeline_tag"):
        q["pipeline_tag"] = cfg["pipeline_tag"]
    data = json.loads(fetch("https://huggingface.co/api/models?" + urllib.parse.urlencode(q)))
    exclude = re.compile(cfg.get("exclude_regex", "$^"))
    cutoff = datetime.now(timezone.utc) - timedelta(days=cfg.get("max_age_days", 14))
    out = []
    for m in data:
        created = parse_date(m.get("createdAt"))
        if exclude.search(m["id"]) or (created and created < cutoff):
            continue
        out.append({
            "source": cfg.get("label", "HF Trending Models"),
            "kind": "community",
            "title": m["id"],
            "url": f"https://huggingface.co/{m['id']}",
            "published": created.isoformat() if created else "",
            "summary": "",
            "extra": {"trending": m.get("trendingScore"), "likes": m.get("likes"),
                      "downloads": m.get("downloads"), "task": m.get("pipeline_tag")},
        })
    return out


def hf_papers(cfg: dict, since: datetime) -> list[dict]:
    data = json.loads(fetch("https://huggingface.co/api/daily_papers?limit=100"))
    data.sort(key=lambda p: p.get("paper", {}).get("upvotes", 0), reverse=True)
    out = []
    for p in data[: cfg.get("limit", 25)]:
        paper = p.get("paper", {})
        out.append({
            "source": "HF Daily Papers",
            "kind": "community",
            "title": clean(paper.get("title") or p.get("title"), 200),
            "url": f"https://huggingface.co/papers/{paper.get('id')}",
            "published": p.get("publishedAt", ""),
            "summary": clean(paper.get("summary"), 350),
            "extra": {"upvotes": paper.get("upvotes"), "arxiv": f"https://arxiv.org/abs/{paper.get('id')}"},
        })
    return out


def github_trending(cfg: dict, since: datetime) -> list[dict]:
    page = fetch("https://github.com/trending?since=daily").decode("utf-8", "replace")
    out = []
    for art in re.findall(r'<article class="Box-row">(.*?)</article>', page, re.S):
        repo = re.search(r'<h2[^>]*>\s*<a[^>]*href="/([^"]+)"', art, re.S)
        if not repo:
            continue
        desc = re.search(r'<p class="[^"]*col-9[^"]*"[^>]*>(.*?)</p>', art, re.S)
        today = re.search(r"([\d,]+) stars? today", art)
        out.append({
            "source": "GitHub Trending",
            "kind": "community",
            "title": repo.group(1).strip(),
            "url": f"https://github.com/{repo.group(1).strip()}",
            "published": "",
            "summary": clean(desc.group(1) if desc else "", 250),
            "extra": {"stars_today": today.group(1) if today else None},
        })
    return out[: cfg.get("limit", 25)]


def collect_all(cfg: dict, since: datetime) -> tuple[list[dict], dict]:
    """Returns (candidates, per-source status)."""
    jobs = [(s["name"], rss, s) for s in cfg.get("rss", [])]
    for key, fn, label in [("hackernews", hackernews, "Hacker News"),
                           ("hf_models", hf_models, "HF Trending Models"),
                           ("hf_models_robotics", hf_models, "HF Trending Robotics"),
                           ("alphaxiv_topics", alphaxiv_topics, "alphaXiv per-field"),
                           ("hf_papers", hf_papers, "HF Daily Papers"),
                           ("github_trending", github_trending, "GitHub Trending"),
                           ("bluesky", bluesky, "Bluesky"),
                           ("x", x_api, "X")]:
        if key == "x" and not __import__("os").environ.get("X_BEARER_TOKEN", "").strip():
            continue
        if cfg.get(key, {}).get("enabled", True):
            jobs.append((label, fn, cfg.get(key, {})))

    status, items = {}, []

    def run(job):
        name, fn, c = job
        try:
            res = fn(c, since)
            return name, res, None
        except Exception as e:  # noqa: BLE001 — one bad source must not kill the run
            return name, [], f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=8) as ex:
        for name, res, err in ex.map(run, jobs):
            status[name] = err or len(res)
            if err:
                log(f"FAIL {name}: {err}")
            items.extend(res)

    # dedupe by url
    seen, uniq = set(), []
    for it in items:
        key = it["url"].split("#")[0].rstrip("/")
        if key and key not in seen:
            seen.add(key)
            uniq.append(it)
    return uniq, status


def bluesky(cfg: dict, since: datetime) -> list[dict]:
    """Posts + reposts (no replies) from followed accounts via the public AppView API (no auth)."""
    out = []
    for handle in cfg.get("accounts", []):
        q = urllib.parse.urlencode({"actor": handle, "limit": 30, "filter": "posts_no_replies"})
        try:
            feed = json.loads(fetch(f"https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?{q}"))["feed"]
        except Exception as e:  # noqa: BLE001 — skip a dead handle, keep the rest
            log(f"bluesky {handle}: {type(e).__name__}: {e}")
            continue
        for f in feed:
            post = f["post"]
            created = parse_date(post["record"].get("createdAt"))
            if created and created < since:
                continue
            author = post["author"]["handle"]
            embed = (post.get("embed") or {}).get("external") or {}
            out.append({
                "source": "Bluesky",
                "kind": "community",
                "title": clean(post["record"].get("text"), 280) or embed.get("title", ""),
                "url": f"https://bsky.app/profile/{author}/post/{post['uri'].rsplit('/', 1)[-1]}",
                "published": created.isoformat() if created else "",
                "summary": clean(embed.get("title"), 200),
                "extra": {"by": author, "reposted_by": handle if "reason" in f else None,
                          "likes": post.get("likeCount"), "reposts": post.get("repostCount"),
                          "link": embed.get("uri")},
            })
    return out


def x_api(cfg: dict, since: datetime) -> list[dict]:
    """Recent original posts from followed X accounts via the official API (pay-per-read).

    Enabled only when X_BEARER_TOKEN is set. `max_reads` caps posts read per run = cost cap
    (at $0.005/read, 100 reads ≈ $0.50/run).
    """
    import os
    token = os.environ.get("X_BEARER_TOKEN", "").strip()
    if not token:
        return []
    accounts, budget = cfg.get("accounts", []), cfg.get("max_reads", 100)
    # recent search queries are limited to 512 chars → split the account list into chunks
    chunks, cur = [], []
    for a in accounts:
        if len(" OR ".join(f"from:{x}" for x in cur + [a])) > 440:
            chunks.append(cur)
            cur = []
        cur.append(a)
    if cur:
        chunks.append(cur)
    per_chunk = max(10, budget // max(1, len(chunks)))
    out = []
    for chunk in chunks:
        query = "(" + " OR ".join(f"from:{a}" for a in chunk) + ") -is:reply -is:retweet"
        q = urllib.parse.urlencode({
            "query": query, "max_results": min(100, per_chunk), "sort_order": "relevancy",
            "start_time": since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tweet.fields": "created_at,public_metrics,author_id,entities",
            "expansions": "author_id", "user.fields": "username",
        })
        req = urllib.request.Request(f"https://api.x.com/2/tweets/search/recent?{q}",
                                     headers={"Authorization": f"Bearer {token}", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read())
        users = {u["id"]: u["username"] for u in data.get("includes", {}).get("users", [])}
        for t in data.get("data", []):
            name = users.get(t["author_id"], "i")
            m = t.get("public_metrics", {})
            links = [u.get("expanded_url") for u in (t.get("entities") or {}).get("urls", [])
                     if "x.com" not in (u.get("expanded_url") or "")]
            out.append({
                "source": "X",
                "kind": "community",
                "title": clean(t["text"], 280),
                "url": f"https://x.com/{name}/status/{t['id']}",
                "published": t.get("created_at", ""),
                "summary": "",
                "extra": {"by": name, "likes": m.get("like_count"), "reposts": m.get("retweet_count"),
                          "link": links[0] if links else None},
            })
    return out


def alphaxiv_topics(cfg: dict, since: datetime) -> list[dict]:
    """Most-viewed recent arXiv papers per category (e.g. cs.RO) — fields that never top the global charts."""
    out = []
    for cat in cfg.get("categories", []):
        q = urllib.parse.urlencode({"sort": "Views", "interval": cfg.get("interval", "3 Days"), "pageNum": 0,
                                    "pageSize": cfg.get("limit", 10), "topics": json.dumps([cat])})
        for p in json.loads(fetch(f"https://api.alphaxiv.org/papers/v3/feed?{q}", timeout=60))["papers"]:
            pid = p.get("universal_paper_id", "")
            if not re.match(r"^\d{4}\.\d{4,5}$", pid):
                continue
            visits = (p.get("metrics") or {}).get("visits_count") or {}
            out.append({
                "source": f"alphaXiv {cat}",
                "kind": "community",
                "title": clean(p.get("title"), 200),
                "url": f"https://arxiv.org/abs/{pid}",
                "published": p.get("first_publication_date", ""),
                "summary": clean(p.get("feed_description") or p.get("abstract"), 350),
                "extra": {"views_7d": visits.get("last_7_days"), "votes": p.get("public_total_votes") or
                          (p.get("metrics") or {}).get("public_total_votes")},
            })
    return out
