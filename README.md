# Pya

Pya is a simple, scalable monolith for parsing Python source code through ANTLR while keeping the architecture clean enough for future semantic analysis, indexing, and export pipelines.

The project starts from the domain, not from the framework:

* business goal: convert Python source into a stable structural model for downstream tooling
* architectural style: DDD-inspired layered monolith with hexagonal boundaries
* parser engine: ANTLR4 with the public Python3 grammar from `antlr/grammars-v4`, requiring no compatibility patches
* current delivery channel: CLI that parses a file or a directory and returns versioned JSON

## Feature Matrix

| Feature | Priority | Status |
|---------|----------|--------|
| Parse one Python file | p0 | done |
| Parse a directory of Python files | p0 | done |
| Structural model: imports, functions, classes, variables | p0 | done |
| Syntax diagnostics as part of the parse contract | p0 | done |
| Versioned JSON output | p0 | done |
| Async function extraction (`async def`) | p0 | done |
| Control flow extraction (if/elif/else, while, for, try/except, with) | p1 | done |
| Nassi-Shneiderman HTML diagrams per file | p1 | done |
| Nassi-Shneiderman HTML diagram bundles for directories | p1 | done |
| Depth-coded nested conditionals (up to 50 levels) | p1 | done |
| Dark Tokyo Night theme with JetBrains Mono | p1 | done |
| match/case control flow (Python 3.10+) | p1 | planned |
| Decorator extraction | p1 | planned |
| Symbol graph / cross-reference export | p3 | planned |
| Semantic passes (type inference, call graph) | p3 | planned |
| Incremental parsing and caching | p3 | planned |
| Interactive HTML diagrams with collapsible nodes | p3 | planned |
| Export to other diagram formats (SVG, PNG, Mermaid) | p3 | planned |
| Integration adapters for external analysis tools | p3 | planned |

## What the system does

Today the system supports:

* **Parsing Python code**
  * parsing one Python file
  * parsing a directory of Python files
  * extracting a lightweight structural model: imports, function definitions (sync and async), class definitions, and module-level variables
  * reporting syntax diagnostics as part of the contract

* **Control flow extraction**
  * if/elif/else statements with nested branches
  * while loops
  * for loops
  * try/except/finally blocks
  * with statements

* **Nassi-Shneiderman diagrams**
  * building a Nassi-Shneiderman HTML diagram for one Python file
  * building diagram bundles for entire directories with index page
  * classic NS rendering with SVG triangles for if-blocks
  * depth-coded nested ifs (up to 50 levels with color cycling and Unicode badges ①-㊿)
  * classic case block structure with side-by-side columns
  * dark Tokyo Night-inspired theme with JetBrains Mono font
  * proper text wrapping and responsive layout

* **Architecture**
  * keeping parser infrastructure behind ports so the application layer stays independent from ANTLR, filesystem, and CLI details

## Diagram Features

The Nassi-Shneiderman diagrams include:

* **Visual clarity**
  * Classic NS triangles for if-blocks with Yes/No labels
  * Horizontal dividers for case blocks with side-by-side columns
  * Color-coded block types (loops=blue, try/except=orange, with=teal, etc.)
  * JetBrains Mono monospace font for code readability

* **Depth awareness**
  * 50 depth levels with cycling colors (blue → green → purple → teal → amber)
  * Unicode circled badges (①-⑩, ⑪-⑳, ㉑-㉟, ㊱-㊿) on nested conditionals
  * Background tinting for deeper nesting levels

* **Dark theme**
  * Tokyo Night-inspired color palette optimized for code readability
  * Proper contrast ratios for comfortable viewing
  - Responsive layout for different screen sizes

* **Smart parsing**
  * Fast path for simple function bodies
  * Fallback to full-file parse when lightweight scanner cannot isolate function bodies

### Screenshots

**Basic control flow** — loops and try/except blocks:

![Basic NS diagram](docs/screenshots/nassi_diagram.png)

**Nested conditionals** — depth-coded badges and colors for up to 50 nesting levels:

![Nested depth diagram](docs/screenshots/nested_depth.png)

## Architecture

The codebase is split into four explicit layers:

* `domain`: domain model, invariants, ports, and domain events
* `application`: use cases and DTOs
* `infrastructure`: ANTLR adapter, filesystem adapters, event publishing
* `presentation`: CLI contract

See the full design docs in [docs/domain-and-goals.md](docs/domain-and-goals.md), [docs/requirements.md](docs/requirements.md), [docs/system-context.md](docs/system-context.md), [docs/glossary.md](docs/glossary.md), and [docs/architecture.md](docs/architecture.md).

## Quick Start

1. Install dependencies:

```bash
uv sync --extra dev
```

2. Vendor the Python3 grammar from `antlr/grammars-v4/python/python3` into `resources/grammars/python3/`, then generate the parser:

```bash
uv run python scripts/generate_python_parser.py
```

3. Parse a single file:

```bash
uv run pya parse-file path/to/module.py
```

4. Parse a directory:

```bash
uv run pya parse-dir path/to/project
```

5. Build a Nassi-Shneiderman diagram for a Python file:

```bash
uv run pya nassi-file path/to/algorithms.py --out output/algorithms.nassi.html
```

6. Build Nassi-Shneiderman diagrams for an entire directory:

```bash
uv run pya nassi-dir path/to/project --out output/nassi-bundle
```

## Constraints and honesty

The grammar is sourced from `antlr/grammars-v4/python/python3`. It targets the Python 3 grammar and is maintained by the antlr/grammars-v4 community. The grammar does not require compatibility patches for Python target generation. Pya makes grammar limitations explicit in requirements, ADRs, and runtime metadata so downstream consumers know what contract they are integrating with.

## Next Steps

Useful future extensions:

* match/case control flow visualization (Python 3.10+)
* decorator extraction and structural annotation
* symbol graph export
* semantic passes on top of the structural model
* integration adapters for external analysis tools
* incremental parsing and caching
* interactive HTML diagrams with collapsible nodes
* export to other diagram formats (SVG, PNG, Mermaid)
