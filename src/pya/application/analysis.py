"""Use cases for semantic and cross-reference exports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pya.domain.analysis import SemanticAnalysis
from pya.domain.model import ParseOutcome, SyntaxDiagnostic
from pya.domain.ports import PythonSemanticAnalyzer, PythonSyntaxParser, SourceRepository


@dataclass(frozen=True, slots=True)
class AnalyzeFileCommand:
    path: str


@dataclass(frozen=True, slots=True)
class AnalyzeDirectoryCommand:
    root_path: str


@dataclass(frozen=True, slots=True)
class SemanticAnalysisDocumentDTO:
    source_location: str
    symbol_count: int
    reference_count: int
    function_count: int
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class SemanticAnalysisBundleDTO:
    root_path: str
    document_count: int
    payload: dict[str, object]


@dataclass(slots=True)
class SemanticAnalysisService:
    source_repository: SourceRepository
    analyzer: PythonSemanticAnalyzer
    parser: PythonSyntaxParser | None = None

    def analyze_file(self, command: AnalyzeFileCommand) -> SemanticAnalysisDocumentDTO:
        source_unit = self.source_repository.load_file(command.path)
        parse_outcome = self.parser.parse(source_unit) if self.parser is not None else None
        try:
            analysis = self.analyzer.analyze(source_unit)
            payload = _analysis_to_dict(analysis, parse_outcome)
        except SyntaxError as error:
            payload = _syntax_error_document(source_unit, error, parse_outcome)
        return SemanticAnalysisDocumentDTO(
            source_location=str(payload["source_location"]),
            symbol_count=len(payload["symbols"]),
            reference_count=len(payload["references"]),
            function_count=len(payload["functions"]),
            payload=payload,
        )

    def analyze_directory(self, command: AnalyzeDirectoryCommand) -> SemanticAnalysisBundleDTO:
        source_units = tuple(self.source_repository.list_python_sources(command.root_path))
        documents: list[dict[str, object]] = []
        successful_analyses: list[SemanticAnalysis] = []
        failure_count = 0

        for source_unit in source_units:
            parse_outcome = self.parser.parse(source_unit) if self.parser is not None else None
            try:
                analysis = self.analyzer.analyze(source_unit)
            except SyntaxError as error:
                failure_count += 1
                documents.append(_syntax_error_document(source_unit, error, parse_outcome))
                continue

            successful_analyses.append(analysis)
            documents.append(_analysis_to_dict(analysis, parse_outcome))

        resolved_root_path = str(Path(command.root_path).expanduser().resolve())
        bundle_references = _resolve_bundle_references(successful_analyses, resolved_root_path)
        return SemanticAnalysisBundleDTO(
            root_path=resolved_root_path,
            document_count=len(documents),
            payload={
                "root_path": resolved_root_path,
                "document_count": len(documents),
                "success_count": len(successful_analyses),
                "failure_count": failure_count,
                "documents": documents,
                "bundle_references": bundle_references,
            },
        )


def _analysis_to_dict(
    analysis: SemanticAnalysis,
    parse_outcome: ParseOutcome | None = None,
) -> dict[str, object]:
    return {
        "source_location": analysis.source_location,
        "status": (
            parse_outcome.status.value
            if parse_outcome is not None and parse_outcome.diagnostics
            else "succeeded"
        ),
        "parse_status": parse_outcome.status.value if parse_outcome is not None else None,
        "grammar_version": (
            parse_outcome.grammar_version.value if parse_outcome is not None else None
        ),
        "diagnostics": (
            [_diagnostic_to_dict(diagnostic) for diagnostic in parse_outcome.diagnostics]
            if parse_outcome is not None
            else []
        ),
        "parse_statistics": (
            {
                "token_count": parse_outcome.statistics.token_count,
                "structural_element_count": parse_outcome.statistics.structural_element_count,
                "diagnostic_count": parse_outcome.statistics.diagnostic_count,
                "elapsed_ms": parse_outcome.statistics.elapsed_ms,
            }
            if parse_outcome is not None
            else None
        ),
        "symbols": [
            {
                "symbol_id": symbol.symbol_id,
                "name": symbol.name,
                "kind": symbol.kind,
                "location": symbol.location,
                "line": symbol.line,
                "column": symbol.column,
                "container": symbol.container,
                "signature": symbol.signature,
            }
            for symbol in analysis.symbols
        ],
        "references": [
            {
                "source_id": reference.source_id,
                "target_id": reference.target_id,
                "relationship": reference.relationship,
                "location": reference.location,
                "line": reference.line,
                "column": reference.column,
            }
            for reference in analysis.references
        ],
        "functions": [
            {
                "qualified_name": function.qualified_name,
                "location": function.location,
                "line": function.line,
                "inferred_return_type": function.inferred_return_type,
                "local_bindings": [
                    {
                        "name": binding.name,
                        "inferred_type": binding.inferred_type,
                        "confidence": binding.confidence,
                    }
                    for binding in function.local_bindings
                ],
                "outbound_calls": list(function.outbound_calls),
            }
            for function in analysis.functions
        ],
    }


def _syntax_error_document(
    source_unit,
    error: SyntaxError,
    parse_outcome: ParseOutcome | None = None,
) -> dict[str, object]:
    message = str(error)
    line = getattr(error, "lineno", 0) or 0
    column = getattr(error, "offset", 0) or 0
    diagnostics = list(
        _diagnostic_to_dict(diagnostic) for diagnostic in (parse_outcome.diagnostics if parse_outcome else ())
    )
    syntax_error_diagnostic = {
        "severity": "error",
        "message": message,
        "line": line,
        "column": column,
    }
    if not any(
        existing["message"] == message and existing["line"] == line and existing["column"] == column
        for existing in diagnostics
    ):
        diagnostics.append(syntax_error_diagnostic)
    return {
        "source_location": source_unit.location,
        "status": "failed",
        "parse_status": parse_outcome.status.value if parse_outcome is not None else None,
        "grammar_version": (
            parse_outcome.grammar_version.value if parse_outcome is not None else None
        ),
        "diagnostics": diagnostics,
        "parse_statistics": (
            {
                "token_count": parse_outcome.statistics.token_count,
                "structural_element_count": parse_outcome.statistics.structural_element_count,
                "diagnostic_count": parse_outcome.statistics.diagnostic_count,
                "elapsed_ms": parse_outcome.statistics.elapsed_ms,
            }
            if parse_outcome is not None
            else None
        ),
        "symbols": [],
        "references": [],
        "functions": [],
        "error": {
            "kind": "syntax_error",
            "message": message,
            "line": line,
            "column": column,
        },
    }


def _diagnostic_to_dict(diagnostic: SyntaxDiagnostic) -> dict[str, object]:
    return {
        "severity": diagnostic.severity.value,
        "message": diagnostic.message,
        "line": diagnostic.line,
        "column": diagnostic.column,
    }


def _resolve_bundle_references(
    analyses: list[SemanticAnalysis],
    root_path: str,
) -> list[dict[str, Any]]:
    bundle_refs: list[dict[str, Any]] = []
    export_docs = [_analysis_to_dict(analysis) for analysis in analyses]
    symbol_by_name: dict[str, list[dict[str, object]]] = {}
    symbol_by_qualified_name: dict[str, list[dict[str, object]]] = {}
    symbol_by_id: dict[str, dict[str, object]] = {}
    module_symbol_index: dict[str, dict[str, dict[str, object]]] = {}
    module_paths: dict[str, str] = {}
    import_target_by_symbol_id: dict[str, str] = {}

    for document in export_docs:
        module_name = _module_name_from_location(str(document["source_location"]), root_path)
        current_module_symbols: dict[str, dict[str, object]] = {}
        module_paths[module_name] = str(document["source_location"])
        for symbol in document["symbols"]:
            symbol_by_id[str(symbol["symbol_id"])] = symbol
            symbol_by_name.setdefault(str(symbol["name"]), []).append(symbol)
            current_module_symbols[str(symbol["name"])] = symbol
            symbol_by_qualified_name.setdefault(
                f'{module_name}.{symbol["name"]}',
                [],
            ).append(symbol)
            if symbol["container"]:
                qualified_name = f'{symbol["container"]}.{symbol["name"]}'
                symbol_by_name.setdefault(qualified_name, []).append(symbol)
                symbol_by_qualified_name.setdefault(
                    f"{module_name}.{qualified_name}",
                    [],
                ).append(symbol)
        module_symbol_index[module_name] = current_module_symbols
        for reference in document["references"]:
            if str(reference["relationship"]) == "imports":
                import_target_by_symbol_id[str(reference["source_id"])] = str(reference["target_id"])

    for document in export_docs:
        source_location = str(document["source_location"])
        source_module = _module_name_from_location(source_location, root_path)
        document_symbols = list(document["symbols"])
        local_symbols_by_simple_name: dict[str, list[dict[str, object]]] = {}
        local_symbols_by_qualified_name: dict[str, dict[str, object]] = {}
        for symbol in document_symbols:
            local_symbols_by_simple_name.setdefault(str(symbol["name"]), []).append(symbol)
            qualified_name = (
                f'{symbol["container"]}.{symbol["name"]}' if symbol["container"] else str(symbol["name"])
            )
            local_symbols_by_qualified_name[qualified_name] = symbol
        local_import_targets = {
            str(symbol["name"]): next(
                (
                    str(reference["target_id"])
                    for reference in document["references"]
                    if reference["source_id"] == symbol["symbol_id"]
                ),
                "",
            )
            for symbol in document["symbols"]
            if symbol["kind"] == "import"
        }

        for reference in document["references"]:
            target_id = str(reference["target_id"])
            resolved_target = None
            relationship = "resolves_to"

            if "." in target_id:
                resolved_target = _resolve_symbol_target(
                    target_id,
                    module_symbol_index=module_symbol_index,
                    symbol_by_name=symbol_by_name,
                    symbol_by_qualified_name=symbol_by_qualified_name,
                    symbol_by_id=symbol_by_id,
                    import_target_by_symbol_id=import_target_by_symbol_id,
                )
                if resolved_target is not None:
                    relationship = "imports_local"
            elif target_id in module_paths:
                relationship = "imports_module_local"
            if resolved_target is None:
                candidates = symbol_by_name.get(target_id, [])
                if len(candidates) == 1:
                    resolved_target = candidates[0]

            if resolved_target is not None:
                bundle_refs.append(
                    {
                        "source_id": reference["source_id"],
                        "target_id": resolved_target["symbol_id"],
                        "relationship": relationship,
                        "location": source_location,
                        "line": reference["line"],
                        "column": reference["column"],
                    }
                )

        for function in document["functions"]:
            source_id = None
            for symbol in document["symbols"]:
                qualified_name = (
                    f'{symbol["container"]}.{symbol["name"]}' if symbol["container"] else symbol["name"]
                )
                if qualified_name == function["qualified_name"]:
                    source_id = symbol["symbol_id"]
                    break
            if source_id is None:
                continue

            for call in function["outbound_calls"]:
                local_target = local_symbols_by_qualified_name.get(call)
                if local_target is None:
                    local_candidates = local_symbols_by_simple_name.get(call, [])
                    if len(local_candidates) == 1:
                        local_target = local_candidates[0]
                if local_target is not None and local_target["kind"] in {"function", "async_function"}:
                    bundle_refs.append(
                        {
                            "source_id": source_id,
                            "target_id": local_target["symbol_id"],
                            "relationship": "calls_local",
                            "location": source_location,
                            "line": function["line"],
                            "column": 0,
                        }
                    )
                    continue

                imported_target = local_import_targets.get(call)
                if imported_target:
                    resolved_import = _resolve_symbol_target(
                        imported_target,
                        module_symbol_index=module_symbol_index,
                        symbol_by_name=symbol_by_name,
                        symbol_by_qualified_name=symbol_by_qualified_name,
                        symbol_by_id=symbol_by_id,
                        import_target_by_symbol_id=import_target_by_symbol_id,
                    )
                    if resolved_import is not None:
                        bundle_refs.append(
                            {
                                "source_id": source_id,
                                "target_id": resolved_import["symbol_id"],
                                "relationship": "calls_import",
                                "location": source_location,
                                "line": function["line"],
                                "column": 0,
                            }
                        )
                        continue

                if "." in call:
                    import_alias, _, member_name = call.partition(".")
                    alias_target = local_import_targets.get(import_alias)
                    if alias_target:
                        qualified_target = f"{alias_target}.{member_name}"
                        resolved_import = _resolve_symbol_target(
                            qualified_target,
                            module_symbol_index=module_symbol_index,
                            symbol_by_name=symbol_by_name,
                            symbol_by_qualified_name=symbol_by_qualified_name,
                            symbol_by_id=symbol_by_id,
                            import_target_by_symbol_id=import_target_by_symbol_id,
                        )
                        if resolved_import is not None:
                            bundle_refs.append(
                                {
                                    "source_id": source_id,
                                    "target_id": resolved_import["symbol_id"],
                                    "relationship": "calls_import",
                                    "location": source_location,
                                    "line": function["line"],
                                    "column": 0,
                                }
                            )
                            continue

                imported_source = local_import_targets.get(call)
                if imported_source:
                    bundle_refs.append(
                        {
                            "source_id": source_id,
                            "target_id": imported_source,
                            "relationship": "calls_import",
                            "location": source_location,
                            "line": function["line"],
                            "column": 0,
                        }
                    )
                    continue

                if "." in call and call.startswith(f"{source_module}."):
                    resolved_local = _resolve_symbol_target(
                        call,
                        module_symbol_index=module_symbol_index,
                        symbol_by_name=symbol_by_name,
                        symbol_by_qualified_name=symbol_by_qualified_name,
                        symbol_by_id=symbol_by_id,
                        import_target_by_symbol_id=import_target_by_symbol_id,
                    )
                    if resolved_local is not None:
                        bundle_refs.append(
                            {
                                "source_id": source_id,
                                "target_id": resolved_local["symbol_id"],
                                "relationship": "calls_local",
                                "location": source_location,
                                "line": function["line"],
                                "column": 0,
                            }
                        )
                        continue

                candidates = symbol_by_name.get(call, [])
                if len(candidates) == 1:
                    bundle_refs.append(
                        {
                            "source_id": source_id,
                            "target_id": candidates[0]["symbol_id"],
                            "relationship": "calls_resolved",
                            "location": source_location,
                            "line": function["line"],
                            "column": 0,
                        }
                    )

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, int, int]] = set()
    for reference in bundle_refs:
        key = (
            str(reference["source_id"]),
            str(reference["target_id"]),
            str(reference["relationship"]),
            str(reference["location"]),
            int(reference["line"]),
            int(reference["column"]),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(reference)
    return deduped


def _resolve_symbol_target(
    target_id: str,
    *,
    module_symbol_index: dict[str, dict[str, dict[str, object]]],
    symbol_by_name: dict[str, list[dict[str, object]]],
    symbol_by_qualified_name: dict[str, list[dict[str, object]]],
    symbol_by_id: dict[str, dict[str, object]],
    import_target_by_symbol_id: dict[str, str],
    _visited: set[str] | None = None,
) -> dict[str, object] | None:
    visited = _visited or set()
    if target_id in visited:
        return None
    visited.add(target_id)

    if "." in target_id:
        module_name, imported_name = target_id.rsplit(".", 1)
        symbol = module_symbol_index.get(module_name, {}).get(imported_name)
        if symbol is not None:
            resolved = _follow_reexport(
                symbol,
                module_symbol_index=module_symbol_index,
                symbol_by_name=symbol_by_name,
                symbol_by_qualified_name=symbol_by_qualified_name,
                symbol_by_id=symbol_by_id,
                import_target_by_symbol_id=import_target_by_symbol_id,
                visited=visited,
            )
            if resolved is not None:
                return resolved

    candidates = symbol_by_qualified_name.get(target_id, [])
    if len(candidates) == 1:
        resolved = _follow_reexport(
            candidates[0],
            module_symbol_index=module_symbol_index,
            symbol_by_name=symbol_by_name,
            symbol_by_qualified_name=symbol_by_qualified_name,
            symbol_by_id=symbol_by_id,
            import_target_by_symbol_id=import_target_by_symbol_id,
            visited=visited,
        )
        if resolved is not None:
            return resolved

    simple_candidates = symbol_by_name.get(target_id, [])
    if len(simple_candidates) == 1:
        return _follow_reexport(
            simple_candidates[0],
            module_symbol_index=module_symbol_index,
            symbol_by_name=symbol_by_name,
            symbol_by_qualified_name=symbol_by_qualified_name,
            symbol_by_id=symbol_by_id,
            import_target_by_symbol_id=import_target_by_symbol_id,
            visited=visited,
        )
    return None


def _follow_reexport(
    symbol: dict[str, object],
    *,
    module_symbol_index: dict[str, dict[str, dict[str, object]]],
    symbol_by_name: dict[str, list[dict[str, object]]],
    symbol_by_qualified_name: dict[str, list[dict[str, object]]],
    symbol_by_id: dict[str, dict[str, object]],
    import_target_by_symbol_id: dict[str, str],
    visited: set[str],
) -> dict[str, object] | None:
    if str(symbol["kind"]) != "import":
        return symbol
    next_target = import_target_by_symbol_id.get(str(symbol["symbol_id"]))
    if not next_target:
        return symbol_by_id.get(str(symbol["symbol_id"]))
    return _resolve_symbol_target(
        next_target,
        module_symbol_index=module_symbol_index,
        symbol_by_name=symbol_by_name,
        symbol_by_qualified_name=symbol_by_qualified_name,
        symbol_by_id=symbol_by_id,
        import_target_by_symbol_id=import_target_by_symbol_id,
        _visited=visited,
    )


def _module_name_from_location(source_location: str, root_path: str) -> str:
    relative = Path(source_location).resolve().relative_to(Path(root_path).resolve())
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)
