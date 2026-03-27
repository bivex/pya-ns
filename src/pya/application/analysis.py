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
        documents = _propagate_bundle_return_types(documents, resolved_root_path)
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
        "module_exports": list(analysis.module_exports),
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


def _resolve_return_type_part(
    *,
    part: str,
    import_targets_by_name: dict[str, str],
    local_function_symbols: dict[str, str],
    module_symbol_index: dict[str, dict[str, dict[str, object]]],
    symbol_by_name: dict[str, list[dict[str, object]]],
    symbol_by_qualified_name: dict[str, list[dict[str, object]]],
    symbol_by_id: dict[str, dict[str, object]],
    import_target_by_symbol_id: dict[str, str],
    function_payload_by_symbol_id: dict[str, dict[str, object]],
) -> str | None:
    if not part or any(token in part for token in ("[", "]", "{", "}", "(", ")", " ")):
        return None
    if part in {"None", "bool", "int", "float", "str", "list", "dict", "set", "tuple", "Path"}:
        return None

    target_symbol_id = local_function_symbols.get(part)
    imported_target_id = _expand_import_target(part, import_targets_by_name)
    if target_symbol_id is None and imported_target_id:
        resolved = _resolve_symbol_target(
            imported_target_id,
            module_symbol_index=module_symbol_index,
            symbol_by_name=symbol_by_name,
            symbol_by_qualified_name=symbol_by_qualified_name,
            symbol_by_id=symbol_by_id,
            import_target_by_symbol_id=import_target_by_symbol_id,
        )
        target_symbol_id = str(resolved["symbol_id"]) if resolved is not None else None

    if target_symbol_id is None:
        return None

    target_function = function_payload_by_symbol_id.get(target_symbol_id)
    target_type = (
        str(target_function["inferred_return_type"])
        if target_function and target_function.get("inferred_return_type")
        else None
    )
    if not target_type or target_type == part:
        return None
    return target_type


def _merge_type_parts(parts: list[str]) -> str:
    ordered: list[str] = []
    for part in parts:
        normalized = part.strip()
        if not normalized or normalized in ordered:
            continue
        ordered.append(normalized)
    if not ordered:
        return ""
    if len(ordered) == 1:
        return ordered[0]
    return " | ".join(ordered)


def _expand_import_target(name: str, import_targets_by_name: dict[str, str]) -> str:
    direct_target = import_targets_by_name.get(name, "")
    if direct_target:
        return direct_target

    segments = name.split(".")
    for index in range(len(segments) - 1, 0, -1):
        prefix = ".".join(segments[:index])
        suffix = ".".join(segments[index:])
        target = import_targets_by_name.get(prefix, "")
        if target:
            return f"{target}.{suffix}" if suffix else target
    return ""


def _propagate_bundle_return_types(
    documents: list[dict[str, object]],
    root_path: str,
) -> list[dict[str, object]]:
    symbol_by_name: dict[str, list[dict[str, object]]] = {}
    symbol_by_qualified_name: dict[str, list[dict[str, object]]] = {}
    symbol_by_id: dict[str, dict[str, object]] = {}
    module_symbol_index: dict[str, dict[str, dict[str, object]]] = {}
    import_target_by_symbol_id: dict[str, str] = {}
    function_payload_by_symbol_id: dict[str, dict[str, object]] = {}

    for document in documents:
        source_location = str(document["source_location"])
        module_name = _module_name_from_location(source_location, root_path)
        module_symbols: dict[str, dict[str, object]] = {}

        for symbol in document["symbols"]:
            symbol_id = str(symbol["symbol_id"])
            symbol_by_id[symbol_id] = symbol
            symbol_by_name.setdefault(str(symbol["name"]), []).append(symbol)
            module_symbols[str(symbol["name"])] = symbol
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
        module_symbol_index[module_name] = module_symbols

        for reference in document["references"]:
            if str(reference["relationship"]) == "imports":
                import_target_by_symbol_id[str(reference["source_id"])] = _normalize_target_id(
                    str(reference["target_id"]),
                    source_module=module_name,
                    source_location=source_location,
                )

        symbol_id_by_function_name: dict[str, str] = {}
        for symbol in document["symbols"]:
            if str(symbol["kind"]) not in {"function", "async_function"}:
                continue
            qualified_name = (
                f'{symbol["container"]}.{symbol["name"]}' if symbol["container"] else str(symbol["name"])
            )
            symbol_id_by_function_name[qualified_name] = str(symbol["symbol_id"])

        for function in document["functions"]:
            symbol_id = symbol_id_by_function_name.get(str(function["qualified_name"]))
            if symbol_id:
                function_payload_by_symbol_id[symbol_id] = function

    changed = True
    while changed:
        changed = False
        for document in documents:
            source_location = str(document["source_location"])
            source_module = _module_name_from_location(source_location, root_path)
            import_targets_by_name = {
                str(symbol["name"]): _normalize_target_id(
                    next(
                        (
                            str(reference["target_id"])
                            for reference in document["references"]
                            if str(reference["source_id"]) == str(symbol["symbol_id"])
                            and str(reference["relationship"]) == "imports"
                        ),
                        "",
                    ),
                    source_module=source_module,
                    source_location=source_location,
                )
                for symbol in document["symbols"]
                if str(symbol["kind"]) == "import"
            }
            local_function_symbols = {
                (
                    f'{symbol["container"]}.{symbol["name"]}'
                    if symbol["container"]
                    else str(symbol["name"])
                ): str(symbol["symbol_id"])
                for symbol in document["symbols"]
                if str(symbol["kind"]) in {"function", "async_function"}
            }

            for function in document["functions"]:
                current_type = function.get("inferred_return_type")
                if not isinstance(current_type, str) or not current_type.strip():
                    binding_changed = False
                else:
                    merged, binding_changed = _resolve_inferred_type(
                        current_type,
                        import_targets_by_name=import_targets_by_name,
                        local_function_symbols=local_function_symbols,
                        module_symbol_index=module_symbol_index,
                        symbol_by_name=symbol_by_name,
                        symbol_by_qualified_name=symbol_by_qualified_name,
                        symbol_by_id=symbol_by_id,
                        import_target_by_symbol_id=import_target_by_symbol_id,
                        function_payload_by_symbol_id=function_payload_by_symbol_id,
                    )
                    if binding_changed and merged != current_type:
                        function["inferred_return_type"] = merged
                        changed = True

                for binding in function.get("local_bindings", []):
                    inferred_type = binding.get("inferred_type")
                    if not isinstance(inferred_type, str) or not inferred_type.strip():
                        continue
                    merged, binding_changed = _resolve_inferred_type(
                        inferred_type,
                        import_targets_by_name=import_targets_by_name,
                        local_function_symbols=local_function_symbols,
                        module_symbol_index=module_symbol_index,
                        symbol_by_name=symbol_by_name,
                        symbol_by_qualified_name=symbol_by_qualified_name,
                        symbol_by_id=symbol_by_id,
                        import_target_by_symbol_id=import_target_by_symbol_id,
                        function_payload_by_symbol_id=function_payload_by_symbol_id,
                    )
                    if binding_changed and merged != inferred_type:
                        binding["inferred_type"] = merged
                        changed = True
    return documents


def _resolve_inferred_type(
    current_type: str,
    *,
    import_targets_by_name: dict[str, str],
    local_function_symbols: dict[str, str],
    module_symbol_index: dict[str, dict[str, dict[str, object]]],
    symbol_by_name: dict[str, list[dict[str, object]]],
    symbol_by_qualified_name: dict[str, list[dict[str, object]]],
    symbol_by_id: dict[str, dict[str, object]],
    import_target_by_symbol_id: dict[str, str],
    function_payload_by_symbol_id: dict[str, dict[str, object]],
) -> tuple[str, bool]:
    parts = [part.strip() for part in current_type.split("|")]
    updated_parts: list[str] = []
    changed = False
    for part in parts:
        replacement = _resolve_return_type_part(
            part=part,
            import_targets_by_name=import_targets_by_name,
            local_function_symbols=local_function_symbols,
            module_symbol_index=module_symbol_index,
            symbol_by_name=symbol_by_name,
            symbol_by_qualified_name=symbol_by_qualified_name,
            symbol_by_id=symbol_by_id,
            import_target_by_symbol_id=import_target_by_symbol_id,
            function_payload_by_symbol_id=function_payload_by_symbol_id,
        )
        updated_parts.append(replacement or part)
        changed = changed or replacement is not None
    return _merge_type_parts(updated_parts), changed


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
    module_exports_index: dict[str, set[str]] = {}

    for document in export_docs:
        module_name = _module_name_from_location(str(document["source_location"]), root_path)
        current_module_symbols: dict[str, dict[str, object]] = {}
        module_paths[module_name] = str(document["source_location"])
        module_exports_index[module_name] = {str(name) for name in document.get("module_exports", [])}
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
                import_target_by_symbol_id[str(reference["source_id"])] = _normalize_target_id(
                    str(reference["target_id"]),
                    source_module=module_name,
                    source_location=str(document["source_location"]),
                )

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
        wildcard_import_targets = [
            _normalize_target_id(
                str(reference["target_id"]),
                source_module=source_module,
                source_location=source_location,
            )
            for reference in document["references"]
            if str(reference["relationship"]) == "imports"
            and any(
                str(symbol["symbol_id"]) == str(reference["source_id"]) and str(symbol["name"]) == "*"
                for symbol in document_symbols
            )
        ]
        wildcard_import_targets = [target[:-2] for target in wildcard_import_targets if target.endswith(".*")]

        for reference in document["references"]:
            target_id = _normalize_target_id(
                str(reference["target_id"]),
                source_module=source_module,
                source_location=source_location,
            )
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
                        _normalize_target_id(
                            imported_target,
                            source_module=source_module,
                            source_location=source_location,
                        ),
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

                expanded_import_target = _expand_import_target(call, local_import_targets)
                if expanded_import_target:
                    qualified_target = _normalize_target_id(
                        expanded_import_target,
                        source_module=source_module,
                        source_location=source_location,
                    )
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

                wildcard_resolved = _resolve_from_wildcard_imports(
                    call,
                    wildcard_modules=wildcard_import_targets,
                    module_exports_index=module_exports_index,
                    module_symbol_index=module_symbol_index,
                    symbol_by_name=symbol_by_name,
                    symbol_by_qualified_name=symbol_by_qualified_name,
                    symbol_by_id=symbol_by_id,
                    import_target_by_symbol_id=import_target_by_symbol_id,
                )
                if wildcard_resolved is not None:
                    bundle_refs.append(
                        {
                            "source_id": source_id,
                            "target_id": wildcard_resolved["symbol_id"],
                            "relationship": "calls_import_star",
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

                if wildcard_import_targets and "." not in call:
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


def _resolve_from_wildcard_imports(
    symbol_name: str,
    *,
    wildcard_modules: list[str],
    module_exports_index: dict[str, set[str]],
    module_symbol_index: dict[str, dict[str, dict[str, object]]],
    symbol_by_name: dict[str, list[dict[str, object]]],
    symbol_by_qualified_name: dict[str, list[dict[str, object]]],
    symbol_by_id: dict[str, dict[str, object]],
    import_target_by_symbol_id: dict[str, str],
) -> dict[str, object] | None:
    candidates: list[dict[str, object]] = []
    for module_name in wildcard_modules:
        allowed_exports = module_exports_index.get(module_name, set())
        if allowed_exports and symbol_name not in allowed_exports:
            continue
        resolved = _resolve_symbol_target(
            f"{module_name}.{symbol_name}",
            module_symbol_index=module_symbol_index,
            symbol_by_name=symbol_by_name,
            symbol_by_qualified_name=symbol_by_qualified_name,
            symbol_by_id=symbol_by_id,
            import_target_by_symbol_id=import_target_by_symbol_id,
        )
        if resolved is not None:
            candidates.append(resolved)
    deduped = {str(candidate["symbol_id"]): candidate for candidate in candidates}
    if len(deduped) == 1:
        return next(iter(deduped.values()))
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


def _normalize_target_id(target_id: str, *, source_module: str, source_location: str) -> str:
    if not target_id.startswith("."):
        return target_id
    dot_count = len(target_id) - len(target_id.lstrip("."))
    remainder = target_id[dot_count:]
    package_parts = source_module.split(".") if source_module else []
    if not source_location.endswith("__init__.py") and package_parts:
        package_parts = package_parts[:-1]
    pops = max(dot_count - 1, 0)
    if pops:
        package_parts = package_parts[:-pops] if pops <= len(package_parts) else []
    base = ".".join(part for part in package_parts if part)
    if remainder:
        return f"{base}.{remainder}" if base else remainder
    return base
