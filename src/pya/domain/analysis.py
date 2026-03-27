"""Domain types for symbol and semantic analysis."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SymbolNode:
    symbol_id: str
    name: str
    kind: str
    location: str
    line: int
    column: int
    container: str | None = None
    signature: str | None = None


@dataclass(frozen=True, slots=True)
class SymbolReference:
    source_id: str
    target_id: str
    relationship: str
    location: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class InferredBinding:
    name: str
    inferred_type: str
    confidence: float


@dataclass(frozen=True, slots=True)
class SemanticFunction:
    qualified_name: str
    location: str
    line: int
    inferred_return_type: str | None
    local_bindings: tuple[InferredBinding, ...]
    outbound_calls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SemanticAnalysis:
    source_location: str
    symbols: tuple[SymbolNode, ...]
    references: tuple[SymbolReference, ...]
    functions: tuple[SemanticFunction, ...]

