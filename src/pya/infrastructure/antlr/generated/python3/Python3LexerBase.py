"""Base class for Python3Lexer."""

from __future__ import annotations

import re

from antlr4.Lexer import Lexer
from antlr4.Token import CommonToken, Token


class Python3LexerBase(Lexer):
    """Base class for Python3 lexer with indentation handling."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pending_tokens: list[CommonToken] = []
        self._indents: list[int] = []
        self._opened = 0
        self._last_token: CommonToken | None = None

    def reset(self) -> None:
        self._pending_tokens.clear()
        self._indents.clear()
        self._opened = 0
        self._last_token = None
        super().reset()

    def nextToken(self):
        if self._pending_tokens:
            token = self._pending_tokens.pop(0)
            if token.channel == Token.DEFAULT_CHANNEL:
                self._last_token = token
            return token

        if self._input.LA(1) == Token.EOF and self._indents:
            self._pending_tokens = [token for token in self._pending_tokens if token.type != Token.EOF]
            self._emit_token(self._common_token(self.NEWLINE, "\n"))
            while self._indents:
                self._emit_token(self._create_dedent())
                self._indents.pop()
            self._emit_token(self._common_token(Token.EOF, "<EOF>"))
            return self._pending_tokens.pop(0)

        next_token = super().nextToken()
        if next_token.channel == Token.DEFAULT_CHANNEL:
            self._last_token = next_token

        if self._pending_tokens:
            self._pending_tokens.append(next_token)
            token = self._pending_tokens.pop(0)
            if token.channel == Token.DEFAULT_CHANNEL:
                self._last_token = token
            return token
        return next_token

    def atStartOfInput(self) -> bool:
        return self.column == 0 and self.line == 1

    def onNewLine(self) -> None:
        new_line = re.sub(r"[^\r\n\f]+", "", self.text)
        spaces = re.sub(r"[\r\n\f]+", "", self.text)
        next_char = self._input.LA(1)
        previous_was_layout = self._last_token is None or self._last_token.type in {
            self.NEWLINE,
            self.INDENT,
            self.DEDENT,
        }

        if self._opened > 0:
            self.skip()
            return

        if next_char in (10, 13, 35):
            if not previous_was_layout:
                self._emit_token(self._common_token(self.NEWLINE, new_line))
            self.skip()
            return

        self._emit_token(self._common_token(self.NEWLINE, new_line))

        indent = self._indentation_count(spaces)
        previous = self._indents[-1] if self._indents else 0

        if indent == previous:
            self.skip()
            return
        if indent > previous:
            self._indents.append(indent)
            self._emit_token(self._common_token(self.INDENT, spaces))
            self.skip()
            return

        while self._indents and self._indents[-1] > indent:
            self._emit_token(self._create_dedent())
            self._indents.pop()
        self.skip()

    def openBrace(self) -> None:
        self._opened += 1

    def closeBrace(self) -> None:
        if self._opened > 0:
            self._opened -= 1

    def openBrack(self) -> None:
        self.openBrace()

    def closeBrack(self) -> None:
        self.closeBrace()

    def openParen(self) -> None:
        self.openBrace()

    def closeParen(self) -> None:
        self.closeBrace()

    def _emit_token(self, token: CommonToken) -> None:
        self._pending_tokens.append(token)

    def _create_dedent(self) -> CommonToken:
        dedent = self._common_token(self.DEDENT, "")
        if self._last_token is not None:
            dedent.line = self._last_token.line
        return dedent

    def _common_token(self, token_type: int, text: str) -> CommonToken:
        stop = self.getCharIndex() - 1
        start = stop if not text else stop - len(text) + 1
        token = CommonToken(
            self._tokenFactorySourcePair,
            token_type,
            Token.DEFAULT_CHANNEL,
            start,
            stop,
        )
        token.text = text
        token.line = self.line
        token.column = 0
        return token

    @staticmethod
    def _indentation_count(spaces: str) -> int:
        count = 0
        for char in spaces:
            if char == "\t":
                count += 8 - (count % 8)
            else:
                count += 1
        return count
