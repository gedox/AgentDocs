"""Command-line interface for AgentDocs.

Flow:
    1. Discover pages from the start URL (sitemap + crawl).
    2. Print the discovered tree and ask for confirmation.
    3. On approval, download, convert to Markdown, and write files.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from . import __version__
from .convert import make_session
from .discover import DiscoveryResult, Page
from .providers import select_provider
from .utils import slugify, url_to_relpath


# --------------------------------------------------------------------------- #
# Rendering the discovered list as a tree
# --------------------------------------------------------------------------- #
def _relpath_for_display(page: Page, prefix: str) -> str:
    # Providers that know their own layout (e.g. Obsidian) set relpath.
    if page.relpath:
        return page.relpath
    parsed = urlparse(page.url)
    path = parsed.path
    pre = urlparse(prefix).path.rstrip("/")
    if pre and path.startswith(pre):
        path = path[len(pre):]
    path = path.strip("/") or "(home)"
    if parsed.query:
        path += f"?{parsed.query}"
    return path


def print_tree(result: DiscoveryResult) -> None:
    groups: dict[str, list[tuple[str, Page]]] = defaultdict(list)
    for page in result.pages:
        rel = _relpath_for_display(page, result.prefix)
        top = rel.split("/", 1)[0] if "/" in rel else "(top level)"
        groups[top].append((rel, page))

    tags = {"sitemap": "S", "crawl": "c"}

    print()
    print(f"  Start URL : {result.start_url}")
    if result.site_name:
        print(f"  Site name : {result.site_name}")
    print(f"  Provider  : {result.provider}")
    print(f"  Found     : {len(result.pages)} page(s)")
    print()

    for top in sorted(groups):
        print(f"  {top}/" if top != "(top level)" else "  (top level)")
        for rel, page in sorted(groups[top], key=lambda t: t[0]):
            label = page.title or rel
            tag = tags.get(page.source, "*")
            print(f"     - {rel}   [{tag}]  {label if label != rel else ''}".rstrip())
    print()
    print("  Legend: [S] sitemap   [c] crawl   [*] provider API")
    print()


def confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        print(f"{prompt} y (auto)")
        return True
    try:
        answer = input(f"{prompt} [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")


# --------------------------------------------------------------------------- #
# Writing output
# --------------------------------------------------------------------------- #
def default_out_dir(start_url: str) -> Path:
    host = urlparse(start_url).netloc.replace(":", "_")
    return Path.cwd() / "agentdocs_output" / slugify(host, "site")


def download(provider, result: DiscoveryResult, out_dir: Path, delay: float) -> list[tuple[Page, str]]:
    written: list[tuple[Page, str]] = []
    total = len(result.pages)

    for i, page in enumerate(result.pages, 1):
        rel = page.relpath or url_to_relpath(page.url, result.prefix)
        dest = out_dir / rel
        print(f"  [{i}/{total}] {page.url}")
        converted = provider.fetch(page)
        if not converted:
            print("           ! skipped (fetch/convert failed)")
            continue
        title, markdown = converted
        if title and not page.title:
            page.title = title
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(markdown, encoding="utf-8")
        written.append((page, rel))
        if delay:
            time.sleep(delay)

    return written


def write_index(result: DiscoveryResult, out_dir: Path, written: list[tuple[Page, str]]) -> Path:
    lines = [
        "# Documentation Index",
        "",
        f"Source: {result.start_url}  ",
        f"Pages: {len(written)}",
        "",
    ]
    for page, rel in sorted(written, key=lambda t: t[1]):
        label = page.title or rel
        lines.append(f"- [{label}]({rel}) — <{page.url}>")
    lines.append("")

    # Avoid clobbering a scraped page that already maps to index.md (e.g. a
    # site home page).
    written_rels = {rel for _, rel in written}
    index_name = "index.md" if "index.md" not in written_rels else "_agentdocs_index.md"
    dest = out_dir / index_name
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


# --------------------------------------------------------------------------- #
# Argument parsing / main
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentdocs",
        description="Turn an online documentation site into local Markdown for AI agents.",
    )
    p.add_argument("url", help="Start URL, e.g. https://help.obsidian.md/")
    p.add_argument(
        "--out", "-o", metavar="DIR",
        help="Output directory (default: ./agentdocs_output/<host>)",
    )
    p.add_argument(
        "--prefix", metavar="URL",
        help="Only include pages under this URL prefix (default: the start URL).",
    )
    p.add_argument("--max", type=int, default=500, help="Max pages to discover (default: 500).")
    p.add_argument("--timeout", type=float, default=15.0, help="Per-request timeout seconds (default: 15).")
    p.add_argument("--delay", type=float, default=0.3, help="Delay between downloads in seconds (default: 0.3).")
    p.add_argument("--no-sitemap", action="store_true", help="Skip sitemap.xml discovery.")
    p.add_argument("--no-crawl", action="store_true", help="Skip link crawling.")
    p.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt.")
    p.add_argument(
        "--list-only", action="store_true",
        help="Only discover and print the page list; do not download.",
    )
    p.add_argument("--version", action="version", version=f"AgentDocs {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    print(f"AgentDocs {__version__}")
    print(f"Discovering pages under {args.url} ...")

    session = make_session()
    provider = select_provider(args.url, session, timeout=args.timeout)
    result = provider.discover(
        prefix=args.prefix,
        max_pages=args.max,
        use_sitemap=not args.no_sitemap,
        use_crawl=not args.no_crawl,
    )

    if not result.pages:
        print("\nNo pages found. The site may require JavaScript rendering, "
              "or the prefix is too narrow. Try --prefix or --no-sitemap/--no-crawl toggles.")
        return 1

    print_tree(result)

    if args.list_only:
        return 0

    out_dir = Path(args.out).expanduser() if args.out else default_out_dir(result.start_url)
    print(f"  Output directory: {out_dir}")
    print()

    if not confirm("Does this list match the site? Download and write .md files?", args.yes):
        print("Aborted. No files written.")
        return 0

    print()
    out_dir.mkdir(parents=True, exist_ok=True)
    written = download(provider, result, out_dir, delay=args.delay)
    index_path = write_index(result, out_dir, written)

    print()
    print(f"Done. Wrote {len(written)} Markdown file(s) to {out_dir}")
    print(f"Index: {index_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
