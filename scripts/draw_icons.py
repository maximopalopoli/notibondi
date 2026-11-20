"""Draw the app icons, and the bus at an angle kept for later.

The icon is a Buenos Aires colectivo from the side, white on blue: three
doors on the right side, the front wheel right behind the front door. The
other drawing is a 3D box seen through a pinhole camera, so its perspective
is right; it has too much detail for an icon, it's kept for the README.

Writes the SVGs to art/ and the PNGs the manifest uses to static/. Needs
rsvg-convert (librsvg).

    uv run python scripts/draw_icons.py
"""

import math
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ART = ROOT / "art"
STATIC = ROOT / "src" / "notibondi" / "static"

BLUE, WHITE = "#1a73e8", "#ffffff"


# ---------- The app icon: a colectivo from the side ----------


def side(fg: str, bg: str) -> str:
    def r(x, y, w, h, rx, c):
        return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{c}"/>'

    def door(x0, x1):
        mid = (x0 + x1) / 2
        return r(x0, 180, x1 - x0, 144, 2, bg) + r(mid - 2.5, 184, 5, 136, 1, fg)

    # Like the photos: the wheel sits up inside its arch, only the bottom
    # third shows below the body
    def wheel(cx):
        return (
            f'<circle cx="{cx}" cy="322" r="38" fill="{bg}"/>'
            f'<circle cx="{cx}" cy="322" r="30" fill="{fg}"/>'
            f'<circle cx="{cx}" cy="322" r="10" fill="{bg}"/>'
        )

    body = (
        '<path d="M56 156H462a10 10 0 0 1 10 10V328a6 6 0 0 1-6 6'
        f'H54a6 6 0 0 1-6-6V164a8 8 0 0 1 8-8z" fill="{fg}"/>'
    )
    return (
        '<g transform="translate(0 8)">'
        + "".join(
            [
                r(196, 142, 168, 24, 3, fg),  # air conditioning on the roof
                body,
                r(108, 266, 296, 12, 0, bg),  # livery stripe
                r(110, 180, 78, 70, 2, bg),  # windows
                r(252, 180, 60, 70, 2, bg),
                r(320, 180, 72, 70, 2, bg),
                door(66, 98),  # rear door, behind the rear wheel
                door(206, 240),  # middle door
                door(404, 436),  # front door, ahead of the front wheel
                f'<path d="M446 176H458a4 4 0 0 1 4 4V296H446z" fill="{bg}"/>',  # windshield
                wheel(160),  # about a quarter from the rear
                wheel(362),  # right behind the front door
            ]
        )
        + "</g>"
    )


# ---------- The bus at an angle, projected (kept for the README) ----------

# x along the bus (0 rear, 12 front), y up, z across (0 = the right side we see)
CAM = (18.0, 1.3, 6.0)
TARGET = (5.6, 1.6, -1.2)
FOCAL = 1.0


def sub(a, b):
    return tuple(p - q for p, q in zip(a, b))


def dot(a, b):
    return sum(p * q for p, q in zip(a, b))


def cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def norm(a):
    n = math.sqrt(dot(a, a))
    return tuple(p / n for p in a)


FWD = norm(sub(TARGET, CAM))
RIGHT = norm(cross(FWD, (0, 1, 0)))
UP = cross(RIGHT, FWD)


def proj(p):
    d = sub(p, CAM)
    z = dot(d, FWD)
    return (FOCAL * dot(d, RIGHT) / z, -FOCAL * dot(d, UP) / z)


def side_quad(x0, x1, y0, y1, z=0.0):
    return [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]


def front_quad(z0, z1, y0, y1, x=12.0):
    return [(x, y0, z0), (x, y0, z1), (x, y1, z1), (x, y1, z0)]


def side_circle(cx, cy, rad, z=0.0, n=40):
    return [
        (cx + rad * math.cos(t), cy + rad * math.sin(t), z)
        for t in (2 * math.pi * i / n for i in range(n))
    ]


def front_circle(cz, cy, rad, x=12.0, n=24):
    return [
        (x, cy + rad * math.sin(t), cz + rad * math.cos(t))
        for t in (2 * math.pi * i / n for i in range(n))
    ]


def three_shapes():
    """(points3d, color, extra) in drawing order; color is 'fg' or 'bg'."""
    s = []
    W = -2.5
    # the body: right side, front, and the AC box on the roof
    s.append((side_quad(0, 12, 0.35, 3.1), "fg", "round"))
    s.append(
        (
            [
                (3.4, 3.1, -0.35),
                (8.2, 3.1, -0.35),
                (8.2, 3.45, -0.35),
                (3.4, 3.45, -0.35),
            ],
            "fg",
            "round",
        )
    )
    s.append(
        (
            [
                (8.2, 3.1, -0.35),
                (8.2, 3.1, -2.15),
                (8.2, 3.45, -2.15),
                (8.2, 3.45, -0.35),
            ],
            "fg",
            "round",
        )
    )
    s.append(
        (
            [
                (3.4, 3.45, -0.35),
                (8.2, 3.45, -0.35),
                (8.2, 3.45, -2.15),
                (3.4, 3.45, -2.15),
            ],
            "fg",
            "round",
        )
    )
    # livery stripe, windows, doors (glass reaches the floor)
    s.append((side_quad(0, 12, 1.05, 1.22), "bg", ""))
    for x0, x1 in [(1.6, 3.85), (5.35, 7.35), (7.5, 9.95)]:
        s.append((side_quad(x0, x1, 1.6, 2.7), "bg", ""))
    for x0, x1 in [(0.35, 1.3), (4.2, 5.15), (10.55, 11.6)]:
        s.append((side_quad(x0, x1, 0.5, 2.7), "bg", ""))
        m = (x0 + x1) / 2
        s.append((side_quad(m - 0.04, m + 0.04, 0.55, 2.65), "fg", ""))
    # wheels
    for cx in (2.65, 9.3):
        s.append((side_circle(cx, 0.5, 0.66), "bg", ""))
        s.append((side_circle(cx, 0.5, 0.5), "fg", ""))
        s.append((side_circle(cx, 0.5, 0.17), "bg", ""))
    # the front, outlined so it separates from the side
    s.append((front_quad(0, W, 0.35, 3.1), "fg", "edge"))
    s.append((front_quad(-0.15, W + 0.15, 2.55, 2.98), "bg", ""))  # the sign
    for z0 in (-0.27, -0.47, -0.67):  # line number
        s.append((front_quad(z0, z0 - 0.12, 2.61, 2.92), "fg", ""))
    s.append((front_quad(-0.95, -2.2, 2.82, 2.89), "fg", ""))  # destination
    s.append((front_quad(-0.95, -1.95, 2.66, 2.73), "fg", ""))
    s.append((front_quad(-0.15, W + 0.15, 1.25, 2.45), "bg", ""))  # windshield
    s.append((front_circle(-0.42, 0.85, 0.13), "bg", ""))  # lights
    s.append((front_circle(W + 0.42, 0.85, 0.13), "bg", ""))
    s.append((front_quad(-0.1, W + 0.1, 0.45, 0.55), "bg", ""))  # bumper
    return s


def three(fg: str, bg: str, size=512, margin=58) -> str:
    shapes = [([proj(p) for p in pts], c, extra) for pts, c, extra in three_shapes()]
    xs = [x for pts, _, _ in shapes for x, _ in pts]
    ys = [y for pts, _, _ in shapes for _, y in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    k = (size - 2 * margin) / max(w, h)
    ox = size / 2 - k * (min(xs) + max(xs)) / 2
    oy = size / 2 - k * (min(ys) + max(ys)) / 2
    out = []
    for pts, c, extra in shapes:
        color = fg if c == "fg" else bg
        d = " ".join(f"{ox + k * x:.1f},{oy + k * y:.1f}" for x, y in pts)
        attrs = f'fill="{color}"'
        if extra == "round":
            attrs += f' stroke="{color}" stroke-width="12" stroke-linejoin="round"'
        elif extra == "edge":
            attrs += f' stroke="{bg}" stroke-width="7" stroke-linejoin="round"'
        out.append(f'<polygon points="{d}" {attrs}/>')
    return "".join(out)


def svg(body: str, bg: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">'
        f'<rect width="512" height="512" fill="{bg}"/>{body}</svg>'
    )


def maskable(body: str) -> str:
    # Android cuts maskable icons into any shape: keep the drawing inside the
    # middle circle (radius 40% of the side)
    return (
        f'<g transform="translate(256 256) scale(0.8) translate(-256 -256)">{body}</g>'
    )


def png(svg_file: Path, png_file: Path, size: int) -> None:
    subprocess.run(
        ["rsvg-convert", "-w", str(size), "-h", str(size), svg_file, "-o", png_file],
        check=True,
    )


if __name__ == "__main__":
    ART.mkdir(exist_ok=True)
    icon = ART / "icon.svg"
    icon.write_text(svg(side(WHITE, BLUE), BLUE))
    icon_maskable = ART / "icon-maskable.svg"
    icon_maskable.write_text(svg(maskable(side(WHITE, BLUE)), BLUE))
    (ART / "bus-angle.svg").write_text(svg(three(BLUE, WHITE), WHITE))

    for size in (180, 192, 512):
        png(icon, STATIC / f"icon-{size}.png", size)
    png(icon_maskable, STATIC / "icon-maskable-512.png", 512)
