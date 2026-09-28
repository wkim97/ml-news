"""Ask Claude (headless `claude -p`) to pick and summarize the hot items. Returns a dict matching SCHEMA."""
import json
import shutil
import subprocess
import sys

from .config import ROOT

SCHEMA = {
    "type": "object",
    "required": ["headline", "tldr", "items", "radar"],
    "additionalProperties": False,
    "properties": {
        "headline": {"type": "string"},
        "tldr": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["category", "title", "what", "why", "links"],
                "additionalProperties": False,
                "properties": {
                    "category": {"type": "string", "enum": ["big", "release", "paper", "tool", "industry"]},
                    "title": {"type": "string"},
                    "what": {"type": "string"},
                    "why": {"type": "string"},
                    "links": {
                        "type": "array", "minItems": 1, "maxItems": 3,
                        "items": {
                            "type": "object", "required": ["label", "url"], "additionalProperties": False,
                            "properties": {"label": {"type": "string"}, "url": {"type": "string"}},
                        },
                    },
                },
            },
        },
        "radar": {
            "type": "array",
            "items": {
                "type": "object", "required": ["title", "url"], "additionalProperties": False,
                "properties": {"title": {"type": "string"}, "url": {"type": "string"}},
            },
        },
    },
}


def build_prompt(cfg: dict, candidates: list[dict], history: list[str], window: str) -> str:
    d, c = cfg["digest"], cfg.get("curate", {})
    web_rule = (
        "You MAY use WebSearch/WebFetch (budget: ~8 calls) to (a) verify/enrich a top item with its primary source, "
        "and (b) run 2–3 searches for major AI releases/announcements in the last 24–36h that the candidates missed "
        "(e.g. new frontier models announced on X). Include a missed item only if you found a primary source."
        if c.get("allow_web", True) else "Do not use any tools; work only from the candidates."
    )
    template = (ROOT / "prompts" / "curate.md").read_text()
    return template.format(
        profile=cfg["profile"]["description"].strip(),
        language=cfg["profile"].get("language", "English"),
        window=window,
        max_items=d.get("max_items", 10),
        max_radar=d.get("max_radar", 6),
        web_rule=web_rule,
        history="\n".join(f"- {h}" for h in history) or "(none)",
        candidates="\n".join(json.dumps(x, ensure_ascii=False) for x in candidates),
    )


def curate(cfg: dict, prompt: str) -> tuple[dict, dict]:
    """Returns (digest, meta). Raises on failure."""
    c = cfg.get("curate", {})
    claude = shutil.which("claude")
    if not claude:
        raise RuntimeError("`claude` CLI not found on PATH")
    cmd = [
        claude, "-p",
        "--output-format", "json",
        "--json-schema", json.dumps(SCHEMA),
        "--no-session-persistence",
        "--strict-mcp-config",  # no MCP servers: curator only needs web tools
    ]
    if c.get("allow_web", True):
        cmd += ["--allowedTools", "WebSearch,WebFetch"]
    if c.get("model"):
        cmd += ["--model", c["model"]]
    proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                          timeout=c.get("timeout_sec", 1200), cwd=ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr[-2000:] or proc.stdout[-2000:]}")
    out = json.loads(proc.stdout)
    if out.get("is_error"):
        raise RuntimeError(f"claude error: {out.get('result')}")
    digest = out.get("structured_output")
    if digest is None:  # fall back to parsing the text result
        digest = json.loads(out.get("result", ""))
    meta = {k: out.get(k) for k in ("total_cost_usd", "duration_ms", "num_turns", "session_id")}
    print(f"[curate] {meta}", file=sys.stderr, flush=True)
    return digest, meta
