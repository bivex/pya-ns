# Roadmap

This roadmap reflects the actual state of the Python implementation in this repository.

## Status Key

* `✅` ready and shipped
* `🟡` partially shipped or heuristic
* `🚧` planned / not fully ready yet

## Ready

### P0 Foundation

* `✅` Parse one Python file
* `✅` Parse a directory of Python files
* `✅` Ignore non-`.py` files during recursive discovery
* `✅` Return versioned JSON parse reports
* `✅` Capture syntax diagnostics with line and column metadata
* `✅` Aggregate file results into a parsing job report
* `✅` Expose grammar version and report schema version
* `✅` Distinguish success, success-with-diagnostics, and technical failure
* `✅` Extract structural elements for imports, classes, functions, async functions, decorators, and module-level variables

### P1 Control Flow and Diagrams

* `✅` Extract control flow for `if`/`elif`/`else`
* `✅` Extract control flow for `while`, `for`, `try`/`except`/`finally`, and `with`
* `✅` Support Python `match`/`case` rendering, including guarded cases
* `✅` Render Nassi-Shneiderman HTML for a single file
* `✅` Render Nassi-Shneiderman HTML bundles for directories
* `✅` Show depth-coded nested conditionals up to 50 levels
* `✅` Support interactive collapsible function panels
* `✅` Show decorator badges in diagram headers

### P3 Exports and Analysis

* `✅` Export diagrams as HTML, Mermaid, SVG, and PNG when a rasterizer is available
* `✅` Export symbol graph and cross-reference data
* `✅` Run lightweight semantic passes for inferred return types, return annotations, local call-chain propagation, local bindings, and outbound calls
* `✅` Surface parser diagnostics and parse metadata in semantic analysis exports
* `✅` Resolve bundle-level local calls, direct imports, alias imports, relative imports, `star imports`, `__all__`-guarded wildcard imports, and package re-exports for straightforward project layouts
* `✅` Expose adapters for JSON, Cytoscape, and Graphviz DOT
* `✅` Support content-addressed parse caching

## Partial

These areas are present, but not fully aligned with what the vendored ANTLR grammar could theoretically support.

* `🟡` `match`/`case` is now stable on the generated ANTLR path for the project fixtures and current example tour, including complex pattern shapes, but control-flow extraction still intentionally falls back to AST when ANTLR reports noisy diagnostics on harder files.
* `🟡` Cross-file resolution now covers local calls, straightforward imports, alias imports, relative imports, dotted module-chain calls such as `pkg.tooling.func()`, package-relative re-export chains such as `from pkg import subpkg` -> `subpkg.run()`, `star imports`, `__all__`-guarded wildcard imports, and package re-exports, but it is still heuristic rather than a full binder.
* `🟡` Type inference now covers literals, annotations, local bindings, local call-chain propagation, imported call-chain propagation in `analyze-dir`, and simple call-based guesses, but it is still far from full static analysis.

## Not Ready Yet

### Near-term

* `🚧` Strengthen cross-file resolution for broader package graphs and more import edge cases
* `🚧` Add richer parser recovery context to semantic exports when ANTLR and AST disagree

### Later

* `🚧` Richer type inference beyond literals, annotations, and simple call heuristics
* `🚧` Persistent repository-scale indexing
* `🚧` Closer visual parity between HTML and exported SVG/PNG
