"""Draw the placeholder frame used by /simulate/cardiac: a schematic, no real person.

    uv run python demo/frames/make_placeholder.py

Writes demo/frames/simulated_cardiac.jpg (640x480): a floor, a taped zone, a stick figure lying
in it, and the label "SIMULATED FRAME". Replace that file with a real frame only if it is a staged
photo of a teammate who agreed to it.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

OUT = Path(__file__).resolve().parent / "simulated_cardiac.jpg"
W, H = 640, 480


def draw() -> np.ndarray:
    img = np.full((H, W, 3), (205, 200, 195), dtype=np.uint8)  # wall
    cv2.rectangle(img, (0, 210), (W, H), (150, 145, 140), -1)  # floor
    for x in range(-200, W + 200, 60):  # floor seams in perspective
        cv2.line(img, (W // 2 + (x - W // 2) // 4, 210), (x, H), (138, 133, 128), 1, cv2.LINE_AA)

    # Taped zone (yellow dashes) seen from about 2 m up.
    zone = np.array([[150, 280], [490, 280], [585, 450], [55, 450]], dtype=np.int32)
    for i in range(4):
        a, b = zone[i], zone[(i + 1) % 4]
        for s in np.linspace(0, 1, 16)[::2]:
            p = a + (b - a) * s
            q = a + (b - a) * min(1.0, s + 1 / 15)
            cv2.line(img, tuple(int(v) for v in p), tuple(int(v) for v in q), (40, 200, 235), 4, cv2.LINE_AA)

    # Mat and a stick figure lying on its side, head to the right.
    cv2.rectangle(img, (175, 345), (470, 400), (120, 90, 70), -1)
    ink = (40, 40, 40)
    head = (430, 362)
    neck, hip = (405, 368), (305, 372)
    cv2.circle(img, head, 15, ink, 3, cv2.LINE_AA)
    for a, b in [
        (neck, hip),
        (neck, (350, 386)),
        ((350, 386), (300, 389)),
        (neck, (372, 352)),
        ((372, 352), (330, 358)),
        (hip, (245, 380)),
        ((245, 380), (195, 384)),
        (hip, (250, 366)),
        ((250, 366), (198, 372)),
    ]:
        cv2.line(img, a, b, ink, 4, cv2.LINE_AA)

    # Labels.
    cv2.rectangle(img, (0, 0), (W, 70), (30, 30, 30), -1)
    cv2.putText(
        img, "SIMULATED FRAME", (20, 45), cv2.FONT_HERSHEY_DUPLEX, 1.2, (255, 255, 255), 2, cv2.LINE_AA
    )
    cv2.putText(
        img,
        "placeholder for /simulate/cardiac - no real person",
        (20, 64),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45,
        (210, 210, 210),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        img, "cam-lobby-1", (W - 130, H - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (60, 60, 60), 1, cv2.LINE_AA
    )
    return img


if __name__ == "__main__":
    ok = cv2.imwrite(str(OUT), draw(), [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    print(("wrote " if ok else "failed to write ") + str(OUT))
