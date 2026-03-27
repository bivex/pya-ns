"""Use cases for semantic and cross-reference exports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
        analysis = self.analyzer.analyze(source_unit)
        payload = _analysis_to_dict(analysis)
        return SemanticAnalysisDocumentDTO(
            source_location=analysis.source_location,
            symbol_count=len(analysis.symbols),
            reference_count=len(analysis.references),
            function_count=len(analysis.functions),
            payload=payload,
        )

    def analyze_directory(self, command: AnalyzeDirectoryCommand) -> SemanticAnalysisBundleDTO:
        source_units = tuple(self.source_repository.list_python_sources(command.root_path))
        analyses = tuple(self.analyzer.analyze(source_unit) for source_unit in source_units)
        return SemanticAnalysisBundleDTO(
            root_path=str(Path(command.root_path).expanduser().resolve()),
            document_count=len(analyses),
            payload={
                "root_path": str(Path(command.root_path).expanduser().resolve()),
                "document_count": len(analyses),
                "documents": [_analysis_to_dict(analysis) for analysis in analyses],
            },
        )


def _analysis_to_dict(analysis: SemanticAnalysis) -> dict[str, object]:
    return {
        "source_location": analysis.source_location,
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
