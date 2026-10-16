"""Draw the pictures in docs/images that come from data.

Run from the repo root: python scripts/make_doc_images.py

The two circuit pictures (circuit-sum-1.png, circuit-sum-8.png) are tididi's
real circuits, exported with to_dot(), relabelled by hand and drawn with
Graphviz. They are kept as files and not regenerated here.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.datasets import load_digits

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"


def digit_seven() -> None:
    """Image 7 of scikit-learn's digits: as you see it, and as the network gets it."""
    digits = load_digits()
    pixels = digits.data[7] / 16
    assert digits.target[7] == 7

    fig = plt.figure(figsize=(9, 2.8))
    grid = fig.add_axes((0.03, 0.12, 0.22, 0.76))
    grid.imshow(pixels.reshape(8, 8), cmap="gray_r", vmin=0, vmax=1)
    grid.set_xticks([])
    grid.set_yticks([])
    grid.set_title("what you see: 8 × 8 pixels", fontsize=10)

    strip = fig.add_axes((0.32, 0.45, 0.65, 0.18))
    strip.imshow(pixels.reshape(1, 64), cmap="gray_r", vmin=0, vmax=1, aspect="auto")
    strip.set_yticks([])
    strip.set_xticks([0, 63], ["row 1", "row 8"])
    strip.set_title("what the network gets: one row of 64 numbers", fontsize=10)
    first = ", ".join(f"{v:.2g}" for v in pixels[:8])
    fig.text(0.32, 0.2, f"Starts {first} (the top bar of the 7)", fontsize=9)

    fig.savefig(OUT / "digit-7-pixels.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    digit_seven()
    print("wrote", OUT / "digit-7-pixels.png")
