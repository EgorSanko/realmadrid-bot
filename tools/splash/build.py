"""Эмблема из присланного SVG → слои для анимации заставки.

Контуры с дырками (кольцо = внешний + внутренний подконтур) нельзя резать по одному,
поэтому режем по областям: «корона» (всё выше обода) и «круг». В каждой области подконтуры
одного цвета остаются одним составным path — дырки сохраняются. Жемчужины (мелкие белые
подконтуры в короне) — отдельными элементами, чтобы появлялись по одной.
"""
import pathlib, re
from svgpathtools import parse_path, Path

HERE = pathlib.Path(__file__).parent
src = (HERE / "logo.svg").read_text(encoding="utf-8")
CROWN_TOP_Y = 12.0  # деталь короны начинается выше обода круга (у круга верх ≥ 12.1)

layers = []  # (fill, [subpaths])
for m in re.finditer(r"<path ([^>]*)>", src):
    a = m.group(1)
    d = re.search(r'\bd="([^"]+)"', a).group(1)
    fill = re.search(r'fill="([^"]+)"', a).group(1)
    layers.append((fill, parse_path(d).continuous_subpaths()))

def dstr(subs):
    return " ".join(sp.d() for sp in subs)

def r3(x):
    return f"{x:.2f}".rstrip("0").rstrip(".")

def compact(d):
    return re.sub(r"-?\d+\.\d+", lambda m: r3(float(m.group())), d)

out = {"circle": {}, "crown": {}, "pearls": []}
for fill, subs in layers:
    is_crown = lambda q: q.bbox()[2] < CROWN_TOP_Y or q.bbox()[3] <= 14.0  # выше обода или мелочь на ободе короны
    circ = [s for s in subs if not is_crown(s)]
    crown = [s for s in subs if is_crown(s)]
    if fill.lower() == "#fff":
        # в короне белое — только жемчуг: каждая бусина отдельно
        for s in sorted(crown, key=lambda q: (q.bbox()[0] + q.bbox()[1]) / 2):
            x0, x1, y0, y1 = s.bbox()
            out["pearls"].append((compact(s.d()), (x0 + x1) / 2, (y0 + y1) / 2))
        crown = []
    if circ:
        out["circle"][fill] = compact(dstr(circ))
    if crown:
        out["crown"][fill] = compact(dstr(crown))

W, G, R, B = "#fff", "#fcbf00", "#e62644", "#004996"
pearls = "\n      ".join(
    f'<path class="sp-pearl" style="--d:{i}" d="{d}"/>' for i, (d, cx, cy) in enumerate(out["pearls"]))
svg = f'''<svg class="sp-crest" viewBox="-1 -1 34 45" role="img" aria-label="Real Madrid">
  <defs>
    <mask id="sp-sweep" maskUnits="userSpaceOnUse" x="-1" y="-1" width="34" height="45">
      <circle class="sp-sweep-c" cx="16" cy="27.56" r="8.5" fill="none" stroke="#fff" stroke-width="17" pathLength="100" transform="rotate(-90 16 27.56)"/>
    </mask>
    <mask id="sp-sash" maskUnits="userSpaceOnUse" x="-1" y="-1" width="34" height="45">
      <rect class="sp-sash-r" x="-40" y="-30" width="112" height="115" fill="#fff"/>
    </mask>
    <linearGradient id="sp-shine-g" x1="0" x2="1" y1="0" y2="0">
      <stop offset="0" stop-color="#fff" stop-opacity="0"/>
      <stop offset=".5" stop-color="#fff" stop-opacity=".7"/>
      <stop offset="1" stop-color="#fff" stop-opacity="0"/>
    </linearGradient>
    <mask id="sp-shape" maskUnits="userSpaceOnUse" x="-1" y="-1" width="34" height="45">
      <g fill="#fff">
        <path d="{out['circle'][G]}"/><path d="{out['crown'][G]}"/><path d="{out['crown'][R]}"/>
      </g>
    </mask>
  </defs>
  <g class="sp-circle">
    <path class="sp-disc" fill="{W}" d="{out['circle'][W]}"/>
    <g mask="url(#sp-sweep)"><path class="sp-gold" fill="{G}" d="{out['circle'][G]}"/></g>
    <g mask="url(#sp-sash)"><path class="sp-blue" fill="{B}" d="{out['circle'][B]}"/></g>
  </g>
  <g class="sp-crown">
    <path class="sp-cap" fill="{R}" d="{out['crown'][R]}"/>
    <path fill="{G}" d="{out['crown'][G]}"/>
    <path fill="{B}" d="{out['crown'].get(B, '')}"/>
    <g fill="{W}">
      {pearls}
    </g>
  </g>
  <g mask="url(#sp-shape)"><rect class="sp-shine" x="-12" y="-1" width="7" height="45" fill="url(#sp-shine-g)"/></g>
</svg>'''
(HERE / "crest-anim.svg").write_text(svg, encoding="utf-8")
print("pearls", len(out["pearls"]), "| circle fills", list(out["circle"]), "| crown fills", list(out["crown"]), "| bytes", len(svg))
