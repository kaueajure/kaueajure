import re
import sys
from pathlib import Path

PHASE = 0.74
FONT = {
    'A': ['01110','10001','10001','11111','10001','10001','10001'],
    'J': ['11111','00100','00100','00100','00100','10100','01100'],
    'R': ['11110','10001','10001','11110','10100','10010','10001'],
}


def targets():
    out = []
    pitch, size, gap = 13, 10, 2
    cols = 19
    x0 = round((848 - ((cols - 1) * pitch + size)) / 2)
    y0 = 10
    offset = 0
    for ch in 'AJR':
        for row, line in enumerate(FONT[ch]):
            for col, bit in enumerate(line):
                if bit == '1':
                    out.append((x0 + (offset + col) * pitch, y0 + row * pitch))
        offset += 5 + gap
    return out


def overlay(ms):
    ox, oy = 76, 48
    items = [f'<g id="ajr-finale" pointer-events="none"><g transform="translate({ox} {oy})" opacity="0"><circle r="10" fill="var(--cs)"/><circle cx="3" cy="-3" r="2" fill="#fff"/><circle cx="3.6" cy="-3" r=".8" fill="#1f2328"/><animate attributeName="opacity" values="0;0;1;1;0;0" keyTimes="0;.735;.75;.835;.85;1" dur="{ms}ms" repeatCount="indefinite"/></g>']
    pts = targets()
    for i, (tx, ty) in enumerate(pts):
        start = .755 + (i % 10) * .0025
        mid = start + .035
        arrive = min(.865, start + .085 + i / max(1, len(pts)-1) * .01)
        kt = f'0;{start:.4f};{mid:.4f};{arrive:.4f};.955;1'
        mx = ox + 70 + (i % 7) * 9
        my = oy - 42 + (i % 8) * 12
        items.append(f'<rect x="{ox}" y="{oy}" width="10" height="10" rx="2" fill="var(--cs)" opacity="0"><animate attributeName="x" values="{ox};{ox};{mx};{tx};{tx};{tx}" keyTimes="{kt}" dur="{ms}ms" repeatCount="indefinite"/><animate attributeName="y" values="{oy};{oy};{my};{ty};{ty};{ty}" keyTimes="{kt}" dur="{ms}ms" repeatCount="indefinite"/><animate attributeName="opacity" values="0;1;1;1;1;0" keyTimes="{kt}" dur="{ms}ms" repeatCount="indefinite"/></rect>')
    items.append('</g>')
    return ''.join(items)


def patch(path):
    p = Path(path)
    svg = p.read_text()
    m = re.search(r'animation:none\s+(\d+)ms', svg)
    old = int(m.group(1))
    new = round(old / PHASE)
    a, b = svg.index('<style>') + 7, svg.index('</style>')
    style = svg[a:b].replace(f'{old}ms', f'{new}ms')
    def scale(m):
        v = float(m.group(1))
        return '100%' if v >= 99.999 else f'{v * PHASE:.2f}'.rstrip('0').rstrip('.') + '%'
    style = re.sub(r'(?<![\w.-])(\d+(?:\.\d+)?)%', scale, style)
    svg = svg[:a] + style + svg[b:]
    svg = svg.replace('</svg>', overlay(new) + '</svg>')
    p.write_text(svg)


for filename in sys.argv[1:]:
    patch(filename)
