"""Primitivas geométricas. Ângulos em graus, distâncias em unidades de imagem."""

from __future__ import annotations

import math

from .types import Point


def distance(a: Point, b: Point) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def angle(a: Point, b: Point, c: Point) -> float:
    """Ângulo interno em `b`, no triângulo a-b-c, em graus [0, 180]."""
    v1 = (a.x - b.x, a.y - b.y)
    v2 = (c.x - b.x, c.y - b.y)
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 == 0 or n2 == 0:
        return float("nan")
    cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def angle_to_vertical(a: Point, b: Point) -> float:
    """Ângulo do segmento a→b face à vertical, com sinal.

    Positivo quando `b` está à direita de `a` na imagem. Zero é perfeitamente
    vertical, independentemente do sentido.
    """
    dx = b.x - a.x
    dy = b.y - a.y
    if dx == 0 and dy == 0:
        return float("nan")
    return math.degrees(math.atan2(dx, -dy)) if dy < 0 else math.degrees(math.atan2(dx, dy))


def angle_to_horizontal(a: Point, b: Point) -> float:
    """Ângulo do segmento a→b face à horizontal, em graus [-90, 90]."""
    dx = b.x - a.x
    dy = b.y - a.y
    if dx == 0 and dy == 0:
        return float("nan")
    return math.degrees(math.atan2(-dy, abs(dx)))


def midpoint(a: Point, b: Point) -> Point:
    return Point(
        (a.x + b.x) / 2,
        (a.y + b.y) / 2,
        min(a.confidence, b.confidence),
    )


def signed_angle_between(a1: Point, a2: Point, b1: Point, b2: Point) -> float:
    """Ângulo entre as direcções a1→a2 e b1→b2, em graus [-180, 180]."""
    t1 = math.atan2(a2.y - a1.y, a2.x - a1.x)
    t2 = math.atan2(b2.y - b1.y, b2.x - b1.x)
    d = math.degrees(t2 - t1)
    while d > 180:
        d -= 360
    while d < -180:
        d += 360
    return d


def two_link_ik(
    root: Point, end: Point, l1: float, l2: float, flip: bool = False
) -> Point:
    """Posição da articulação intermédia de uma cadeia de dois segmentos.

    Usado pelo gerador sintético para produzir joelhos plausíveis a partir de
    trajectórias de anca e tornozelo.
    """
    dx, dy = end.x - root.x, end.y - root.y
    d = math.hypot(dx, dy)
    d = max(abs(l1 - l2) + 1e-6, min(l1 + l2 - 1e-6, d))
    a = (l1 * l1 - l2 * l2 + d * d) / (2 * d)
    h_sq = max(0.0, l1 * l1 - a * a)
    h = math.sqrt(h_sq)
    ux, uy = dx / d, dy / d
    px, py = root.x + a * ux, root.y + a * uy
    sign = -1.0 if flip else 1.0
    return Point(px + sign * h * (-uy), py + sign * h * ux)
