# Roadmap

This roadmap reflects the actual state of the Python implementation in this repository.

## Shipped

### P0 Foundation

* Parse one Python file
* Parse a directory of Python files
* Ignore non-`.py` files during recursive discovery
* Return versioned JSON parse reports
* Capture syntax diagnostics with line and column metadata
* Aggregate file results into a parsing job report
* Expose grammar version and report schema version
* Distinguish success, success-with-diagnostics, and technical failure
* Extract structural elements for imports, classes, functions, async functions, decorators, and module-level variables

### P1 Control Flow and Diagrams

* Extract control flow for `if`/`elif`/`else`
* Extract control flow for `while`, `for`, `try`/`except`/`finally`, and `with`
* Support Python `match`/`case` rendering, including guarded cases
* Render Nassi-Shneiderman HTML for a single file
* Render Nassi-Shneiderman HTML bundles for directories
* Show depth-coded nested conditionals up to 50 levels
* Support interactive collapsible function panels
* Show decorator badges in diagram headers

### P3 Exports and Analysis

* Export diagrams as HTML, Mermaid, SVG, and PNG when a rasterizer is available
* Export symbol graph and cross-reference data
* Run lightweight semantic passes for inferred return types, local bindings, and outbound calls
* Expose adapters for JSON, Cytoscape, and Graphviz DOT
* Support content-addressed parse caching

## Partial

These areas are present, but not fully aligned with what the vendored ANTLR grammar could theoretically support.

* `match`/`case` works in product behavior, but currently relies on AST fallback when the generated ANTLR parser hits Python-target compatibility gaps in pattern matching actions.
* `try` captures `except` and `finally`, but `try ... else` is not modeled explicitly yet.
* `for ... else` and `while ... else` are accepted by the grammar, but not yet represented as distinct control-flow branches.
* `except ... as exc` aliases are not surfaced as first-class data in the control-flow model.
* Annotated assignments such as `x: int = 1` are analyzed semantically, but are not yet promoted into the structural parse report the same way plain module assignments are.

## Next

### Near-term

* Model loop `else` branches and `try ... else` in the control-flow domain
* Improve exception clause extraction so `except ValueError as exc` is preserved accurately
* Promote annotated module assignments into the structural parse contract
* Remove the remaining ANTLR/Python target gap for pattern matching, so `match` no longer depends on AST fallback

### Later

* Stronger cross-file symbol resolution and name binding
* Richer type inference beyond literals, annotations, and simple call heuristics
* Persistent repository-scale indexing
* Closer visual parity between HTML and exported SVG/PNG
