"""Base class for Python3Parser."""

from antlr4.Parser import Parser


class Python3ParserBase(Parser):
    """Base class for Python3 parser."""

    def CannotBePlusMinus(self) -> bool:
        next_token = self._input.LT(1)
        return getattr(next_token, "text", None) not in {"+", "-"}

    def CannotBeDotLpEq(self) -> bool:
        next_token = self._input.LT(1)
        return getattr(next_token, "text", None) not in {".", "(", "="}
