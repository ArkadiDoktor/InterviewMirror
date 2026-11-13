"""Build the face mesh that lets the browser animate a still portrait.

Run this once per portrait photo (dev machine only - it is NOT needed at runtime):

    pip install "mediapipe==0.10.14" opencv-python scipy numpy
    python tools/build_avatar_mesh.py im/assets/friendly.jpg

It writes ``<photo>.mesh.json`` next to the photo, containing:
  * ``lm``    - 478 face landmarks as flat [x, y, z, ...] in pixels
  * ``extra`` - helper points around the head and on the image border,
                flat [x, y, follow, ...] where ``follow`` (0..1) says how much
                the point moves together with the head
  * ``outer`` - triangles covering the whole image (background, hair, shoulders)

With ``--topology`` it also (re)writes ``im/assets/face_topology.json``: the
triangle list of the face itself, which is identical for every face.

Photo tips: frontal face, mouth closed, neutral or light smile, eyes open,
square crop with a little space above the hair, 300-600 px.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial import Delaunay

RING_A_SCALE, RING_A_FOLLOW = 1.28, 0.7
RING_B_SCALE, RING_B_FOLLOW = 1.75, 0.25
BORDER_STEPS = 6
MIN_DIST = 6.0


def _ordered_oval(face_mesh_module) -> list[int]:
    """Return the face-oval landmark ids as one closed loop."""
    nxt: dict[int, list[int]] = {}
    for a, b in face_mesh_module.FACEMESH_FACE_OVAL:
        nxt.setdefault(a, []).append(b)
        nxt.setdefault(b, []).append(a)
    start = next(iter(nxt))
    loop, prev, cur = [start], None, start
    while True:
        options = [n for n in nxt[cur] if n != prev]
        if not options or options[0] == start:
            break
        prev, cur = cur, options[0]
        loop.append(cur)
    return loop


def face_topology(face_mesh_module) -> list[int]:
    """All triangles of the canonical face mesh (mouth and eyes are holes)."""
    edges = {(min(a, b), max(a, b)) for a, b in face_mesh_module.FACEMESH_TESSELATION}
    adj: dict[int, set[int]] = {}
    for a, b in edges:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    tris = set()
    for a, b in edges:
        for c in adj[a] & adj[b]:
            tris.add(tuple(sorted((a, b, c))))
    return [i for t in sorted(tris) for i in t]


def build(photo: Path, write_topology: bool) -> Path:
    import mediapipe as mp

    if not hasattr(mp, "solutions"):
        sys.exit('This tool needs the legacy "solutions" API: pip install "mediapipe==0.10.14"')
    fm = mp.solutions.face_mesh

    img = cv2.imread(str(photo))
    if img is None:
        sys.exit(f"Cannot read {photo}")
    h, w = img.shape[:2]
    with fm.FaceMesh(static_image_mode=True, refine_landmarks=True, max_num_faces=1) as mesh:
        res = mesh.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    if not res.multi_face_landmarks:
        sys.exit("No face found - use a clear frontal portrait.")
    pts = res.multi_face_landmarks[0].landmark
    lm = np.array([[p.x * w, p.y * h, p.z * w] for p in pts], dtype=float)

    oval = _ordered_oval(fm)
    center = lm[oval, :2].mean(axis=0)

    extra: list[list[float]] = []

    def add(x: float, y: float, follow: float) -> None:
        inside = 2 <= x <= w - 2 and 2 <= y <= h - 2
        if not inside:  # outside the photo: pin it to the border, it must not move
            x, y, follow = float(np.clip(x, 0, w)), float(np.clip(y, 0, h)), 0.0
        for e in extra:
            if (e[0] - x) ** 2 + (e[1] - y) ** 2 < MIN_DIST**2:
                e[2] = min(e[2], follow)
                return
        extra.append([x, y, follow])

    for i in range(BORDER_STEPS + 1):  # fixed frame first, so it wins de-duplication
        t = i / BORDER_STEPS
        for x, y in ((t * w, 0), (t * w, h), (0, t * h), (w, t * h)):
            add(x, y, 0.0)
    for scale, follow in ((RING_A_SCALE, RING_A_FOLLOW), (RING_B_SCALE, RING_B_FOLLOW)):
        for idx in oval:
            p = center + scale * (lm[idx, :2] - center)
            add(float(p[0]), float(p[1]), follow)

    outer_ids = oval + [478 + i for i in range(len(extra))]
    outer_xy = np.array([lm[i, :2] if i < 478 else extra[i - 478][:2] for i in outer_ids])
    tri = Delaunay(outer_xy)
    outer = [int(outer_ids[i]) for simplex in tri.simplices for i in simplex]

    out = {
        "w": w,
        "h": h,
        "lm": [round(float(v), 2) for v in lm.reshape(-1)],
        "extra": [round(float(v), 2) for e in extra for v in e],
        "outer": outer,
    }
    target = photo.with_suffix(".mesh.json")
    target.write_text(json.dumps(out, separators=(",", ":")))
    if write_topology:
        topo = photo.parent / "face_topology.json"
        topo.write_text(json.dumps({"tris": face_topology(fm)}, separators=(",", ":")))
        print(f"wrote {topo}")
    print(f"wrote {target}  ({len(extra)} helper points, {len(outer) // 3} outer triangles)")
    return target


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo", type=Path, nargs="+")
    ap.add_argument("--topology", action="store_true", help="also rewrite face_topology.json")
    args = ap.parse_args()
    for i, p in enumerate(args.photo):
        build(p, args.topology and i == 0)
