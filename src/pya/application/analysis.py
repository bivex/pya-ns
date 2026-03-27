"""Use cases for semantic and cross-reference exports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pya.domain.analysis import SemanticAnalysis
from pya.domain.ports import PythonSemanticAnalyzer, SourceRepository


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

    def analyze_file(self, command: AnalyzeFileCommand) -> SemanticAnalysisDocumentDTO:
        source_unit = self.source_repository.load_file(command.path)
        try:
            analysis = self.analyzer.analyze(source_unit)
            payload = _analysis_to_dict(analysis)
        except SyntaxError as error:
            payload = _syntax_error_document(source_unit, error)
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
            try:
                analysis = self.analyzer.analyze(source_unit)
            except SyntaxError as error:
                failure_count += 1
                documents.append(_syntax_error_document(source_unit, error))
                continue

            successful_analyses.append(analysis)
            documents.append(_analysis_to_dict(analysis))

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


def _analysis_to_dict(analysis: SemanticAnalysis) -> dict[str, object]:
    return {
        "source_location": analysis.source_location,
        "status": "succeeded",
        "diagnostics": [],
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


def _syntax_error_document(source_unit, error: SyntaxError) -> dict[str, object]:
    message = str(error)
    line = getattr(error, "lineno", 0) or 0
    column = getattr(error, "offset", 0) or 0
    diagnostic = {
        "severity": "error",
        "message": message,
        "line": line,
        "column": column,
    }
    return {
        "source_location": source_unit.location,
        "status": "failed",
        "diagnostics": [diagnostic],
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


def _resolve_bundle_references(
    analyses: list[SemanticAnalysis],
    root_path: str,
) -> list[dict[str, Any]]:
    bundle_refs: list[dict[str, Any]] = []
    export_docs = [_analysis_to_dict(analysis) for analysis in analyses]
    symbol_by_name: dict[str, list[dict[str, object]]] = {}
    symbol_by_qualified_name: dict[str, list[dict[str, object]]] = {}
    module_symbol_index: dict[str, dict[str, dict[str, object]]] = {}
    module_paths: dict[str, str] = {}

    for document in export_docs:
        module_name = _module_name_from_location(str(document["source_location"]), root_path)
        current_module_symbols: dict[str, dict[str, object]] = {}
        module_paths[module_name] = str(document["source_location"])
        for symbol in document["symbols"]:
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

    for document in export_docs:
        source_location = str(document["source_location"])
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
                module_name, imported_name = target_id.rsplit(".", 1)
                resolved_target = module_symbol_index.get(module_name, {}).get(imported_name)
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
                imported_target = local_import_targets.get(call)
                if imported_target:
                    imported_candidates = symbol_by_qualified_name.get(imported_target, [])
                    if len(imported_candidates) == 1:
                        bundle_refs.append(
                            {
                                "source_id": source_id,
                                "target_id": imported_candidates[0]["symbol_id"],
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
                        imported_candidates = symbol_by_qualified_name.get(qualified_target, [])
                        if len(imported_candidates) == 1:
                            bundle_refs.append(
                                {
                                    "source_id": source_id,
                                    "target_id": imported_candidates[0]["symbol_id"],
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


def _module_name_from_location(source_location: str, root_path: str) -> str:
    relative = Path(source_location).resolve().relative_to(Path(root_path).resolve())
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)
