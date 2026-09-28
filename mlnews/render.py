"""Digest dict -> (subject, html, plaintext). Inline CSS only (email clients strip <style>).

Layout: headline + TL;DR → 🔥 must-read (any field) → one section per field (items, then radar one-liners).
"""
from datetime import datetime
from html import escape

FIELDS = [
    ("vision", "👁 Vision"),
    ("nlp", "💬 NLP"),
    ("robotics", "🤖 Robotics"),
    ("general", "🧠 General ML"),
]
FIELD_SHORT = {"vision": "Vision", "nlp": "NLP", "robotics": "Robotics", "general": "ML"}
CATEGORY = {"release": "릴리스", "paper": "논문", "tool": "오픈소스", "industry": "업계"}
WEEKDAY = "월화수목금토일"

C_TEXT, C_MUTED, C_LINK, C_RULE, C_ACCENT, C_TAG_BG = "#1f2328", "#656d76", "#0969da", "#d8dee4", "#cf222e", "#eff2f5"


def subject(cfg: dict, digest: dict, now: datetime) -> str:
    prefix = cfg["digest"].get("subject_prefix", "[ML News]")
    date = f"{now.month}/{now.day}({WEEKDAY[now.weekday()]})"
    return f"{prefix} {date} {digest.get('headline', '')}".strip()


def _field(x: dict) -> str:
    return x.get("field") if x.get("field") in FIELD_SHORT else "general"


def _tag(text: str) -> str:
    return (f'<span style="display:inline-block;font-size:11px;font-weight:600;color:{C_MUTED};background:{C_TAG_BG};'
            f'border-radius:4px;padding:0 5px;margin-right:6px;vertical-align:1px">{escape(text)}</span>')


def _links_html(links: list[dict]) -> str:
    return " · ".join(
        f'<a href="{escape(l["url"])}" style="color:{C_LINK};text-decoration:none">{escape(l["label"])}</a>'
        for l in links
    )


def _section_header(label: str, color: str) -> str:
    return (f'<div style="margin:24px 0 6px;padding-bottom:4px;border-bottom:1px solid {C_RULE};'
            f'font-size:14px;font-weight:700;color:{color}">{label}</div>')


def _item_html(it: dict, tag: str) -> str:
    return (f'<div style="margin:12px 0">'
            f'<div style="font-weight:700">{_tag(tag)}{escape(it["title"])}</div>'
            f'<div>{escape(it["what"])}</div>'
            f'<div style="color:{C_MUTED}">→ {escape(it["why"])}</div>'
            f'<div style="font-size:13px;margin-top:2px">{_links_html(it["links"])}</div></div>')


def to_html(digest: dict, now: datetime, footer: str) -> str:
    items, radar = digest.get("items", []), digest.get("radar", [])
    p = [f'<div style="max-width:640px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\','
         f'\'Apple SD Gothic Neo\',\'Malgun Gothic\',sans-serif;color:{C_TEXT};font-size:15px;line-height:1.55">',
         f'<div style="font-size:12px;color:{C_MUTED}">{now:%Y-%m-%d} · ML News</div>',
         f'<div style="font-size:19px;font-weight:700;margin:4px 0 10px">{escape(digest.get("headline", ""))}</div>']
    if digest.get("tldr"):
        p.append('<ul style="margin:0 0 8px;padding-left:18px">'
                 + "".join(f"<li>{escape(t)}</li>" for t in digest["tldr"]) + "</ul>")

    must = [i for i in items if i.get("must_read")]
    if must:
        p.append(_section_header("🔥 꼭 볼 것", C_ACCENT))
        p += [_item_html(it, FIELD_SHORT[_field(it)]) for it in must]

    for key, label in FIELDS:
        sec = [i for i in items if not i.get("must_read") and _field(i) == key]
        rad = [r for r in radar if _field(r) == key]
        if not (sec or rad):
            continue
        p.append(_section_header(label, C_TEXT))
        p += [_item_html(it, CATEGORY.get(it.get("category"), "")) for it in sec]
        if rad:
            p.append(f'<ul style="margin:6px 0 0;padding-left:18px;font-size:14px;color:{C_MUTED}">' + "".join(
                f'<li><a href="{escape(r["url"])}" style="color:{C_LINK};text-decoration:none">{escape(r["title"])}</a></li>'
                for r in rad) + "</ul>")

    if not items and not radar:
        p.append(f'<p style="color:{C_MUTED}">오늘은 조용한 날입니다. 챙길 만한 큰 소식이 없었어요.</p>')

    p.append(f'<div style="margin-top:28px;font-size:11px;color:{C_MUTED}">{escape(footer)}</div></div>')
    return "\n".join(p)


def to_text(digest: dict, now: datetime, footer: str) -> str:
    items, radar = digest.get("items", []), digest.get("radar", [])
    out = [f"{now:%Y-%m-%d} ML News", digest.get("headline", ""), ""]
    out += [f"- {t}" for t in digest.get("tldr", [])]

    def item(it, tag):
        return [f"* [{tag}] {it['title']}", f"  {it['what']}", f"  → {it['why']}"] + \
               [f"  {l['label']}: {l['url']}" for l in it["links"]]

    must = [i for i in items if i.get("must_read")]
    if must:
        out += ["", "🔥 꼭 볼 것"]
        for it in must:
            out += item(it, FIELD_SHORT[_field(it)])
    for key, label in FIELDS:
        sec = [i for i in items if not i.get("must_read") and _field(i) == key]
        rad = [r for r in radar if _field(r) == key]
        if sec or rad:
            out += ["", label]
            for it in sec:
                out += item(it, CATEGORY.get(it.get("category"), ""))
            out += [f"  - {r['title']}: {r['url']}" for r in rad]
    out += ["", footer]
    return "\n".join(out)
