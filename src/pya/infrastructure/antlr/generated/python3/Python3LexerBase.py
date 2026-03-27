"""Base class for Python3Lexer."""

from antlr4.Lexer import Lexer


class Python3LexerBase(Lexer):
    """Base class for Python3 lexer with Python3 grammar support."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bracket_stack = []
        self._last_token_was_newline = False

    def atStartOfInput(self) -> bool:
        """Check if the lexer is at the start of input."""
        return self._input.LA(1) == -1 or (
            self._tokenStartCharIndex == 0 and
            self._tokenStartLine == 1
        )

    def onNewLine(self) -> None:
        """Called when a newline token is encountered."""
        self._last_token_was_newline = True

    def openBrace(self) -> None:
        """Track opening brace."""
        self._bracket_stack.append("{")
        self._last_token_was_newline = False

    def closeBrace(self) -> None:
        """Track closing brace."""
        if self._bracket_stack:
            self._bracket_stack.pop()
        self._last_token_was_newline = False

    def openBrack(self) -> None:
        """Track opening bracket."""
        self._bracket_stack.append("[")
        self._last_token_was_newline = False

    def closeBrack(self) -> None:
        """Track closing bracket."""
        if self._bracket_stack:
            self._bracket_stack.pop()
        self._last_token_was_newline = False

    def openParen(self) -> None:
        """Track opening parenthesis."""
        self._bracket_stack.append("(")
        self._last_token_was_newline = False
