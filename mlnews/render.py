"""Digest dict -> (subject, html, plaintext). Inline CSS only (email clients strip <style>)."""
from datetime import datetime
from html import escape

SECTIONS = [
    ("big", "🔥 꼭 볼 것"),
    ("release", "🚀 릴리스"),
    ("paper", "📄 논문"),
    ("tool", "🛠 오픈소스 · 데이터"),
    ("industry", "🏢 업계"),
]
WEEKDAY = "월화수목금토일"

C_TEXT, C_MUTED, C_LINK, C_RULE, C_ACCENT = "#1f2328", "#656d76", "#0969da", "#d8dee4", "#cf222e"


def subject(cfg: dict, digest: dict, now: datetime) -> str:
    prefix = cfg["digest"].get("subject_prefix", "[ML News]")
    date = f"{now.month}/{now.day}({WEEKDAY[now.weekday()]})"
    return f"{prefix} {date} {digest.get('headline', '')}".strip()


def _links_html(links: list[dict]) -> str:
    return " · ".join(
        f'<a href="{escape(l["url"])}" style="color:{C_LINK};text-decoration:none">{escape(l["label"])}</a>'
        for l in links
    )


def to_html(digest: dict, now: datetime, footer: str) -> str:
    p = []
    p.append(f'<div style="max-width:640px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\','
             f'\'Apple SD Gothic Neo\',\'Malgun Gothic\',sans-serif;color:{C_TEXT};font-size:15px;line-height:1.55">')
    p.append(f'<div style="font-size:12px;color:{C_MUTED}">{now:%Y-%m-%d} · ML News</div>')
    p.append(f'<div style="font-size:19px;font-weight:700;margin:4px 0 10px">{escape(digest.get("headline", ""))}</div>')
    if digest.get("tldr"):
        p.append(f'<ul style="margin:0 0 8px;padding-left:18px">'
                 + "".join(f"<li>{escape(t)}</li>" for t in digest["tldr"]) + "</ul>")

    items = digest.get("items", [])
    for key, label in SECTIONS:
        sec = [i for i in items if i.get("category") == key]
        if not sec:
            continue
        p.append(f'<div style="margin:22px 0 6px;padding-bottom:4px;border-bottom:1px solid {C_RULE};'
                 f'font-size:13px;font-weight:700;color:{C_ACCENT if key == "big" else C_MUTED}">{label}</div>')
        for it in sec:
            p.append('<div style="margin:12px 0">')
            p.append(f'<div style="font-weight:700">{escape(it["title"])}</div>')
            p.append(f'<div>{escape(it["what"])}</div>')
            p.append(f'<div style="color:{C_MUTED}">→ {escape(it["why"])}</div>')
            p.append(f'<div style="font-size:13px;margin-top:2px">{_links_html(it["links"])}</div>')
            p.append("</div>")

    if digest.get("radar"):
        p.append(f'<div style="margin:22px 0 6px;padding-bottom:4px;border-bottom:1px solid {C_RULE};'
                 f'font-size:13px;font-weight:700;color:{C_MUTED}">👀 레이더</div>')
        p.append('<ul style="margin:0;padding-left:18px;font-size:14px">' + "".join(
            f'<li><a href="{escape(r["url"])}" style="color:{C_LINK};text-decoration:none">{escape(r["title"])}</a></li>'
            for r in digest["radar"]) + "</ul>")

    if not items and not digest.get("radar"):
        p.append(f'<p style="color:{C_MUTED}">오늘은 조용한 날입니다. 챙길 만한 큰 소식이 없었어요.</p>')

    p.append(f'<div style="margin-top:28px;font-size:11px;color:{C_MUTED}">{escape(footer)}</div></div>')
    return "\n".join(p)


def to_text(digest: dict, now: datetime, footer: str) -> str:
    out = [f"{now:%Y-%m-%d} ML News", digest.get("headline", ""), ""]
    out += [f"- {t}" for t in digest.get("tldr", [])]
    items = digest.get("items", [])
    for key, label in SECTIONS:
        sec = [i for i in items if i.get("category") == key]
        if sec:
            out += ["", label]
            for it in sec:
                out += [f"* {it['title']}", f"  {it['what']}", f"  → {it['why']}"]
                out += [f"  {l['label']}: {l['url']}" for l in it["links"]]
    if digest.get("radar"):
        out += ["", "👀 레이더"] + [f"- {r['title']}: {r['url']}" for r in digest["radar"]]
    out += ["", footer]
    return "\n".join(out)
