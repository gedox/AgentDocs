"""Build the AgentDocs Windows icon and web favicon from the source artwork.

The source PNG (`agentdocs-icon.png`) was designed in Canva to match the app's
drafting-table identity. Run this only when the artwork changes:

    python assets/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).parent
SOURCE = ASSETS / "agentdocs-icon.png"
ICO = ASSETS / "agentdocs.ico"
FAVICON = ASSETS.parent / "agentdocs" / "ui" / "static" / "favicon.ico"

# Windows picks the closest match from these; include the small sizes explicitly
# so the shell never has to downscale the 512px artwork itself.
SIZES = [256, 128, 64, 48, 32, 16]


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"Missing source artwork: {SOURCE}")

    img = Image.open(SOURCE).convert("RGBA")
    # Square-crop defensively in case the source is not 1:1.
    side = min(img.size)
    left = (img.width - side) // 2
    top = (img.height - side) // 2
    img = img.crop((left, top, left + side, top + side))

    frames = [img.resize((s, s), Image.LANCZOS) for s in SIZES]

    ICO.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(ICO, format="ICO", sizes=[(s, s) for s in SIZES])

    FAVICON.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(FAVICON, format="ICO", sizes=[(s, s) for s in (48, 32, 16)])

    print(f"wrote {ICO}  ({ICO.stat().st_size} bytes)")
    print(f"wrote {FAVICON}  ({FAVICON.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
