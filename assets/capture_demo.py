"""Record a demo GIF of the AgentDocs UI for the landing page.

Drives the real app with Playwright, captures frames at each beat of the
story, and assembles an optimised animated GIF.

    python -m pip install playwright && python -m playwright install chromium
    python assets/capture_demo.py

The UI must already be running (python -m agentdocs.ui).
"""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8765/"
VIEWPORT = {"width": 1280, "height": 800}
SITE = Path(__file__).parent.parent / "site"
OUT_GIF = SITE / "demo.gif"
OUT_MP4 = SITE / "demo.mp4"
OUT_POSTER = SITE / "demo.png"

GIF_WIDTH = 960          # downscale keeps the file small and crisp
FRAME_MS = 90            # base tick between captured frames
FPS = 12                 # fixed rate the still frames are expanded to
DOCSET = "obsidian"      # the doc set to showcase

frames: list[tuple[Image.Image, int]] = []


def shot(page, hold_ms: int = FRAME_MS) -> None:
    """Capture one frame and hold it for hold_ms."""
    img = Image.open(io.BytesIO(page.screenshot(type="png"))).convert("RGB")
    frames.append((img, hold_ms))


def beat(page, hold_ms: int, steps: int = 3, step_ms: int = 90) -> None:
    """Capture a short burst (motion) then hold the final frame."""
    for _ in range(steps):
        page.wait_for_timeout(step_ms)
        shot(page)
    shot(page, hold_ms)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(1200)

        # Collapse the terminal drawer: empty, it is a dead dark band that
        # eats a quarter of the frame. The docs → blueprint story is the point.
        try:
            if not page.locator("#terminalBody.collapsed").count():
                page.click("#termToggle")
                page.wait_for_timeout(350)
        except Exception:
            pass

        # ---- beat 1: the workbench, doc sets discovered -------------------
        shot(page, 1100)

        # ---- beat 2: open the doc set ------------------------------------
        card = page.locator(".docset", has=page.locator(f".ds-name:has-text('{DOCSET}')")).first
        card.scroll_into_view_if_needed()
        card.hover()
        shot(page, 260)
        card.click()
        page.wait_for_selector(".ft-file", timeout=15000)
        beat(page, 1400)

        # ---- beat 3: read a page -----------------------------------------
        files = page.locator(".ft-file")
        target = files.nth(min(2, files.count() - 1))
        target.hover()
        shot(page, 220)
        target.click()
        page.wait_for_selector("#reader .markdown", timeout=15000)
        beat(page, 1500)

        # gentle scroll through the rendered doc
        for _ in range(3):
            page.eval_on_selector("#reader", "el => el.scrollBy({top: 170, behavior:'instant'})")
            page.wait_for_timeout(110)
            shot(page)
        shot(page, 900)

        # ---- beat 4: the blueprint tab -----------------------------------
        page.click(".tab[data-tab='blueprint']")
        page.wait_for_timeout(500)
        beat(page, 1700)

        # ---- beat 5: preview a generated spec ----------------------------
        bp = page.locator(".bp-file")
        if bp.count():
            item = bp.nth(min(1, bp.count() - 1))
            item.hover()
            shot(page, 240)
            item.click()
            page.wait_for_selector("#modal:not(.hidden)", timeout=15000)
            page.wait_for_timeout(450)
            beat(page, 1900)

            for _ in range(3):
                page.eval_on_selector("#modalBody", "el => el.scrollBy({top: 150, behavior:'instant'})")
                page.wait_for_timeout(110)
                shot(page)
            shot(page, 2200)

        # poster frame for social / fallback
        OUT_POSTER.parent.mkdir(parents=True, exist_ok=True)
        frames[0][0].save(OUT_POSTER, optimize=True)
        browser.close()

    if not frames:
        print("no frames captured", file=sys.stderr)
        return 1

    return encode(frames)


def encode(frames: list[tuple[Image.Image, int]]) -> int:
    """Expand variable-duration frames to a fixed frame rate, then let ffmpeg
    produce the video and the GIF.

    ffmpeg's palettegen/paletteuse gives a dramatically better GIF than a
    single quantised palette, and h264 gives a hero that is both smaller and
    sharper than any GIF.
    """
    OUT_GIF.parent.mkdir(parents=True, exist_ok=True)

    # h264 needs even dimensions.
    w, h = frames[0][0].size
    size = (GIF_WIDTH, (int(h * GIF_WIDTH / w) // 2) * 2)

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        n = 0
        for img, hold in frames:
            repeat = max(1, round(hold / (1000 / FPS)))
            resized = img.resize(size, Image.LANCZOS)
            for _ in range(repeat):
                resized.save(tmpdir / f"f_{n:05d}.png")
                n += 1
        pattern = str(tmpdir / "f_%05d.png")
        print(f"expanded to {n} frames @ {FPS}fps ({n / FPS:.1f}s)")

        def run(args: list[str]) -> None:
            subprocess.run(args, check=True, capture_output=True)

        # --- MP4 hero ------------------------------------------------------
        run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", pattern,
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "24",
             "-preset", "slow", "-movflags", "+faststart",
             "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", str(OUT_MP4)])

        # --- shareable GIF (palettegen → paletteuse) ------------------------
        palette = tmpdir / "palette.png"
        gif_w = 800
        vf = f"fps={FPS},scale={gif_w}:-1:flags=lanczos"
        run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", pattern,
             "-vf", f"{vf},palettegen=max_colors=192:stats_mode=diff", str(palette)])
        run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", pattern, "-i", str(palette),
             "-lavfi", f"{vf}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle",
             "-loop", "0", str(OUT_GIF)])

    for f in (OUT_MP4, OUT_GIF, OUT_POSTER):
        if f.exists():
            print(f"wrote {f.name:12s} {f.stat().st_size / 1024:7.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
