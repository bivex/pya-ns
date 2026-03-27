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
            name = ctx.name().NAME().getText() if ctx.name() and ctx.name().NAME() else "unknown"
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitFuncdef(self, ctx):
            name = ctx.name().NAME().getText() if ctx.name() and ctx.name().NAME() else "unknown"
            signature = f"def {name}(...)"
            block = ctx.block()  # Returns a single BlockContext
            self.functions.append(
                FunctionControlFlow(
                    name=name,
                    signature=signature,
                    container=".".join(self._containers) if self._containers else None,
                    steps=self._extract_block(block),
                )
            )
            return None

        def visitAsync_funcdef(self, ctx):
            funcdef = ctx.funcdef()
            name = funcdef.name().NAME().getText() if funcdef and funcdef.name() and funcdef.name().NAME() else "unknown"
            signature = f"async def {name}(...)"
            block = funcdef.block()  # Returns a single BlockContext
            self.functions.append(
                FunctionControlFlow(
                    name=name,
                    signature=signature,
                    container=".".join(self._containers) if self._containers else None,
                    steps=self._extract_block(block),
                )
            )
            return None

        def _with_container(self, name: str, callback):
            self._containers.append(name)
            try:
                return callback()
            finally:
                self._containers.pop()

        def _extract_block(self, block_ctx) -> tuple[ControlFlowStep, ...]:
            """Extract steps from a block (Python3 grammar uses blocks, not suites)."""
            if block_ctx is None:
                return ()
            steps: list[ControlFlowStep] = []

            # Check for simple statements first
            if hasattr(block_ctx, "simple_stmts") and block_ctx.simple_stmts():
                simple_stmts = block_ctx.simple_stmts()
                if hasattr(simple_stmts, "simple_stmt") and simple_stmts.simple_stmt():
                    for stmt in simple_stmts.simple_stmt():
                        extracted = self._extract_statement(stmt)
                        if extracted is not None:
                            steps.append(extracted)

            # Check for regular statements (block.stmt() returns a list)
            if hasattr(block_ctx, "stmt"):
                stmts = block_ctx.stmt()
                if stmts:
                    for stmt in stmts:
                        extracted = self._extract_statement(stmt)
                        if extracted is not None:
                            steps.append(extracted)

            return tuple(steps)

        def _extract_statement(self, stmt_ctx) -> ControlFlowStep | None:
            """Extract a single statement (could be compound or simple)."""
            if stmt_ctx is None:
                return None

            # Check the statement type
            if hasattr(stmt_ctx, "compound_stmt"):
                compound = stmt_ctx.compound_stmt()
                if compound:
                    return self._extract_compound_stmt(compound)

            # Simple statement - represent as action
            return ActionFlowStep(context.compact(stmt_ctx))

        def _extract_compound_stmt(self, compound_ctx) -> ControlFlowStep | None:
            """Extract compound statements (if, while, for, try, with, etc.)."""
            if compound_ctx is None:
                return None

            # Check each type of compound statement
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

            # Skip nested function/class definitions (don't recurse)
            if hasattr(compound_ctx, "funcdef") and compound_ctx.funcdef():
                return None
            if hasattr(compound_ctx, "classdef") and compound_ctx.classdef():
                return None
            if hasattr(compound_ctx, "async_stmt") and compound_ctx.async_stmt():
                async_stmt = compound_ctx.async_stmt()
                if hasattr(async_stmt, "funcdef") and async_stmt.funcdef():
                    return None
                if hasattr(async_stmt, "for_stmt") and async_stmt.for_stmt():
                    return self._extract_for_stmt(async_stmt.for_stmt())
                if hasattr(async_stmt, "with_stmt") and async_stmt.with_stmt():
                    return self._extract_with_stmt(async_stmt.with_stmt())

            # Fallback
            return ActionFlowStep(context.compact(compound_ctx))

        def _extract_if_stmt(self, if_ctx) -> IfFlowStep:
            """Extract if/elif/else statement.
            Python3 grammar: if_stmt: 'if' test ':' block ('elif' test ':' block)* ('else' ':' block)?
            - if_ctx.test() returns a list of test expressions
            - if_ctx.block() returns a list of block contexts
            """
            tests = list(if_ctx.test()) if hasattr(if_ctx, "test") else []
            blocks = list(if_ctx.block()) if hasattr(if_ctx, "block") else []

            if not tests or not blocks:
                return IfFlowStep(condition="condition", then_steps=(), else_steps=())

            # First if
            condition = context.compact(tests[0]) if tests[0] else "condition"
            then_steps = self._extract_block(blocks[0]) if len(blocks) > 0 else ()

            # Handle elif/else
            else_steps: tuple[ControlFlowStep, ...] = ()

            if len(tests) > 1:
                # We have elif branches - build nested if chain
                else_steps = (self._build_elif_chain(tests[1:], blocks[1:], if_ctx),)
            elif len(blocks) > len(tests):
                # Plain else clause
                else_steps = self._extract_block(blocks[-1])

            return IfFlowStep(
                condition=condition,
                then_steps=then_steps,
                else_steps=else_steps,
            )

        def _build_elif_chain(self, tests, blocks, parent_ctx) -> IfFlowStep:
            """Build nested if chain for elif statements."""
            if not tests:
                # No more elif - check for else
                if blocks:
                    return IfFlowStep(
                        condition="else",
                        then_steps=self._extract_block(blocks[0]),
                        else_steps=(),
                    )
                return IfFlowStep(condition="else", then_steps=(), else_steps=())

            condition = context.compact(tests[0]) if tests[0] else "condition"
            then_steps = self._extract_block(blocks[0]) if len(blocks) > 0 else ()

            else_steps: tuple[ControlFlowStep, ...] = ()
            if len(tests) > 1:
                # More elif branches
                else_steps = (self._build_elif_chain(tests[1:], blocks[1:], parent_ctx),)
            elif len(blocks) > len(tests):
                # Plain else
                else_steps = self._extract_block(blocks[-1])

            return IfFlowStep(
                condition=condition,
                then_steps=then_steps,
                else_steps=else_steps,
            )

        def _extract_while_stmt(self, while_ctx) -> WhileFlowStep:
            """Extract while statement.
            Python3 grammar: while_stmt: 'while' test ':' block
            - while_ctx.test() returns a single test expression
            - while_ctx.block() returns a single block context
            """
            test = while_ctx.test() if hasattr(while_ctx, "test") else None
            block = while_ctx.block() if hasattr(while_ctx, "block") else None

            condition = context.compact(test) if test else "condition"
            body_steps = self._extract_block(block) if block else ()

            return WhileFlowStep(
                condition=condition,
                body_steps=body_steps,
            )

        def _extract_for_stmt(self, for_ctx) -> ForInFlowStep:
            """Extract for statement.
            Python3 grammar: for_stmt: 'for' exprlist 'in' testlist ':' block
            - for_ctx.exprlist() returns a single exprlist context
            - for_ctx.testlist() returns a single testlist context
            - for_ctx.block() returns a single block context
            """
            exprlist = for_ctx.exprlist() if hasattr(for_ctx, "exprlist") else None
            testlist = for_ctx.testlist() if hasattr(for_ctx, "testlist") else None
            block = for_ctx.block() if hasattr(for_ctx, "block") else None

            header_parts = []
            if exprlist:
                header_parts.append(context.compact(exprlist))
            header_parts.append("in")
            if testlist:
                header_parts.append(context.compact(testlist))
            header = " ".join(header_parts) if header_parts else "item in iterable"

            body_steps = self._extract_block(block) if block else ()

            return ForInFlowStep(
                header=header,
                body_steps=body_steps,
            )

        def _extract_try_stmt(self, try_ctx) -> DoCatchFlowStep:
            """Extract try/except/finally statement.
            Python3 grammar: try_stmt: 'try' ':' block ('except' ...)* ('finally' ':' block)?
            - try_ctx.block() returns a list of block contexts
            """
            blocks = list(try_ctx.block()) if hasattr(try_ctx, "block") else []

            if not blocks:
                return DoCatchFlowStep(body_steps=(), catches=())

            # First block is the try body
            body_steps = self._extract_block(blocks[0])

            catches: list[CatchClauseFlow] = []

            # Look for except clauses and finally block
            # The structure varies based on what's present
            remaining_blocks = blocks[1:] if len(blocks) > 1 else []

            # Check if there's a finally block (last block in try_stmt with 'finally')
            text = context.text(try_ctx)
            has_finally = "finally" in text

            if has_finally and remaining_blocks:
                # Last block is finally
                finally_steps = self._extract_block(remaining_blocks[-1])
                if finally_steps:
                    catches.append(
                        CatchClauseFlow(
                            pattern="finally",
                            steps=finally_steps,
                        )
                    )
                remaining_blocks = remaining_blocks[:-1]

            # The remaining blocks are except handlers
            for block in remaining_blocks:
                catches.append(
                    CatchClauseFlow(
                        pattern="except",
                        steps=self._extract_block(block),
                    )
                )

            return DoCatchFlowStep(
                body_steps=body_steps,
                catches=tuple(catches),
            )

        def _extract_with_stmt(self, with_ctx) -> WithFlowStep:
            """Extract with statement.
            Python3 grammar: with_stmt: 'with' with_item (',' with_item)* ':' block
            - with_ctx.block() returns a single block context
            """
            block = with_ctx.block() if hasattr(with_ctx, "block") else None

            # Extract the with header (before the colon)
            header = context.compact(with_ctx)
            if ":" in header:
                header = header.split(":", 1)[0].strip()

            body_steps = self._extract_block(block) if block else ()

            return WithFlowStep(
                header=header,
                body_steps=body_steps,
            )

    return PythonControlFlowVisitor
