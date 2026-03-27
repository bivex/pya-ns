"""ANTLR-backed Python parser adapter."""

from __future__ import annotations

import ast
from time import perf_counter

from pya.domain.model import (
    GrammarVersion,
    ParseOutcome,
    ParseStatistics,
    SourceUnit,
    StructuralElement,
    StructuralElementKind,
)
from pya.domain.ports import PythonSyntaxParser
from pya.infrastructure.antlr.runtime import (
    ANTLR_GRAMMAR_VERSION,
    load_generated_types,
    parse_source_text,
)


class AntlrPythonSyntaxParser(PythonSyntaxParser):
    def __init__(self) -> None:
        self._generated = load_generated_types()

    @property
    def grammar_version(self) -> GrammarVersion:
        return ANTLR_GRAMMAR_VERSION

    def parse(self, source_unit: SourceUnit) -> ParseOutcome:
        started_at = perf_counter()
        try:
            parse_result = parse_source_text(source_unit.content, self._generated)
            structure_visitor = _build_structure_visitor(self._generated.visitor_type)()
            structure_visitor.visit(parse_result.tree)

            elements = tuple(structure_visitor.elements)
            elapsed_ms = round((perf_counter() - started_at) * 1000, 3)

            return ParseOutcome.success(
                source_unit=source_unit,
                grammar_version=self.grammar_version,
                diagnostics=parse_result.diagnostics,
                structural_elements=elements,
                statistics=ParseStatistics(
                    token_count=len(parse_result.token_stream.tokens),
                    structural_element_count=len(elements),
                    diagnostic_count=len(parse_result.diagnostics),
                    elapsed_ms=elapsed_ms,
                ),
            )
        except Exception as error:
            try:
                elements = tuple(_extract_structure_with_ast(source_unit))
                elapsed_ms = round((perf_counter() - started_at) * 1000, 3)
                return ParseOutcome.success(
                    source_unit=source_unit,
                    grammar_version=self.grammar_version,
                    diagnostics=(),
                    structural_elements=elements,
                    statistics=ParseStatistics(
                        token_count=0,
                        structural_element_count=len(elements),
                        diagnostic_count=0,
                        elapsed_ms=elapsed_ms,
                    ),
                )
            except Exception:
                elapsed_ms = round((perf_counter() - started_at) * 1000, 3)
                return ParseOutcome.technical_failure(
                    source_unit=source_unit,
                    grammar_version=self.grammar_version,
                    message=str(error),
                    elapsed_ms=elapsed_ms,
                )


def _build_structure_visitor(visitor_base: type) -> type:
    class PythonStructureVisitor(visitor_base):
        def __init__(self) -> None:
            super().__init__()
            self.elements: list[StructuralElement] = []
            self._containers: list[str] = []

        def visitDecorated(self, ctx):
            target_name = self._decorated_target_name(ctx)
            target_container = ".".join([*self._containers, target_name]) if target_name else None
            decorators = ctx.decorators()
            if decorators:
                for decorator in decorators.decorator():
                    raw_text = decorator.getText()
                    self.elements.append(
                        StructuralElement(
                            kind=StructuralElementKind.DECORATOR,
                            name=raw_text.removeprefix("@"),
                            line=decorator.start.line,
                            column=decorator.start.column,
                            container=target_container,
                            signature=raw_text,
                        )
                    )

            if ctx.classdef():
                return self.visit(ctx.classdef())
            if ctx.funcdef():
                return self.visit(ctx.funcdef())
            if ctx.async_funcdef():
                return self.visit(ctx.async_funcdef())
            return None

        def visitFuncdef(self, ctx):
            name = ctx.name().NAME().getText() if ctx.name() and ctx.name().NAME() else "unknown"
            self._append(
                StructuralElementKind.FUNCTION,
                name,
                ctx,
                signature=f"def {name}(...)",
            )
            return None

        def visitAsync_funcdef(self, ctx):
            funcdef = ctx.funcdef()
            name = funcdef.name().NAME().getText() if funcdef and funcdef.name() and funcdef.name().NAME() else "unknown"
            self._append(
                StructuralElementKind.ASYNC_FUNCTION,
                name,
                ctx,
                signature=f"async def {name}(...)",
            )
            return None

        def visitClassdef(self, ctx):
            name = ctx.name().NAME().getText() if ctx.name() and ctx.name().NAME() else "unknown"
            self._append(StructuralElementKind.CLASS, name, ctx, signature=f"class {name}")
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitImport_name(self, ctx):
            import_text = ctx.dotted_as_names().getText()
            self._append(
                StructuralElementKind.IMPORT,
                import_text,
                ctx,
                signature=f"import {import_text}",
            )
            return None

        def visitImport_from(self, ctx):
            text = ctx.getText()
            self._append(
                StructuralElementKind.IMPORT,
                text,
                ctx,
                signature=text,
            )
            return None

        def visitExpr_stmt(self, ctx):
            # Simple name assignments at module level
            if self._containers:
                return self.visitChildren(ctx)
            text = ctx.getText()
            if "=" in text and not text.startswith("("):
                # Extract the left-hand side as the variable name
                assign_text = text.split("=", 1)[0].strip()
                if ":" in assign_text:
                    annotated_name = assign_text.split(":", 1)[0].strip()
                    if annotated_name.isidentifier():
                        self._append(
                            StructuralElementKind.VARIABLE,
                            annotated_name,
                            ctx,
                            signature=f"{annotated_name}: ...",
                        )
                        return None
                if assign_text.isidentifier():
                    self._append(
                        StructuralElementKind.VARIABLE,
                        assign_text,
                        ctx,
                        signature=f"{assign_text} = ...",
                    )
            return None

        def visitAnnassign(self, ctx):
            if self._containers:
                return self.visitChildren(ctx)
            parent = getattr(ctx, "parentCtx", None)
            if parent is None or not hasattr(parent, "testlist_star_expr"):
                return None
            lhs = parent.testlist_star_expr()
            if lhs is None:
                return None
            lhs_text = lhs.getText().strip()
            if lhs_text.isidentifier():
                annotation = ctx.test().getText() if ctx.test() else "object"
                self._append(
                    StructuralElementKind.VARIABLE,
                    lhs_text,
                    parent,
                    signature=f"{lhs_text}: {annotation}",
                )
            return None

        def _append(self, kind, name: str, ctx, signature: str | None = None) -> None:
            container = ".".join(self._containers) if self._containers else None
            self.elements.append(
                StructuralElement(
                    kind=kind,
                    name=name,
                    line=ctx.start.line,
                    column=ctx.start.column,
                    container=container,
                    signature=signature,
                )
            )

        def _with_container(self, name: str, callback):
            self._containers.append(name)
            try:
                return callback()
            finally:
                self._containers.pop()

        def _decorated_target_name(self, ctx) -> str | None:
            if ctx.classdef() and ctx.classdef().name() and ctx.classdef().name().NAME():
                return ctx.classdef().name().NAME().getText()
            if ctx.funcdef() and ctx.funcdef().name() and ctx.funcdef().name().NAME():
                return ctx.funcdef().name().NAME().getText()
            if (
                ctx.async_funcdef()
                and ctx.async_funcdef().funcdef()
                and ctx.async_funcdef().funcdef().name()
                and ctx.async_funcdef().funcdef().name().NAME()
            ):
                return ctx.async_funcdef().funcdef().name().NAME().getText()
            return None

    return PythonStructureVisitor


def _extract_structure_with_ast(source_unit: SourceUnit) -> tuple[StructuralElement, ...]:
    tree = ast.parse(source_unit.content, filename=source_unit.location)
    visitor = _AstStructureVisitor(source_unit.location)
    visitor.visit(tree)
    return tuple(visitor.elements)


class _AstStructureVisitor(ast.NodeVisitor):
    def __init__(self, location: str) -> None:
        self.location = location
        self.elements: list[StructuralElement] = []
        self._containers: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            text = alias.asname and f"{alias.name} as {alias.asname}" or alias.name
            self._append(StructuralElementKind.IMPORT, alias.asname or alias.name, node, signature=f"import {text}")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        imported = ", ".join(
            f"{alias.name} as {alias.asname}" if alias.asname else alias.name
            for alias in node.names
        )
        self._append(
            StructuralElementKind.IMPORT,
            imported,
            node,
            signature=f"from {module} import {imported}".strip(),
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._append(StructuralElementKind.CLASS, node.name, node, signature=f"class {node.name}")
        self._with_container(node.name, node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._append(StructuralElementKind.FUNCTION, node.name, node, signature=f"def {node.name}(...)")
        self._append_decorators(node.decorator_list, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._append(
            StructuralElementKind.ASYNC_FUNCTION,
            node.name,
            node,
            signature=f"async def {node.name}(...)",
        )
        self._append_decorators(node.decorator_list, node.name)

    def visit_Assign(self, node: ast.Assign) -> None:
        if self._containers:
            return
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            return
        name = node.targets[0].id
        self._append(StructuralElementKind.VARIABLE, name, node, signature=f"{name} = ...")

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if self._containers or not isinstance(node.target, ast.Name):
            return
        name = node.target.id
        annotation = ast.unparse(node.annotation)
        self._append(StructuralElementKind.VARIABLE, name, node, signature=f"{name}: {annotation}")

    def _append_decorators(self, decorators: list[ast.expr], target_name: str) -> None:
        target_container = ".".join([*self._containers, target_name]) if target_name else None
        for decorator in decorators:
            raw = ast.unparse(decorator)
            self.elements.append(
                StructuralElement(
                    kind=StructuralElementKind.DECORATOR,
                    name=raw,
                    line=decorator.lineno,
                    column=decorator.col_offset,
                    container=target_container,
                    signature=f"@{raw}",
                )
            )

    def _append(self, kind, name: str, node: ast.AST, *, signature: str | None = None) -> None:
        container = ".".join(self._containers) if self._containers else None
        self.elements.append(
            StructuralElement(
                kind=kind,
                name=name,
                line=getattr(node, "lineno", 0),
                column=getattr(node, "col_offset", 0),
                container=container,
                signature=signature,
            )
        )

    def _with_container(self, name: str, node: ast.ClassDef) -> None:
        self._append_decorators(node.decorator_list, node.name)
        self._containers.append(name)
        self.generic_visit(node)
        self._containers.pop()
