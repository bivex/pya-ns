"""AST-backed semantic and symbol analysis."""

from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass

from pya.domain.analysis import (
    InferredBinding,
    SemanticAnalysis,
    SemanticFunction,
    SymbolNode,
    SymbolReference,
)
from pya.domain.ports import PythonSemanticAnalyzer
from pya.domain.model import SourceUnit


@dataclass(frozen=True, slots=True)
class _FunctionFrame:
    qualified_name: str
    line: int


class AstPythonSemanticAnalyzer(PythonSemanticAnalyzer):
    def analyze(self, source_unit: SourceUnit) -> SemanticAnalysis:
        tree = ast.parse(source_unit.content, filename=source_unit.location)
        visitor = _SemanticVisitor(source_unit.location)
        visitor.visit(tree)
        return SemanticAnalysis(
            source_location=source_unit.location,
            symbols=tuple(visitor.symbols),
            references=tuple(visitor.references),
            functions=tuple(visitor.semantic_functions()),
        )


class _SemanticVisitor(ast.NodeVisitor):
    def __init__(self, location: str) -> None:
        self.location = location
        self.symbols: list[SymbolNode] = []
        self.references: list[SymbolReference] = []
        self._function_stack: list[_FunctionFrame] = []
        self._class_stack: list[str] = []
        self._bindings: dict[str, list[InferredBinding]] = defaultdict(list)
        self._returns: dict[str, list[str]] = defaultdict(list)
        self._calls: dict[str, list[str]] = defaultdict(list)
        self._symbol_ids: dict[str, str] = {}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname or alias.name
            symbol_id = self._make_symbol_id(None, name, "import")
            self._symbol_ids[f"import:{name}"] = symbol_id
            self.symbols.append(
                SymbolNode(
                    symbol_id=symbol_id,
                    name=name,
                    kind="import",
                    location=self.location,
                    line=node.lineno,
                    column=node.col_offset,
                    signature=(
                        f"import {alias.name} as {alias.asname}"
                        if alias.asname
                        else f"import {alias.name}"
                    ),
                )
            )
            self.references.append(
                SymbolReference(
                    source_id=symbol_id,
                    target_id=alias.name,
                    relationship="imports",
                    location=self.location,
                    line=node.lineno,
                    column=node.col_offset,
                )
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        module_prefix = "." * node.level
        for alias in node.names:
            name = alias.asname or alias.name
            qualified_module = f"{module_prefix}{module}" if module else module_prefix
            qualified = f"{qualified_module}.{alias.name}" if qualified_module else alias.name
            symbol_id = self._make_symbol_id(None, name, "import")
            self._symbol_ids[f"import:{name}"] = symbol_id
            self.symbols.append(
                SymbolNode(
                    symbol_id=symbol_id,
                    name=name,
                    kind="import",
                    location=self.location,
                    line=node.lineno,
                    column=node.col_offset,
                    signature=(
                        f"from {qualified_module} import {alias.name} as {alias.asname}"
                        if qualified_module and alias.asname
                        else f"from {qualified_module} import {alias.name}"
                        if qualified_module
                        else f"import {alias.name}"
                    ),
                )
            )
            self.references.append(
                SymbolReference(
                    source_id=symbol_id,
                    target_id=qualified,
                    relationship="imports",
                    location=self.location,
                    line=node.lineno,
                    column=node.col_offset,
                )
            )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualified_name = self._qualify(node.name)
        symbol_id = self._make_symbol_id(self._container(), node.name, "class")
        self._symbol_ids[f"class:{qualified_name}"] = symbol_id
        self.symbols.append(
            SymbolNode(
                symbol_id=symbol_id,
                name=node.name,
                kind="class",
                location=self.location,
                line=node.lineno,
                column=node.col_offset,
                container=self._container(),
                signature=f"class {node.name}",
            )
        )
        self._add_decorators(node.decorator_list, qualified_name, node)
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node, is_async=True)

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._function_stack:
            inferred = _infer_type(node.value)
            for target in node.targets:
                if isinstance(target, ast.Name) and inferred:
                    self._bindings[self._function_stack[-1].qualified_name].append(
                        InferredBinding(
                            name=target.id,
                            inferred_type=inferred,
                            confidence=0.65,
                        )
                    )
        elif len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0]
            symbol_id = self._make_symbol_id(None, target.id, "variable")
            self._symbol_ids[f"var:{target.id}"] = symbol_id
            self.symbols.append(
                SymbolNode(
                    symbol_id=symbol_id,
                    name=target.id,
                    kind="variable",
                    location=self.location,
                    line=node.lineno,
                    column=node.col_offset,
                    signature=f"{target.id} = ...",
                )
            )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name):
            inferred = _expr_text(node.annotation)
            if self._function_stack:
                self._bindings[self._function_stack[-1].qualified_name].append(
                    InferredBinding(
                        name=node.target.id,
                        inferred_type=inferred,
                        confidence=0.95,
                    )
                )
            else:
                symbol_id = self._make_symbol_id(None, node.target.id, "variable")
                self._symbol_ids[f"var:{node.target.id}"] = symbol_id
                self.symbols.append(
                    SymbolNode(
                        symbol_id=symbol_id,
                        name=node.target.id,
                        kind="variable",
                        location=self.location,
                        line=node.lineno,
                        column=node.col_offset,
                        signature=f"{node.target.id}: {inferred}",
                    )
                )
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:
        if self._function_stack:
            inferred = _infer_type(node.value) if node.value else "None"
            if inferred:
                self._returns[self._function_stack[-1].qualified_name].append(inferred)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if self._function_stack:
            self._calls[self._function_stack[-1].qualified_name].append(_expr_text(node.func))
        self.generic_visit(node)

    def semantic_functions(self) -> list[SemanticFunction]:
        items: list[SemanticFunction] = []
        for symbol in self.symbols:
            if symbol.kind not in {"function", "async_function"}:
                continue
            qualified_name = _join_container(symbol.container, symbol.name)
            return_type = _merge_inferred_types(self._returns.get(qualified_name, []))
            items.append(
                SemanticFunction(
                    qualified_name=qualified_name,
                    location=self.location,
                    line=symbol.line,
                    inferred_return_type=return_type,
                    local_bindings=tuple(self._bindings.get(qualified_name, [])),
                    outbound_calls=tuple(self._calls.get(qualified_name, [])),
                )
            )
        return items

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, *, is_async: bool) -> None:
        qualified_name = self._qualify(node.name)
        kind = "async_function" if is_async else "function"
        symbol_id = self._make_symbol_id(self._container(), node.name, kind)
        self._symbol_ids[f"func:{qualified_name}"] = symbol_id
        signature_prefix = "async def" if is_async else "def"
        self.symbols.append(
            SymbolNode(
                symbol_id=symbol_id,
                name=node.name,
                kind=kind,
                location=self.location,
                line=node.lineno,
                column=node.col_offset,
                container=self._container(),
                signature=f"{signature_prefix} {node.name}(...)",
            )
        )
        self._add_decorators(node.decorator_list, qualified_name, node)
        frame = _FunctionFrame(qualified_name=qualified_name, line=node.lineno)
        self._function_stack.append(frame)
        self.generic_visit(node)
        self._function_stack.pop()

    def _add_decorators(
        self,
        decorators: list[ast.expr],
        target_qualified_name: str,
        node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        for decorator in decorators:
            text = _expr_text(decorator)
            symbol_id = self._make_symbol_id(target_qualified_name, text, "decorator")
            self.symbols.append(
                SymbolNode(
                    symbol_id=symbol_id,
                    name=text,
                    kind="decorator",
                    location=self.location,
                    line=decorator.lineno,
                    column=decorator.col_offset,
                    container=target_qualified_name,
                    signature=f"@{text}",
                )
            )
            target_id = self._symbol_ids.get(f"func:{target_qualified_name}") or self._symbol_ids.get(
                f"class:{target_qualified_name}"
            ) or target_qualified_name
            self.references.append(
                SymbolReference(
                    source_id=symbol_id,
                    target_id=target_id,
                    relationship="decorates",
                    location=self.location,
                    line=node.lineno,
                    column=node.col_offset,
                )
            )

    def _container(self) -> str | None:
        parts = [*self._class_stack]
        return ".".join(parts) if parts else None

    def _qualify(self, name: str) -> str:
        return _join_container(self._container(), name)

    def _make_symbol_id(self, container: str | None, name: str, kind: str) -> str:
        qualified_name = _join_container(container, name)
        return f"{self.location}::{kind}::{qualified_name}"


def _expr_text(node: ast.AST | None) -> str:
    if node is None:
        return "None"
    return ast.unparse(node)


def _infer_type(node: ast.AST | None) -> str | None:
    if node is None:
        return "None"
    if isinstance(node, ast.Constant):
        return type(node.value).__name__
    if isinstance(node, ast.JoinedStr):
        return "str"
    if isinstance(node, ast.List):
        return "list"
    if isinstance(node, ast.Dict):
        return "dict"
    if isinstance(node, ast.Set):
        return "set"
    if isinstance(node, ast.Tuple):
        return "tuple"
    if isinstance(node, ast.Compare):
        return "bool"
    if isinstance(node, ast.BoolOp):
        return "bool"
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return "bool"
    if isinstance(node, ast.Await):
        return _infer_type(node.value)
    if isinstance(node, ast.IfExp):
        left = _infer_type(node.body)
        right = _infer_type(node.orelse)
        if left and right:
            return left if left == right else f"{left} | {right}"
        return left or right
    if isinstance(node, ast.BinOp):
        left = _infer_type(node.left)
        right = _infer_type(node.right)
        if left == right and left in {"int", "float", "str"}:
            return left
        if {left, right} == {"int", "float"}:
            return "float"
    if isinstance(node, ast.Call):
        callee = _expr_text(node.func)
        if callee in {"int", "float", "str", "bool", "list", "dict", "set", "tuple"}:
            return callee
        return callee
    return None


def _merge_inferred_types(items: list[str]) -> str | None:
    if not items:
        return None
    kinds = tuple(dict.fromkeys(items))
    if len(kinds) == 1:
        return kinds[0]
    return " | ".join(kinds)


def _join_container(container: str | None, name: str) -> str:
    if container:
        return f"{container}.{name}"
    return name
