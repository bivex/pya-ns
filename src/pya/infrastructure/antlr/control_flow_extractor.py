"""Extract structured control flow from Python source through ANTLR."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pya.domain.control_flow import (
    ActionFlowStep,
    CatchClauseFlow,
    ControlFlowDiagram,
    ControlFlowStep,
    DoCatchFlowStep,
    ForInFlowStep,
    FunctionControlFlow,
    IfFlowStep,
    WhileFlowStep,
    WithFlowStep,
)
from pya.domain.model import SourceUnit
from pya.domain.ports import PythonControlFlowExtractor
from pya.infrastructure.antlr.runtime import (
    load_generated_types,
    parse_source_text,
)


@dataclass(frozen=True, slots=True)
class _ExtractorContext:
    token_stream: object

    def text(self, ctx) -> str:
        if ctx is None:
            return ""
        return self.token_stream.getText(
            start=ctx.start.tokenIndex,
            stop=ctx.stop.tokenIndex,
        )

    def compact(self, ctx, *, limit: int = 96) -> str:
        text = re.sub(r"\s+", " ", self.text(ctx)).strip()
        if len(text) <= limit:
            return text
        return f"{text[: limit - 1]}..."


class AntlrPythonControlFlowExtractor(PythonControlFlowExtractor):
    def __init__(self) -> None:
        self._generated = load_generated_types()

    def extract(self, source_unit: SourceUnit) -> ControlFlowDiagram:
        try:
            parse_result = parse_source_text(source_unit.content, self._generated)
            visitor = _build_control_flow_visitor(
                self._generated.visitor_type,
                _ExtractorContext(token_stream=parse_result.token_stream),
            )()
            visitor.visit(parse_result.tree)
            return ControlFlowDiagram(
                source_location=source_unit.location,
                functions=tuple(visitor.functions),
            )
        except Exception:
            return ControlFlowDiagram(
                source_location=source_unit.location,
                functions=(),
            )


def _build_control_flow_visitor(visitor_base: type, context: _ExtractorContext) -> type:
    class PythonControlFlowVisitor(visitor_base):
        def __init__(self) -> None:
            super().__init__()
            self.functions: list[FunctionControlFlow] = []
            self._containers: list[str] = []

        def visitClassdef(self, ctx):
            name = ctx.NAME().getText()
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitFuncdef(self, ctx):
            name = ctx.NAME().getText()
            signature = f"def {name}(...)"
            suite = ctx.suite()
            self.functions.append(
                FunctionControlFlow(
                    name=name,
                    signature=signature,
                    container=".".join(self._containers) if self._containers else None,
                    steps=self._extract_suite(suite),
                )
            )
            return None

        def visitAsync_funcdef(self, ctx):
            funcdef = ctx.funcdef()
            name = funcdef.NAME().getText()
            signature = f"async def {name}(...)"
            suite = funcdef.suite()
            self.functions.append(
                FunctionControlFlow(
                    name=name,
                    signature=signature,
                    container=".".join(self._containers) if self._containers else None,
                    steps=self._extract_suite(suite),
                )
            )
            return None

        def _with_container(self, name: str, callback):
            self._containers.append(name)
            try:
                return callback()
            finally:
                self._containers.pop()

        def _extract_suite(self, suite_ctx) -> tuple[ControlFlowStep, ...]:
            if suite_ctx is None:
                return ()
            steps: list[ControlFlowStep] = []
            for stmt_ctx in self._get_statements(suite_ctx):
                extracted = self._extract_statement(stmt_ctx)
                if extracted is not None:
                    steps.append(extracted)
            return tuple(steps)

        def _get_statements(self, suite_ctx) -> list:
            """Get all statement contexts from a suite."""
            stmts = []
            if hasattr(suite_ctx, "stmt") and suite_ctx.stmt():
                for stmt_ctx in suite_ctx.stmt():
                    stmts.append(stmt_ctx)
            elif hasattr(suite_ctx, "simple_stmt") and suite_ctx.simple_stmt():
                stmts.append(suite_ctx.simple_stmt())
            return stmts

        def _extract_statement(self, stmt_ctx) -> ControlFlowStep | None:
            # Check for compound statements
            if hasattr(stmt_ctx, "compound_stmt") and stmt_ctx.compound_stmt():
                return self._extract_compound_stmt(stmt_ctx.compound_stmt())
            # Check for simple statements
            if hasattr(stmt_ctx, "simple_stmt") and stmt_ctx.simple_stmt():
                return ActionFlowStep(context.compact(stmt_ctx.simple_stmt()))
            # Fallback
            return ActionFlowStep(context.compact(stmt_ctx))

        def _extract_compound_stmt(self, compound_ctx) -> ControlFlowStep | None:
            if hasattr(compound_ctx, "if_stmt") and compound_ctx.if_stmt():
                return self._extract_if_stmt(compound_ctx.if_stmt())
            if hasattr(compound_ctx, "while_stmt") and compound_ctx.while_stmt():
                return self._extract_while_stmt(compound_ctx.while_stmt())
            if hasattr(compound_ctx, "for_stmt") and compound_ctx.for_stmt():
                return self._extract_for_stmt(compound_ctx.for_stmt())
            if hasattr(compound_ctx, "try_stmt") and compound_ctx.try_stmt():
                return self._extract_try_stmt(compound_ctx.try_stmt())
            if hasattr(compound_ctx, "with_stmt") and compound_ctx.with_stmt():
                return self._extract_with_stmt(compound_ctx.with_stmt())
            if hasattr(compound_ctx, "funcdef") and compound_ctx.funcdef():
                # Nested function -- skip, don't recurse into nested defs
                return None
            if hasattr(compound_ctx, "classdef") and compound_ctx.classdef():
                return None
            if hasattr(compound_ctx, "async_stmt") and compound_ctx.async_stmt():
                return self._extract_async_stmt(compound_ctx.async_stmt())
            return ActionFlowStep(context.compact(compound_ctx))

        def _extract_async_stmt(self, async_ctx) -> ControlFlowStep | None:
            if hasattr(async_ctx, "for_stmt") and async_ctx.for_stmt():
                return self._extract_for_stmt(async_ctx.for_stmt())
            if hasattr(async_ctx, "with_stmt") and async_ctx.with_stmt():
                return self._extract_with_stmt(async_ctx.with_stmt())
            return ActionFlowStep(context.compact(async_ctx))

        def _extract_if_stmt(self, if_ctx) -> IfFlowStep:
            # Python3 grammar: if_stmt: 'if' test ':' suite ('elif' test ':' suite)* ('else' ':' suite)?
            # Get all suites (if-body, elif bodies, else body)
            suites = if_ctx.suite() if hasattr(if_ctx, "suite") else []
            tests = if_ctx.test() if hasattr(if_ctx, "test") else []

            condition = context.compact(tests[0]) if tests else "condition"
            then_steps = self._extract_suite(suites[0]) if suites else ()

            # Build else steps: chain elif as nested IfFlowStep
            else_steps: tuple[ControlFlowStep, ...] = ()
            if len(tests) > 1:
                # There are elif branches
                else_steps = (self._build_elif_chain(tests[1:], suites[1:], if_ctx),)
            elif len(suites) > len(tests):
                # There is a plain else
                else_steps = self._extract_suite(suites[-1])

            return IfFlowStep(
                condition=condition,
                then_steps=then_steps,
                else_steps=else_steps,
            )

        def _build_elif_chain(self, tests, suites, if_ctx) -> IfFlowStep:
            condition = context.compact(tests[0]) if tests else "condition"
            then_steps = self._extract_suite(suites[0]) if suites else ()

            else_steps: tuple[ControlFlowStep, ...] = ()
            if len(tests) > 1:
                else_steps = (self._build_elif_chain(tests[1:], suites[1:], if_ctx),)
            elif len(suites) > len(tests):
                else_steps = self._extract_suite(suites[-1])

            return IfFlowStep(
                condition=condition,
                then_steps=then_steps,
                else_steps=else_steps,
            )

        def _extract_while_stmt(self, while_ctx) -> WhileFlowStep:
            test = while_ctx.test() if hasattr(while_ctx, "test") else None
            condition = context.compact(test) if test else "condition"
            suites = while_ctx.suite() if hasattr(while_ctx, "suite") else []
            body_steps = self._extract_suite(suites[0]) if suites else ()
            return WhileFlowStep(
                condition=condition,
                body_steps=body_steps,
            )

        def _extract_for_stmt(self, for_ctx) -> ForInFlowStep:
            exprlist = for_ctx.exprlist() if hasattr(for_ctx, "exprlist") else None
            testlist = for_ctx.testlist() if hasattr(for_ctx, "testlist") else None
            header_parts = []
            if exprlist:
                header_parts.append(context.compact(exprlist))
            header_parts.append("in")
            if testlist:
                header_parts.append(context.compact(testlist))
            header = " ".join(header_parts) if header_parts else "item in iterable"

            suites = for_ctx.suite() if hasattr(for_ctx, "suite") else []
            body_steps = self._extract_suite(suites[0]) if suites else ()
            return ForInFlowStep(
                header=header,
                body_steps=body_steps,
            )

        def _extract_try_stmt(self, try_ctx) -> DoCatchFlowStep:
            suites = try_ctx.suite() if hasattr(try_ctx, "suite") else []
            body_steps = self._extract_suite(suites[0]) if suites else ()

            catches: list[CatchClauseFlow] = []
            except_clauses = (
                try_ctx.except_clause() if hasattr(try_ctx, "except_clause") else []
            )
            # except clauses correspond to suites[1..len(except_clauses)]
            for i, except_clause in enumerate(except_clauses):
                pattern = context.compact(except_clause) if except_clause else "except"
                catch_suite_index = i + 1
                catch_steps = (
                    self._extract_suite(suites[catch_suite_index])
                    if catch_suite_index < len(suites)
                    else ()
                )
                catches.append(
                    CatchClauseFlow(
                        pattern=pattern,
                        steps=catch_steps,
                    )
                )

            # Check for finally (last suite if there's a 'finally' keyword)
            text = context.text(try_ctx)
            if "finally" in text and len(suites) > len(except_clauses) + 1:
                finally_steps = self._extract_suite(suites[-1])
                if finally_steps:
                    catches.append(
                        CatchClauseFlow(
                            pattern="finally",
                            steps=finally_steps,
                        )
                    )

            return DoCatchFlowStep(
                body_steps=body_steps,
                catches=tuple(catches),
            )

        def _extract_with_stmt(self, with_ctx) -> WithFlowStep:
            # with_stmt: 'with' with_item (',' with_item)* ':' suite
            header = context.compact(with_ctx)
            # Extract just the header before the ':'
            if ":" in header:
                header = header.split(":", 1)[0].strip()

            suites = with_ctx.suite() if hasattr(with_ctx, "suite") else []
            body_steps = self._extract_suite(suites[0]) if suites else ()
            return WithFlowStep(
                header=header,
                body_steps=body_steps,
            )

    return PythonControlFlowVisitor
