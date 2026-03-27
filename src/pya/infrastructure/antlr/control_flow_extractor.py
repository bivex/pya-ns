"""Extract structured control flow from Python source through ANTLR."""

from __future__ import annotations

import ast
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
    SwitchCaseFlow,
    SwitchFlowStep,
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
        # Reconstruct text including hidden channel tokens (whitespace)
        tokens = self.token_stream.getTokens(
            start=ctx.start.tokenIndex,
            stop=ctx.stop.tokenIndex,
        )
        parts = []
        for token in tokens:
            parts.append(token.text)
        text = "".join(parts)
        # If the reconstructed text has no spaces but has multiple tokens,
        # add spaces between tokens (ANTLR doesn't include whitespace in tokens)
        if len(tokens) > 1 and " " not in text and text.isalnum() or any(c in text for c in "=<>+-*/%&|^~!"):
            # Reconstruct with spaces between tokens
            text = " ".join(token.text for token in tokens)
        return text

    def compact(self, ctx, *, limit: int = 96) -> str:
        # Get original text with whitespace
        text = self.text(ctx)
        # Strip leading/trailing whitespace but preserve internal spacing
        text = text.strip()
        # Collapse multiple consecutive spaces to single space
        text = re.sub(r"  +", " ", text)
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
            try:
                return _extract_with_ast(source_unit)
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
            self._pending_decorators: list[str] = []

        def visitDecorated(self, ctx):
            decorators = []
            if ctx.decorators():
                decorators = [
                    context.compact(decorator).removeprefix("@")
                    for decorator in ctx.decorators().decorator()
                ]

            previous = self._pending_decorators
            self._pending_decorators = decorators
            try:
                if ctx.classdef():
                    return self.visit(ctx.classdef())
                if ctx.funcdef():
                    return self.visit(ctx.funcdef())
                if ctx.async_funcdef():
                    return self.visit(ctx.async_funcdef())
                return None
            finally:
                self._pending_decorators = previous

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
                    decorators=tuple(self._pending_decorators),
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
                    decorators=tuple(self._pending_decorators),
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
            if hasattr(compound_ctx, "match_stmt") and compound_ctx.match_stmt():
                return self._extract_match_stmt(compound_ctx.match_stmt())

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

        def _extract_match_stmt(self, match_ctx) -> SwitchFlowStep:
            subject = (
                context.compact(match_ctx.subject_expr())
                if hasattr(match_ctx, "subject_expr") and match_ctx.subject_expr()
                else "value"
            )
            cases: list[SwitchCaseFlow] = []
            for case_ctx in match_ctx.case_block() if hasattr(match_ctx, "case_block") else ():
                pattern = context.compact(case_ctx.patterns()) if case_ctx.patterns() else "_"
                guard = (
                    context.compact(case_ctx.guard())
                    if hasattr(case_ctx, "guard") and case_ctx.guard()
                    else ""
                )
                label = f"case {pattern}"
                if guard:
                    label = f"{label} {guard}"
                cases.append(
                    SwitchCaseFlow(
                        label=label,
                        steps=self._extract_block(case_ctx.block() if hasattr(case_ctx, "block") else None),
                    )
                )
            return SwitchFlowStep(expression=subject, cases=tuple(cases))

    return PythonControlFlowVisitor


def _extract_with_ast(source_unit: SourceUnit) -> ControlFlowDiagram:
    tree = ast.parse(source_unit.content, filename=source_unit.location)
    visitor = _AstControlFlowVisitor(source_unit)
    visitor.visit(tree)
    return ControlFlowDiagram(
        source_location=source_unit.location,
        functions=tuple(visitor.functions),
    )


class _AstControlFlowVisitor(ast.NodeVisitor):
    def __init__(self, source_unit: SourceUnit) -> None:
        self._source_unit = source_unit
        self.functions: list[FunctionControlFlow] = []
        self._containers: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._containers.append(node.name)
        self.generic_visit(node)
        self._containers.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(
            FunctionControlFlow(
                name=node.name,
                signature=f"def {node.name}(...)",
                container=".".join(self._containers) if self._containers else None,
                steps=self._extract_body(node.body),
                decorators=tuple(_compact_ast_text(self._source_unit.content, decorator).removeprefix("@") for decorator in node.decorator_list),
            )
        )

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.functions.append(
            FunctionControlFlow(
                name=node.name,
                signature=f"async def {node.name}(...)",
                container=".".join(self._containers) if self._containers else None,
                steps=self._extract_body(node.body),
                decorators=tuple(_compact_ast_text(self._source_unit.content, decorator).removeprefix("@") for decorator in node.decorator_list),
            )
        )

    def _extract_body(self, statements: list[ast.stmt]) -> tuple[ControlFlowStep, ...]:
        steps: list[ControlFlowStep] = []
        for statement in statements:
            extracted = self._extract_statement(statement)
            if extracted is not None:
                steps.append(extracted)
        return tuple(steps)

    def _extract_statement(self, statement: ast.stmt) -> ControlFlowStep | None:
        if isinstance(statement, ast.If):
            return IfFlowStep(
                condition=_compact_ast_text(self._source_unit.content, statement.test),
                then_steps=self._extract_body(statement.body),
                else_steps=self._extract_body(statement.orelse),
            )
        if isinstance(statement, ast.While):
            return WhileFlowStep(
                condition=_compact_ast_text(self._source_unit.content, statement.test),
                body_steps=self._extract_body(statement.body),
            )
        if isinstance(statement, (ast.For, ast.AsyncFor)):
            return ForInFlowStep(
                header=(
                    f"{_compact_ast_text(self._source_unit.content, statement.target)} in "
                    f"{_compact_ast_text(self._source_unit.content, statement.iter)}"
                ),
                body_steps=self._extract_body(statement.body),
            )
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            return WithFlowStep(
                header=_compact_ast_text(self._source_unit.content, statement).split(":", 1)[0].strip(),
                body_steps=self._extract_body(statement.body),
            )
        if isinstance(statement, ast.Try):
            catches = [
                CatchClauseFlow(
                    pattern=(
                        f"except {_compact_ast_text(self._source_unit.content, handler.type)}"
                        if handler.type
                        else "except"
                    ),
                    steps=self._extract_body(handler.body),
                )
                for handler in statement.handlers
            ]
            if statement.finalbody:
                catches.append(
                    CatchClauseFlow(
                        pattern="finally",
                        steps=self._extract_body(statement.finalbody),
                    )
                )
            return DoCatchFlowStep(
                body_steps=self._extract_body(statement.body),
                catches=tuple(catches),
            )
        if isinstance(statement, ast.Match):
            cases = []
            for case in statement.cases:
                label = f"case {_compact_ast_text(self._source_unit.content, case.pattern)}"
                if case.guard is not None:
                    label = f"{label} if {_compact_ast_text(self._source_unit.content, case.guard)}"
                cases.append(SwitchCaseFlow(label=label, steps=self._extract_body(case.body)))
            return SwitchFlowStep(
                expression=_compact_ast_text(self._source_unit.content, statement.subject),
                cases=tuple(cases),
            )
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return None
        return ActionFlowStep(_compact_ast_text(self._source_unit.content, statement))


def _compact_ast_text(source_text: str, node: ast.AST | None, *, limit: int = 96) -> str:
    if node is None:
        return ""
    text = ast.get_source_segment(source_text, node) or ast.unparse(node)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}..."
