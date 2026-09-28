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

    if digest.get("arxiv"):
        p.append(_arxiv_html(digest["arxiv"]))

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
    if digest.get("arxiv"):
        out += _arxiv_text(digest["arxiv"])
    out += ["", footer]
    return "\n".join(out)


# ---------------------------------------------------------------- arXiv sections

def _a(url: str, text: str) -> str:
    return f'<a href="{escape(url)}" style="color:{C_LINK};text-decoration:none">{escape(text)}</a>'


def _paper(ax: dict, pid: str) -> dict:
    return ax["papers"].get(pid) or {"title": pid, "url": f"https://arxiv.org/abs/{pid}"}


def _arxiv_html(ax: dict) -> str:
    p = []
    shown = {}
    for w in ax.get("windows", []):
        if not w["papers"]:
            continue
        label = f'최근 {w["days"]}일'
        p.append(_section_header(f"📈 arXiv 조회수 Top-{len(w['papers'])} · {label}", C_TEXT))
        p.append('<ol style="margin:0;padding-left:20px">')
        for t in w["papers"]:
            views = f'{t["views"]:,} views'
            if t["id"] in shown:  # already described in a fresher window → compact line
                p.append(f'<li style="margin:4px 0;color:{C_MUTED};font-size:14px">{_a(t["url"], t["title"])} '
                         f'· {views} <span style="font-size:12px">(↑ {shown[t["id"]]} 참고)</span></li>')
                continue
            shown[t["id"]] = label
            p.append(f'<li style="margin:6px 0"><b>{escape(t["title"])}</b>'
                     f'<div>{escape(t.get("message") or "")}</div>'
                     f'<div style="font-size:12px;color:{C_MUTED}">{views} · {t["published"]} · '
                     f'{_a(t["url"], "arXiv")} · {_a(t["alphaxiv"], "alphaXiv")}</div></li>')
        p.append("</ol>")
    if ax.get("windows"):
        p.append(f'<div style="font-size:11px;color:{C_MUTED};margin-top:4px">조회수: alphaXiv 기준, 해당 기간에 게시된 논문 '
                 f'(3·7일 목록은 최근 7일 조회수, 30일 목록은 누적 조회수)</div>')

    trend = ax.get("trend") or {}
    if trend.get("skipped"):
        p.append(_section_header("📊 arXiv 트렌드", C_TEXT))
        p.append(f'<div style="color:{C_MUTED};font-size:14px">{escape(trend["skipped"])}</div>')
    elif trend.get("trends"):
        p.append(_section_header(f'📊 arXiv 트렌드 · {ax["mailing"]} 메일링 {ax["total"]:,}편', C_TEXT))
        p.append(f'<div style="margin-bottom:6px">{escape(trend.get("overview", ""))}</div>')
        for key, label in FIELDS:
            ts = [t for t in trend["trends"] if _field(t) == key]
            if not ts:
                continue
            p.append(f'<div style="font-size:13px;font-weight:700;color:{C_MUTED};margin:10px 0 2px">{label}</div>')
            p.append('<ul style="margin:0;padding-left:18px;font-size:14px">')
            for t in ts:
                up = f'<span style="color:{C_ACCENT};font-weight:700"> ↑</span>' if t.get("rising") else ""
                ex = " · ".join(_a(_paper(ax, i)["url"], _paper(ax, i)["title"][:60]) for i in t["ids"])
                p.append(f'<li style="margin:4px 0"><b>{escape(t["topic"])}</b> '
                         f'<span style="color:{C_MUTED}">{t["count"]}편</span>{up} — {escape(t["what"])}'
                         f'<div style="font-size:12px">{ex}</div></li>')
            p.append("</ul>")
        if trend.get("standouts"):
            p.append(f'<div style="font-size:13px;font-weight:700;color:{C_MUTED};margin:10px 0 2px">⭐ 열어볼 만한 논문</div>')
            p.append('<ul style="margin:0;padding-left:18px;font-size:14px">' + "".join(
                f'<li>{_a(_paper(ax, s["id"])["url"], _paper(ax, s["id"])["title"])} '
                f'<span style="color:{C_MUTED}">— {escape(s["why"])}</span></li>' for s in trend["standouts"]) + "</ul>")
    return "\n".join(p)


def _arxiv_text(ax: dict) -> list[str]:
    out = []
    shown = set()
    for w in ax.get("windows", []):
        if not w["papers"]:
            continue
        out += ["", f"📈 arXiv 조회수 Top-{len(w['papers'])} · 최근 {w['days']}일 (alphaXiv)"]
        for n, t in enumerate(w["papers"], 1):
            if t["id"] in shown:
                out.append(f"{n}. {t['title']} ({t['views']:,} views, 위 참고)")
                continue
            shown.add(t["id"])
            out += [f"{n}. {t['title']} ({t['views']:,} views, {t['published']})",
                    f"   {t.get('message') or ''}", f"   {t['url']}"]
    trend = ax.get("trend") or {}
    if trend.get("skipped"):
        out += ["", "📊 arXiv 트렌드", trend["skipped"]]
    elif trend.get("trends"):
        out += ["", f"📊 arXiv 트렌드 · {ax['mailing']} 메일링 {ax['total']:,}편", trend.get("overview", "")]
        for key, label in FIELDS:
            ts = [t for t in trend["trends"] if _field(t) == key]
            if ts:
                out += [label] + [f"  - {t['topic']} ({t['count']}편){' ↑' if t.get('rising') else ''}: {t['what']}"
                                  for t in ts]
        for s in trend.get("standouts", []):
            out.append(f"  ⭐ {_paper(ax, s['id'])['title']} — {s['why']} {_paper(ax, s['id'])['url']}")
    return out
