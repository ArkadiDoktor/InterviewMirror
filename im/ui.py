"""Look and feel: one stylesheet and a few HTML snippets.

Visual idea: a calm, light video-meeting app. The page stays quiet (cool
paper-grey, navy ink) so the one dark element - the interviewer's video tile -
is where the eye goes. Each interviewer has an accent colour of their own.
All text that comes from the candidate or from a model is HTML-escaped.
"""
from __future__ import annotations

import base64
from html import escape

import streamlit as st

INK, MUTED, LINE, PAPER, SURFACE = "#14213d", "#5b6b82", "#d5dce6", "#eef1f5", "#ffffff"
GOOD, MID, LOW = "#1f9d8a", "#c98a12", "#b23a48"

CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Assistant:wght@400;600;700&family=Frank+Ruhl+Libre:wght@500;700;900&display=swap');

:root {{ --ink:{INK}; --muted:{MUTED}; --line:{LINE}; --paper:{PAPER}; --surface:{SURFACE};
        --good:{GOOD}; --mid:{MID}; --low:{LOW}; --accent:#2f5bea; }}

html, body, .stApp, .stApp p, .stApp li, .stApp label, .stApp input, .stApp textarea, .stApp button {{
  font-family: "Assistant", "Heebo", "Segoe UI", Arial, sans-serif; }}
.stApp {{ background: var(--paper); color: var(--ink); }}
[data-testid="stMainBlockContainer"] {{ direction: rtl; max-width: 1120px; padding-top: 2.2rem; padding-bottom: 3rem; }}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"], .stApp label {{ direction: rtl; text-align: right; }}
.stApp input, .stApp textarea {{ direction: rtl; text-align: right; }}
[data-testid="stChatMessage"] {{ direction: rtl; background: transparent; padding: 0.35rem 0; gap: 0.7rem; }}
[data-testid="stChatMessage"] img {{ object-fit: cover; object-position: top; }}
[data-testid="stExpander"] summary {{ direction: rtl; }}
[data-testid="stAlert"] {{ direction: rtl; text-align: right; }}
button:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
/* segmented controls are built for left-to-right: mirror their joined edges */
[data-testid="stButtonGroup"] [role="radiogroup"] > button {{ margin-right: 0 !important; margin-left: -1px !important; border-radius: 0 !important;
  border-color: color-mix(in srgb, var(--ink) 22%, transparent) !important; position: relative; }}
[data-testid="stButtonGroup"] [role="radiogroup"] > button[aria-checked="true"] {{ border-color: var(--ink) !important; z-index: 1; }}
[data-testid="stButtonGroup"] [role="radiogroup"] > button:first-child {{ border-radius: 0 8px 8px 0 !important; }}
[data-testid="stButtonGroup"] [role="radiogroup"] > button:last-child {{ border-radius: 8px 0 0 8px !important; margin-left: 0 !important; }}

/* type scale: 15 / 17 / 22 / 30 / 44 */
.im-brand {{ font: 700 17px/1 "Frank Ruhl Libre", serif; letter-spacing: .01em; color: var(--ink); direction: ltr; text-align: right; }}
.im-brand span {{ color: var(--muted); font: 400 15px "Assistant", sans-serif; margin-inline-start: .6rem; }}
.im-h1 {{ font: 900 clamp(30px, 5vw, 44px)/1.12 "Frank Ruhl Libre", serif; margin: 1.6rem 0 .5rem; color: var(--ink); max-width: 24ch; }}
.im-lede {{ font-size: 17px; line-height: 1.55; color: var(--muted); max-width: 52ch; margin: 0 0 1.8rem; }}
.im-h2 {{ font: 700 22px/1.25 "Frank Ruhl Libre", serif; margin: 1.9rem 0 .7rem; color: var(--ink); }}
.im-note {{ font-size: 15px; color: var(--muted); line-height: 1.5; }}

/* persona cards */
[class*="st-key-pc-"] {{ background: var(--surface); border-radius: 16px; border: 1.5px solid var(--line); padding: 14px; height: 100%; }}
[class*="st-key-pc-"][class*="-on"] {{ border-color: var(--pc); box-shadow: 0 0 0 3px color-mix(in srgb, var(--pc) 22%, transparent); }}
.st-key-pc-friendly-on, .st-key-pc-friendly-off {{ --pc: #1f9d8a; }}
.st-key-pc-technical-on, .st-key-pc-technical-off {{ --pc: #2f5bea; }}
.st-key-pc-tough-on, .st-key-pc-tough-off {{ --pc: #b23a48; }}
.im-pc {{ display: flex; gap: 12px; align-items: center; margin-bottom: 8px; }}
.im-pc img {{ width: 64px; height: 64px; border-radius: 50%; object-fit: cover; object-position: top; flex: none; }}
.im-pc b {{ display: block; font-size: 17px; line-height: 1.2; }}
.im-pc span {{ font-size: 15px; color: var(--pc); font-weight: 600; }}
.im-pc-text {{ font-size: 15px; line-height: 1.45; color: var(--muted); min-height: 3.2em; margin: 0 0 6px; }}

/* interview room */
.im-progress {{ margin: 14px 2px 10px; }}
.im-progress div {{ display: flex; justify-content: space-between; font-size: 15px; color: var(--muted); margin-bottom: 6px; }}
.im-progress i {{ display: block; height: 5px; border-radius: 3px; background: var(--line); overflow: hidden; }}
.im-progress i::after {{ content: ""; display: block; height: 100%; width: var(--w); background: var(--accent); border-radius: 3px; }}
.st-key-room-chat {{ background: var(--surface); border: 1px solid var(--line); border-radius: 18px; padding: 6px 16px; }}
.im-fb {{ margin: -2px 0 6px; margin-inline-start: 3rem; padding: 10px 14px; border-inline-start: 3px solid var(--c); background: color-mix(in srgb, var(--c) 7%, white);
          border-radius: 4px 10px 10px 4px; font-size: 15px; line-height: 1.5; }}
.im-fb b {{ color: var(--c); }}
.im-fb p {{ margin: 2px 0 0; }}
.im-typing {{ display: inline-flex; gap: 5px; padding: 6px 0; }}
.im-typing i {{ width: 7px; height: 7px; border-radius: 50%; background: var(--muted); animation: im-b 1s infinite ease-in-out; }}
.im-typing i:nth-child(2) {{ animation-delay: .15s; }} .im-typing i:nth-child(3) {{ animation-delay: .3s; }}
@keyframes im-b {{ 0%, 80%, 100% {{ opacity: .25; }} 40% {{ opacity: 1; }} }}
@media (prefers-reduced-motion: reduce) {{ .im-typing i {{ animation: none; opacity: .6; }} }}

/* report */
.im-verdict {{ display: inline-block; padding: 4px 14px; border-radius: 999px; font-weight: 700; font-size: 15px; color: #fff; background: var(--c); }}
.im-score {{ display: flex; gap: 26px; align-items: center; background: var(--surface); border: 1px solid var(--line); border-radius: 18px; padding: 22px 26px; margin: 1rem 0 0; }}
.im-ring {{ position: relative; width: 128px; height: 128px; flex: none; display: grid; place-content: center; text-align: center; }}
.im-ring img {{ position: absolute; inset: 0; }}
.im-ring b {{ font: 900 40px/1 "Frank Ruhl Libre", serif; font-variant-numeric: lining-nums; }}
.im-ring span {{ font-size: 13px; color: var(--muted); }}
.im-score p {{ margin: 0; font-size: 17px; line-height: 1.6; }}
.im-score small {{ display: block; margin-top: 10px; color: var(--muted); font-size: 15px; }}
.im-bars {{ display: grid; gap: 14px; }}
.im-bar header {{ display: flex; justify-content: space-between; font-weight: 700; font-size: 17px; }}
.im-bar header span {{ font-variant-numeric: tabular-nums; color: var(--c); }}
.im-bar i {{ display: block; height: 8px; border-radius: 4px; background: var(--line); margin: 5px 0; overflow: hidden; }}
.im-bar i::after {{ content: ""; display: block; height: 100%; width: var(--w); background: var(--c); border-radius: 4px; }}
.im-bar p {{ margin: 0; font-size: 15px; color: var(--muted); line-height: 1.45; }}
.stApp ul.im-list {{ margin: 0; padding: 0; list-style: none; display: grid; gap: 10px; }}
.stApp ul.im-list li {{ margin: 0; padding: 10px 14px; background: var(--surface); border-radius: 10px; border-inline-start: 3px solid var(--c); font-size: 15px; line-height: 1.5; }}
.im-qa p {{ margin: 0 0 8px; font-size: 15px; line-height: 1.55; }}
.im-qa .a {{ color: var(--muted); }}
.im-chart {{ background: var(--surface); border: 1px solid var(--line); border-radius: 18px; padding: 14px 18px 8px; }}

@media (max-width: 640px) {{
  .im-score {{ flex-direction: column; align-items: flex-start; }}
  .im-fb {{ margin-inline-start: 0; }}
}}
"""


def _svg_img(svg: str, alt: str, style: str = "") -> str:
    """st.html strips inline <svg>, so drawings are embedded as images."""
    uri = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode()
    return f'<img src="{uri}" alt="{escape(alt)}" style="{style}">'


def inject_css() -> None:
    st.html(f"<style>{CSS}</style>")


def tone(score10: float) -> str:
    return GOOD if score10 >= 7 else MID if score10 >= 5 else LOW


def brand() -> None:
    st.html('<div class="im-brand">InterviewMirror<span>סימולטור ראיונות עבודה בעברית</span></div>')


def h2(text: str) -> None:
    st.html(f'<h2 class="im-h2">{escape(text)}</h2>')


def progress(label: str, right: str, fraction: float, accent: str) -> None:
    pct = max(0, min(100, round(fraction * 100)))
    st.html(f'<div class="im-progress" style="--accent:{accent}"><div><span>{escape(label)}</span><span>{escape(right)}</span></div>'
            f'<i style="--w:{pct}%"></i></div>')


def feedback_card(ev: dict) -> None:
    c = tone(ev["score"])
    rows = "".join(f"<p><b>{lbl}</b> {escape(ev[k])}</p>" for lbl, k in
                   (("מה עבד:", "strength"), ("מה לשפר:", "improve"), ("בפעם הבאה:", "tip")) if ev.get(k))
    st.html(f'<div class="im-fb" style="--c:{c}"><b>{ev["score"]}/10</b>{rows}</div>')


def typing() -> None:
    st.html('<span class="im-typing" aria-label="המראיין חושב"><i></i><i></i><i></i></span>')


def score_ring(overall: int, verdict_text: str, color: str, summary: str, meta: str) -> None:
    r, circ = 52, 2 * 3.14159 * 52
    dash = circ * max(0, min(100, overall)) / 100
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128">'
        f'<circle cx="64" cy="64" r="{r}" fill="none" stroke="{LINE}" stroke-width="10"/>'
        f'<circle cx="64" cy="64" r="{r}" fill="none" stroke="{color}" stroke-width="10" stroke-linecap="round" '
        f'stroke-dasharray="{dash:.1f} {circ:.1f}" transform="rotate(-90 64 64)"/></svg>')
    st.html(
        f'<div class="im-score"><div class="im-ring">{_svg_img(svg, f"ציון כולל {overall} מתוך 100")}'
        f'<b>{overall}</b><span>מתוך 100</span></div>'
        f'<div><span class="im-verdict" style="--c:{color}">{escape(verdict_text)}</span>'
        f'<p style="margin-top:10px">{escape(summary)}</p><small>{escape(meta)}</small></div></div>')


def bars(items: list[dict]) -> None:
    html = "".join(
        f'<div class="im-bar" style="--c:{tone(c["score"])};--w:{c["score"] * 10}%"><header><b>{escape(c["name"])}</b>'
        f'<span>{c["score"]}/10</span></header><i></i><p>{escape(c.get("comment", ""))}</p></div>' for c in items)
    st.html(f'<div class="im-bars">{html}</div>')


def bullet_list(items: list[str], color: str) -> None:
    st.html(f'<ul class="im-list" style="--c:{color}">' + "".join(f"<li>{escape(s)}</li>" for s in items) + "</ul>")


def score_chart(scores: list[int]) -> None:
    """Score per answer, drawn as plain SVG so Hebrew labels render correctly."""
    if len(scores) < 2:
        return
    w, h, pad_x, top, bottom = 640, 190, 34, 16, 34
    step = (w - 2 * pad_x) / (len(scores) - 1)
    y = lambda s: top + (10 - s) / 10 * (h - top - bottom)  # noqa: E731
    pts = [(pad_x + i * step, y(s)) for i, s in enumerate(scores)]
    avg = sum(scores) / len(scores)
    grid = "".join(f'<line x1="{pad_x}" x2="{w - pad_x}" y1="{y(v)}" y2="{y(v)}" stroke="{LINE}" stroke-width="1"/>'
                   f'<text x="{pad_x - 10}" y="{y(v) + 4}" font-size="11" fill="{MUTED}" text-anchor="end">{v}</text>'
                   for v in (0, 5, 10))
    line = " ".join(f"{x:.1f},{yy:.1f}" for x, yy in pts)
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{yy:.1f}" r="5.5" fill="{tone(s)}" stroke="#fff" stroke-width="2"/>'
        f'<text x="{x:.1f}" y="{h - 12}" font-size="11" fill="{MUTED}" text-anchor="middle">{i + 1}</text>'
        for i, ((x, yy), s) in enumerate(zip(pts, scores)))
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="Arial, sans-serif">{grid}'
        f'<line x1="{pad_x}" x2="{w - pad_x}" y1="{y(avg)}" y2="{y(avg)}" stroke="{MUTED}" stroke-dasharray="4 5" stroke-width="1.2"/>'
        f'<polyline points="{line}" fill="none" stroke="{INK}" stroke-width="2.2" stroke-linejoin="round"/>{dots}</svg>')
    st.html(
        f'<div class="im-chart">{_svg_img(svg, f"ציון לכל תשובה לאורך הראיון, ממוצע {avg:.1f}", "width:100%;display:block")}'
        f'<p class="im-note" style="margin:0 4px 6px">ציון לכל תשובה לפי הסדר. הקו המקווקו הוא הממוצע שלך: {avg:.1f}.</p></div>')


def day_bars(counts: dict[str, int], accent: str = "#2f5bea") -> None:
    """Simple bar chart (label -> count) drawn as an image, so labels never get clipped."""
    if not counts:
        return
    items = list(counts.items())
    w, h, pad_l, pad_b, top = 760, 220, 34, 30, 14
    top_val = max(v for _, v in items) or 1
    slot = (w - pad_l - 8) / len(items)
    bar_w = max(4.0, slot * 0.62)
    y = lambda v: top + (1 - v / top_val) * (h - top - pad_b)  # noqa: E731
    step = max(1, len(items) // 14)
    parts = [f'<line x1="{pad_l}" x2="{w - 8}" y1="{y(0)}" y2="{y(0)}" stroke="{LINE}"/>',
             f'<text x="{pad_l - 8}" y="{y(top_val) + 4}" font-size="11" fill="{MUTED}" text-anchor="end">{top_val}</text>',
             f'<text x="{pad_l - 8}" y="{y(0) + 4}" font-size="11" fill="{MUTED}" text-anchor="end">0</text>']
    for i, (label, v) in enumerate(items):
        x = pad_l + i * slot + (slot - bar_w) / 2
        parts.append(f'<rect x="{x:.1f}" y="{y(v):.1f}" width="{bar_w:.1f}" height="{y(0) - y(v):.1f}" rx="3" fill="{accent}"/>')
        if v:
            parts.append(f'<text x="{x + bar_w / 2:.1f}" y="{y(v) - 4:.1f}" font-size="11" fill="{INK}" text-anchor="middle">{v}</text>')
        if i % step == 0:
            parts.append(f'<text x="{x + bar_w / 2:.1f}" y="{h - 10}" font-size="11" fill="{MUTED}" text-anchor="middle">{escape(label)}</text>')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="Arial, sans-serif">{"".join(parts)}</svg>'
    st.html(f'<div class="im-chart">{_svg_img(svg, "ראיונות לפי יום", "width:100%;display:block")}</div>')
