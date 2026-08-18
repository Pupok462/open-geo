import argparse
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(REPO, ".venv", "bin", "python")
ASSETS = os.path.join(REPO, "assets")


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout + proc.stderr)
        raise SystemExit(f"failed: {' '.join(cmd)}")


def trim_trailing_space(png_path: str, footer_band: float = 0.10, pad: int = 40) -> None:
    from PIL import Image

    img = Image.open(png_path).convert("RGB")
    w, h = img.size
    bg = img.getpixel((2, 2))
    body_bottom = int(h * (1.0 - footer_band))
    px = img.load()
    last = None
    for y in range(body_bottom - 1, -1, -1):
        row_has_ink = any(px[x, y] != bg for x in range(0, w, 3))
        if row_has_ink:
            last = y
            break
    if last is None or last + pad >= h:
        return
    img.crop((0, 0, w, min(h, last + pad))).save(png_path)


def rasterize(pdf: str, page: int, out_png: str, dpi: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        prefix = os.path.join(tmp, "page")
        run(
            [
                "pdftoppm",
                "-png",
                "-r",
                str(dpi),
                "-f",
                str(page),
                "-l",
                str(page),
                pdf,
                prefix,
            ]
        )
        produced = [f for f in os.listdir(tmp) if f.endswith(".png")]
        if not produced:
            raise SystemExit(f"pdftoppm produced nothing for page {page}")
        shutil.move(os.path.join(tmp, produced[0]), out_png)


def main() -> int:
    ap = argparse.ArgumentParser(prog="scripts/make_report_assets.py")
    ap.add_argument("--cover-page", type=int, default=1)
    ap.add_argument("--metrics-page", type=int, default=2)
    ap.add_argument("--dpi", type=int, default=150)
    args = ap.parse_args()

    os.makedirs(ASSETS, exist_ok=True)
    sample = os.path.join(ASSETS, "sample-report-example.pdf")

    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "demo.db")
        run([PY, "-m", "pipeline.seed_demo", "--db", db])
        run(
            [
                PY,
                "-m",
                "report.generate",
                "--brand",
                "Example",
                "--domain",
                "example.com",
                "--engine",
                "google",
                "--period",
                "all",
                "--lang",
                "en",
                "--db",
                db,
                "--out",
                sample,
            ]
        )

    cover = os.path.join(ASSETS, "report-cover.png")
    metrics = os.path.join(ASSETS, "report-metrics.png")
    rasterize(sample, args.cover_page, cover, args.dpi)
    rasterize(sample, args.metrics_page, metrics, args.dpi)
    trim_trailing_space(metrics)

    for name in ("sample-report-example.pdf", "report-cover.png", "report-metrics.png"):
        path = os.path.join(ASSETS, name)
        print(f"{name}: {os.path.getsize(path) // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
