"""ANTLR-backed Python parser adapter."""

from __future__ import annotations

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
                if assign_text.isidentifier():
                    self._append(
                        StructuralElementKind.VARIABLE,
                        assign_text,
                        ctx,
                        signature=f"{assign_text} = ...",
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

    return PythonStructureVisitor
