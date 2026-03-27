"""Persistent content-addressed parser cache."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pya.domain.model import (
    DiagnosticSeverity,
    GrammarVersion,
    ParseOutcome,
    ParseStatistics,
    ParseStatus,
    SourceUnit,
    SourceUnitId,
    StructuralElement,
    StructuralElementKind,
    SyntaxDiagnostic,
)
from pya.domain.ports import PythonSyntaxParser


CACHE_FORMAT_VERSION = "parser-cache-v2"


class CachedPythonSyntaxParser(PythonSyntaxParser):
    def __init__(self, inner: PythonSyntaxParser, cache_dir: str | Path) -> None:
        self._inner = inner
        self._cache_dir = Path(cache_dir).expanduser().resolve()

    @property
    def grammar_version(self) -> GrammarVersion:
        return self._inner.grammar_version

    def parse(self, source_unit: SourceUnit) -> ParseOutcome:
        cache_path = self._cache_path(source_unit)
        if cache_path.exists():
            return _parse_outcome_from_dict(json.loads(cache_path.read_text(encoding="utf-8")))

        outcome = self._inner.parse(source_unit)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(_parse_outcome_to_dict(outcome), indent=2), encoding="utf-8")
        return outcome

    def _cache_path(self, source_unit: SourceUnit) -> Path:
        key = hashlib.sha256(
            (
                f"{CACHE_FORMAT_VERSION}\n"
                f"{source_unit.location}\n"
                f"{self.grammar_version.value}\n"
                f"{source_unit.content}"
            ).encode("utf-8")
        ).hexdigest()
        return self._cache_dir / f"{key}.json"


def _parse_outcome_to_dict(outcome: ParseOutcome) -> dict[str, object]:
    return {
        "source_unit_id": outcome.source_unit_id.value,
        "source_location": outcome.source_location,
        "grammar_version": outcome.grammar_version.value,
        "status": outcome.status.value,
        "diagnostics": [
            {
                "severity": diagnostic.severity.value,
                "message": diagnostic.message,
                "line": diagnostic.line,
                "column": diagnostic.column,
            }
            for diagnostic in outcome.diagnostics
        ],
        "structural_elements": [
            {
                "kind": element.kind.value,
                "name": element.name,
                "line": element.line,
                "column": element.column,
                "container": element.container,
                "signature": element.signature,
            }
            for element in outcome.structural_elements
        ],
        "statistics": {
            "token_count": outcome.statistics.token_count,
            "structural_element_count": outcome.statistics.structural_element_count,
            "diagnostic_count": outcome.statistics.diagnostic_count,
            "elapsed_ms": outcome.statistics.elapsed_ms,
        },
        "failure_message": outcome.failure_message,
    }


def _parse_outcome_from_dict(payload: dict[str, object]) -> ParseOutcome:
    statistics = payload["statistics"]
    return ParseOutcome(
        source_unit_id=SourceUnitId(payload["source_unit_id"]),
        source_location=payload["source_location"],
        grammar_version=GrammarVersion(payload["grammar_version"]),
        status=ParseStatus(payload["status"]),
        diagnostics=tuple(
            SyntaxDiagnostic(
                severity=DiagnosticSeverity(item["severity"]),
                message=item["message"],
                line=item["line"],
                column=item["column"],
            )
            for item in payload["diagnostics"]
        ),
        structural_elements=tuple(
            StructuralElement(
                kind=StructuralElementKind(item["kind"]),
                name=item["name"],
                line=item["line"],
                column=item["column"],
                container=item["container"],
                signature=item["signature"],
            )
            for item in payload["structural_elements"]
        ),
        statistics=ParseStatistics(
            token_count=statistics["token_count"],
            structural_element_count=statistics["structural_element_count"],
            diagnostic_count=statistics["diagnostic_count"],
            elapsed_ms=statistics["elapsed_ms"],
        ),
        failure_message=payload["failure_message"],
    )
