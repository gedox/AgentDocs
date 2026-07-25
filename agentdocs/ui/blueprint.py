"""Turn a folder of documentation into an AI-buildable blueprint.

A *blueprint* is a set of functional-specification Markdown files that describe
WHAT a piece of software must do and HOW it must behave — precise enough that an
AI coding agent can implement it from scratch without guessing. It is generated
by a local Ollama model, one file per top-level documentation category, plus a
synthesised overview.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .ollama_client import OllamaError, generate, generate_stream

# Character budget per category fed to the model (keeps generation responsive).
CATEGORY_CHAR_BUDGET = 14000
BLUEPRINT_DIRNAME = "_blueprint"

# Generation options. num_predict caps output so a single verbose model can't
# stall the run; temperature stays low for consistent, factual specs.
GEN_OPTIONS = {"temperature": 0.2, "num_predict": 1600}
OVERVIEW_OPTIONS = {"temperature": 0.3, "num_predict": 1200}

SYSTEM_PROMPT = (
    "You are a senior software architect. You are given end-user documentation "
    "for a piece of software. Convert it into a precise FUNCTIONAL SPECIFICATION "
    "that an AI coding agent can implement from scratch, without access to the "
    "original product and without guessing.\n\n"
    "Rules:\n"
    "- Describe WHAT must be built and HOW it must behave — features, user-facing "
    "behaviours, inputs, outputs, states, validation rules, and edge cases.\n"
    "- Do NOT write a user manual or marketing copy. Write build requirements.\n"
    "- Use numbered functional requirements (FR-1, FR-2, ...). Be concrete and "
    "unambiguous. Prefer bullet lists and short tables over prose.\n"
    "- Where the docs imply data structures, commands, or settings, specify them "
    "explicitly (fields, types, defaults).\n"
    "- Output GitHub-flavoured Markdown only. No preamble, no apologies."
)


def _iter_md_files(root: Path) -> list[Path]:
    files = [
        p
        for p in root.rglob("*.md")
        if BLUEPRINT_DIRNAME not in p.relative_to(root).parts
        and p.name not in ("index.md", "_agentdocs_index.md")
    ]
    return sorted(files)


def _group_by_category(root: Path, files: list[Path]) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for f in files:
        rel = f.relative_to(root)
        category = rel.parts[0] if len(rel.parts) > 1 else "(root)"
        groups.setdefault(category, []).append(f)
    return dict(sorted(groups.items()))


def _read_budgeted(root: Path, files: list[Path], budget: int) -> str:
    parts: list[str] = []
    used = 0
    for f in files:
        if used >= budget:
            parts.append(f"\n\n[... {len(files)} files total; remainder truncated ...]")
            break
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = f.relative_to(root).as_posix()
        remaining = budget - used
        snippet = text[:remaining]
        parts.append(f"\n\n===== FILE: {rel} =====\n{snippet}")
        used += len(snippet) + len(rel) + 20
    return "".join(parts).strip()


def _slug(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in " -_" else "-" for c in name)
    return "-".join(keep.lower().split()) or "section"


def build_blueprint(docset_path: str, model: str) -> Iterator[dict]:
    """Generate a blueprint, yielding event dicts for streaming to the UI.

    Event shapes:
      {"type": "status", "message": str, "step": int, "total": int}
      {"type": "token",  "text": str}                # live model output
      {"type": "file",   "path": str, "name": str}   # a spec file was written
      {"type": "error",  "message": str}
      {"type": "done",   "dir": str, "files": int}
    """
    root = Path(docset_path).expanduser()
    if not root.is_dir():
        yield {"type": "error", "message": f"Not a folder: {root}"}
        return

    files = _iter_md_files(root)
    if not files:
        yield {"type": "error", "message": "No Markdown files found in this folder."}
        return

    groups = _group_by_category(root, files)
    out_dir = root / BLUEPRINT_DIRNAME
    out_dir.mkdir(exist_ok=True)

    total = len(groups) + 1  # categories + overview
    written: list[tuple[str, str]] = []  # (title, filename)
    category_digests: list[str] = []

    for i, (category, cat_files) in enumerate(groups.items(), 1):
        yield {
            "type": "status",
            "message": f"Specifying '{category}' ({len(cat_files)} doc(s))",
            "step": i,
            "total": total,
        }
        corpus = _read_budgeted(root, cat_files, CATEGORY_CHAR_BUDGET)
        prompt = (
            f"The software is documented below. Produce the functional "
            f"specification for the area: \"{category}\".\n\n"
            f"Begin with a level-1 heading naming this area, then a one-paragraph "
            f"purpose, then the numbered functional requirements.\n\n"
            f"----- DOCUMENTATION -----\n{corpus}\n----- END DOCUMENTATION -----"
        )

        collected: list[str] = []
        try:
            for chunk in generate_stream(model, prompt, system=SYSTEM_PROMPT, options=GEN_OPTIONS):
                collected.append(chunk)
                yield {"type": "token", "text": chunk}
        except OllamaError as exc:
            yield {"type": "error", "message": f"Ollama error: {exc}"}
            return

        body = "".join(collected).strip()
        if not body:
            continue
        filename = f"{i:02d}-{_slug(category)}.md"
        header = f"<!-- AgentDocs blueprint · source area: {category} · model: {model} -->\n\n"
        (out_dir / filename).write_text(header + body + "\n", encoding="utf-8")
        written.append((category, filename))
        category_digests.append(f"## {category}\n{body[:600]}")
        yield {"type": "file", "path": str(out_dir / filename), "name": filename}

    # ---- Synthesised overview -------------------------------------------- #
    yield {"type": "status", "message": "Synthesising overview", "step": total, "total": total}
    digest = "\n\n".join(category_digests)[: CATEGORY_CHAR_BUDGET]
    overview_prompt = (
        "Below are per-area functional specifications for one software product. "
        "Write a top-level BLUEPRINT OVERVIEW that an AI agent reads first.\n\n"
        "Include: (1) one-paragraph product purpose; (2) 'Core capabilities' as a "
        "bullet list; (3) 'Suggested modules / architecture' mapping capabilities "
        "to components; (4) a short glossary of domain terms. Markdown only.\n\n"
        f"----- AREA SPECS -----\n{digest}\n----- END -----"
    )
    try:
        overview = generate(model, overview_prompt, system=SYSTEM_PROMPT, options=OVERVIEW_OPTIONS)
    except OllamaError as exc:
        overview = f"_Overview generation failed: {exc}_"

    contents_lines = "\n".join(f"- [{title}]({fname})" for title, fname in written)
    overview_doc = (
        f"# Build Blueprint — {root.name}\n\n"
        f"_Generated by AgentDocs from the documentation in `{root.name}` "
        f"using the local model `{model}`._\n\n"
        f"This blueprint is a functional specification: give it to an AI coding "
        f"agent to build the software described by the source documentation.\n\n"
        f"## Contents\n\n{contents_lines}\n\n---\n\n{overview}\n"
    )
    (out_dir / "00-overview.md").write_text(overview_doc, encoding="utf-8")
    yield {"type": "file", "path": str(out_dir / "00-overview.md"), "name": "00-overview.md"}

    yield {"type": "done", "dir": str(out_dir), "files": len(written) + 1}
