"""Сравнение скриншотов до/после: доля изменившихся пикселей и рамка изменений.

  python diff.py [префикс]     # например tma390 — только мини-апп

Живые данные (эфир, отсчёт, новости) меняются между прогонами — смотреть на рамку изменений и
картинку diff-*.png (красным — отличия), а не на голый процент.
"""
import pathlib
import sys

import numpy as np
from PIL import Image

HERE = pathlib.Path(__file__).resolve().parent.parent
B, A, D = HERE / "before", HERE / "after", HERE / "diff"
D.mkdir(exist_ok=True)
pref = sys.argv[1] if len(sys.argv) > 1 else ""
for fb in sorted(B.glob(f"{pref}*.png")):
    fa = A / fb.name
    if not fa.exists():
        print(f"{fb.name:45} нет «после»")
        continue
    ib, ia = Image.open(fb).convert("RGB"), Image.open(fa).convert("RGB")
    if ib.size != ia.size:
        print(f"{fb.name:45} размер {ib.size} → {ia.size}")
        h = min(ib.size[1], ia.size[1])
        ib, ia = ib.crop((0, 0, ib.size[0], h)), ia.crop((0, 0, ia.size[0], h))
    x, y = np.asarray(ib, dtype=np.int16), np.asarray(ia, dtype=np.int16)
    m = np.abs(x - y).max(axis=2) > 24
    share = m.mean() * 100
    box = ""
    if m.any():
        ys, xs = np.where(m)
        box = f"рамка x{xs.min()}-{xs.max()} y{ys.min()}-{ys.max()}"
        if share > 0.05:
            out = (np.asarray(ia) * 0.35).astype(np.uint8)
            out[m] = [255, 40, 40]
            Image.fromarray(out).save(D / f"diff-{fb.name}")
    print(f"{fb.name:45} {share:6.2f}%  {box}")
