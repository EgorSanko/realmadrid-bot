"""Эмблема из присланного SVG → слои для анимации заставки.

Контуры с дырками (кольцо = внешний + внутренний подконтур) нельзя резать по одному,
поэтому режем по областям: «корона» (всё выше обода) и «круг». В каждой области подконтуры
одного цвета остаются одним составным path — дырки сохраняются. Жемчужины (мелкие белые
подконтуры в короне) — отдельными элементами, чтобы появлялись по одной.

Круг делится ещё на два слоя, и у каждого одна маска на все цвета (поэтому цвета не расходятся):
  «обод»   — концентрические кольца: синий внешний кант, золотое кольцо, синий внутренний кант.
             Это пары почти-окружностей с центром в центре круга (большие, из ≤5 сегментов).
  «вензель» — всё остальное в круге: золотые буквы MCF, их синяя обводка и синяя лента.
Белый диск — отдельно.

  python tools/splash/build.py && python tools/splash/inject.py   (нужен svgpathtools)
"""
import pathlib, re
from svgpathtools import parse_path

HERE = pathlib.Path(__file__).parent
src = (HERE / "logo.svg").read_text(encoding="utf-8")
CROWN_TOP_Y = 12.0  # деталь короны начинается выше обода круга (у круга верх ≥ 12.1)
CX, CY = 16.0, 27.56  # центр круга эмблемы

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

def is_rim(q):
    """концентрическая окружность обода (или край диска)"""
    x0, x1, y0, y1 = q.bbox()
    return (len(q) <= 5 and x1 - x0 > 26.8
            and abs((x0 + x1) / 2 - CX) < .05 and abs((y0 + y1) / 2 - CY) < .05)

out = {"circle": {}, "rim": {}, "mono": {}, "crown": {}, "pearls": []}
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
        if fill.lower() != "#fff":
            rim = [s for s in circ if is_rim(s)]
            mono = [s for s in circ if not is_rim(s)]
            if rim:
                out["rim"][fill] = compact(dstr(rim))
            if mono:
                out["mono"][fill] = compact(dstr(mono))
    if crown:
        out["crown"][fill] = compact(dstr(crown))

W, G, R, B = "#fff", "#fcbf00", "#e62644", "#004996"
assert set(out["rim"]) == {G, B}, out["rim"].keys()
pearls = "\n      ".join(
    f'<path class="sp-pearl" style="--d:{i}" d="{d}"/>' for i, (d, cx, cy) in enumerate(out["pearls"]))
# обод рисуется штрихом маски по окружности r=14.8 (кольца лежат в 13.55…16); длина окружности:
RING_R = 14.8
svg = f'''<svg class="sp-crest" viewBox="-1 -1 34 45" role="img" aria-label="Real Madrid">
  <defs>
    <mask id="sp-ring" maskUnits="userSpaceOnUse" x="-1" y="-1" width="34" height="45">
      <circle class="sp-ring-c" cx="{CX}" cy="{CY}" r="{RING_R}" fill="none" stroke="#fff" stroke-width="3.8" transform="rotate(-90 {CX} {CY})"/>
      <rect class="sp-ring-seal" x="-1" y="-1" width="34" height="45" fill="#fff"/>
    </mask>
    <linearGradient id="sp-wipe-g" x1="0" x2="1" y1="0" y2="0">
      <stop offset="0" stop-color="#fff"/>
      <stop offset=".88" stop-color="#fff"/>
      <stop offset="1" stop-color="#fff" stop-opacity="0"/>
    </linearGradient>
    <mask id="sp-wipe" maskUnits="userSpaceOnUse" x="-1" y="-1" width="34" height="45">
      <g transform="translate({CX} {CY}) rotate(42)">
        <rect class="sp-wipe-r" x="-60" y="-30" width="60" height="60" fill="url(#sp-wipe-g)"/>
      </g>
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
    <g class="sp-rim" mask="url(#sp-ring)"><path fill="{G}" d="{out['rim'][G]}"/><path fill="{B}" d="{out['rim'][B]}"/></g>
    <g class="sp-mono" mask="url(#sp-wipe)"><path fill="{G}" d="{out['mono'][G]}"/><path fill="{B}" d="{out['mono'][B]}"/></g>
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
(HERE / "crest-anim.svg").write_text(svg, encoding="utf-8", newline="\n")
print("pearls", len(out["pearls"]), "| rim", list(out["rim"]), "| mono", list(out["mono"]),
      "| crown fills", list(out["crown"]), "| bytes", len(svg))
