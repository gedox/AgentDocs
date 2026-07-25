# AgentDocs

Turn an online documentation site into a local folder of clean Markdown files —
one `.md` per page, mirroring the site's structure — ready to feed to AI agents.
Then turn those docs into a **build blueprint** with a local LLM.

> **Just want the app?** Run `python -m agentdocs.ui`, or create a one-click
> desktop launcher:
>
> ```bash
> powershell -ExecutionPolicy Bypass -File assets/make_launcher.ps1
> ```
>
> That writes `Launch AgentDocs.lnk` (with the app icon) into this folder.
> It isn't committed because a Windows shortcut hard-codes absolute paths.

---

## The UI

```bash
python -m agentdocs.ui
```

Opens a local app at <http://127.0.0.1:8765> (bound to localhost only). It has
four parts:

**1. Documentation browser** — Load any folder. AgentDocs finds the documentation
sets inside it (any subfolder containing `.md` files) and lists them with page
counts. Click a set to browse its pages grouped by category, and click any page
to read it rendered.

**2. Blueprint generator** — Pick a doc set, choose one of your local Ollama
models, and hit **Create blueprint**. AgentDocs feeds the documentation to the
model category by category and writes a `_blueprint/` folder of functional
specification files: numbered requirements (FR-1, FR-2, …), behaviours, inputs
and outputs, edge cases, plus a synthesised `00-overview.md` with core
capabilities, suggested architecture, and a glossary.

The point: hand the blueprint to an AI coding agent and it knows what to build
and how, without guessing. Generation streams live, and every generated file can
be previewed in-app.

> Bigger models give noticeably better fidelity. A 2B model will invent details;
> something like `qwen3.6:27b` stays much closer to the source docs.

**3. Command shortcuts** — Every project command, ready to copy or send straight
to the terminal.

**4. Mini terminal** — Run commands without leaving the app. Output streams live.
The working directory follows whichever folder you have loaded.

Requires [Ollama](https://ollama.com) running locally for blueprints; everything
else works without it.

---

## The scraper

You give it a documentation URL. It **discovers every page**, shows you the full
list as a tree, and **waits for your confirmation**. Only after you approve does
it download the pages, convert them to Markdown, and write the files.

```
python -m agentdocs https://help.obsidian.md/
```

## How it works

1. **Discover** — AgentDocs enumerates the site's pages. It picks the best
   strategy automatically (see *Providers* below).
2. **Confirm** — it prints the discovered pages as a tree and asks:
   *"Does this list match the site? Download and write .md files?"*
   Compare it against the site's own navigation; if it matches, type `y`.
3. **Download** — each page is fetched, stripped of navigation/header/footer
   chrome, converted to Markdown, and saved. An `index.md` table of contents is
   written alongside.

Nothing is written to disk until you confirm.

## Install

```bash
pip install -r requirements.txt
```

Requires Python 3.10+.

## Usage

```bash
# See the full page list without downloading anything:
python -m agentdocs https://help.obsidian.md/ --list-only

# Download everything (asks for confirmation first):
python -m agentdocs https://help.obsidian.md/

# Choose an output directory and skip the prompt:
python -m agentdocs https://www.mkdocs.org/ --out ./mkdocs-docs --yes

# Only include pages under a sub-section:
python -m agentdocs https://www.mkdocs.org/ --prefix https://www.mkdocs.org/user-guide/
```

### Options

| Flag | Description |
|------|-------------|
| `--out DIR`, `-o` | Output directory (default: `./agentdocs_output/<host>`) |
| `--prefix URL` | Only include pages under this URL prefix |
| `--max N` | Maximum pages to discover (default: 500) |
| `--timeout SECS` | Per-request timeout (default: 15) |
| `--delay SECS` | Delay between downloads, to be polite (default: 0.3) |
| `--no-sitemap` | Skip `sitemap.xml` discovery |
| `--no-crawl` | Skip link crawling |
| `--yes`, `-y` | Skip the confirmation prompt |
| `--list-only` | Discover and print the list only; never download |

## Output layout

```
agentdocs_output/help.obsidian.md/
├── index.md                         # table of contents (links to every page)
├── Getting started/
│   ├── Create a vault.md
│   └── Create your first note.md
├── Plugins/
│   └── ...
└── ...
```

Each file starts with a small source reference so an agent (or you) can trace
any page back to its origin URL.

After generating a blueprint, the doc set gains a `_blueprint/` folder:

```
agentdocs_output/help.obsidian.md/
├── _blueprint/
│   ├── 00-overview.md               # purpose, capabilities, architecture, glossary
│   ├── 01-getting-started.md        # numbered functional requirements
│   └── 02-plugins.md
└── … the scraped docs …
```

## Project layout

```
AgentDocs/
├── AgentDocs.bat           # what the desktop launcher runs
├── site/                   # the landing page (static, deploys anywhere)
├── agentdocs/
│   ├── cli.py              # scraper CLI (discover → confirm → download)
│   ├── discover.py         # sitemap + crawl page discovery
│   ├── convert.py          # HTML → Markdown
│   ├── providers/          # generic + Obsidian Publish extraction
│   └── ui/
│       ├── server.py       # local HTTP + SSE server
│       ├── blueprint.py    # docs → functional specification
│       ├── ollama_client.py
│       └── static/         # the UI (HTML/CSS/JS, no build step)
└── assets/                 # app icon + generator script
```

## Providers

AgentDocs classifies the site and uses the right extraction strategy:

- **Generic** — ordinary server-rendered HTML sites. Discovers pages via
  `sitemap.xml` (most reliable) and by crawling in-page navigation links,
  restricted to the same host and under the start URL's path. Content is
  extracted from the main article region and converted HTML → Markdown.

- **Obsidian Publish** — sites on `publish.obsidian.md` (including
  `help.obsidian.md`). These render entirely in JavaScript, so plain scraping
  sees nothing. AgentDocs instead reads Obsidian Publish's JSON API to get the
  exact page list and navigation order, and downloads each note's **original
  raw Markdown** — frontmatter and `[[wiki-links]]` preserved.

The provider is chosen automatically; you don't need to specify it.

## Notes & limitations

- Be considerate of the sites you scrape; the default `--delay` throttles
  requests. Respect each site's terms of use and copyright.
- Generic discovery relies on a sitemap or server-rendered links. A JavaScript
  single-page docs site with no sitemap and no provider support may return few
  pages — support for more such sites can be added as new providers.
