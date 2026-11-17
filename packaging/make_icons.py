"""Turn App/brand/logo.svg into every icon the app, installer and website use. Needs rsvg-convert and Pillow."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "App" / "brand" / "logo.svg"
SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]


def render(size, out):
    subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), str(SVG), "-o", str(out)], check=True)


def main():
    if len(sys.argv) > 1:
        src = ROOT / "App" / "brand" / "options" / f"{sys.argv[1]}.svg"
        shutil.copyfile(src, SVG)
    tmp = Path(tempfile.mkdtemp())
    imgs = []
    for s in SIZES:
        p = tmp / f"{s}.png"
        render(s, p)
        imgs.append(Image.open(p).convert("RGBA"))
    imgs[-1].save(ROOT / "App" / "sc_copilot.png")
    imgs[-1].save(ROOT / "App" / "sc_copilot.ico", sizes=[(s, s) for s in SIZES], append_images=imgs[:-1])
    site = ROOT / "docs" / "site" / "img"
    site.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SVG, site / "logo.svg")
    render(512, site / "logo-512.png")
    render(180, site / "apple-touch-icon.png")
    imgs[3].save(site / "favicon-32.png")
    print(f"icons made from {SVG.name}")


if __name__ == "__main__":
    main()
