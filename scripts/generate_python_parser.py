"""Generate Python parser artifacts from the vendored Python3 grammar."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from urllib.request import urlretrieve


ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "build" / "tools"
GRAMMAR_DIR = ROOT / "resources" / "grammars" / "python3"
OUTPUT_DIR = ROOT / "src" / "pya" / "infrastructure" / "antlr" / "generated" / "python3"
ANTLR_VERSION = "4.13.2"
ANTLR_JAR = TOOLS_DIR / f"antlr-{ANTLR_VERSION}-complete.jar"
ANTLR_JAR_URL = f"https://www.antlr.org/download/antlr-{ANTLR_VERSION}-complete.jar"


def main() -> None:
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    _ensure_grammar_exists()
    _ensure_antlr_jar_exists()
    _generate_parser()
    _ensure_package_files()


def _ensure_grammar_exists() -> None:
    required = (
        GRAMMAR_DIR / "Python3Lexer.g4",
        GRAMMAR_DIR / "Python3Parser.g4",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(
            f"missing grammar files: {', '.join(missing)}\n"
            "Source them from https://github.com/antlr/grammars-v4/tree/master/python/python3"
        )


def _ensure_antlr_jar_exists() -> None:
    if ANTLR_JAR.exists():
        return
    print(f"Downloading ANTLR {ANTLR_VERSION}...")
    urlretrieve(ANTLR_JAR_URL, ANTLR_JAR)


def _generate_parser() -> None:
    command = [
        "java",
        "-jar",
        str(ANTLR_JAR),
        "-Dlanguage=Python3",
        "-visitor",
        "-no-listener",
        "-o",
        str(OUTPUT_DIR),
        str(GRAMMAR_DIR / "Python3Lexer.g4"),
        str(GRAMMAR_DIR / "Python3Parser.g4"),
    ]
    subprocess.run(command, check=True, cwd=ROOT)


def _ensure_package_files() -> None:
    init_file = OUTPUT_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text('"""Generated Python3 ANTLR parser."""\n', encoding="utf-8")

    # Create base classes for lexer and parser
    (OUTPUT_DIR / "Python3LexerBase.py").write_text(
        '''"""Base class for Python3Lexer."""

from __future__ import annotations

import re

from antlr4.Lexer import Lexer
from antlr4.Token import CommonToken, Token

class Python3LexerBase(Lexer):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bracket_stack = []
        self._last_token_was_newline = False
    def nextToken(self):
        if self._pending_tokens:
            return self._pending_tokens.pop(0)

        if self._input.LA(1) == Token.EOF and self._indents:
            self._pending_tokens = [token for token in self._pending_tokens if token.type != Token.EOF]
            self._emit_token(self._common_token(self.NEWLINE, "\\n"))
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
            return self._pending_tokens.pop(0)
        return next_token

    def atStartOfInput(self) -> bool:
        return self.column == 0 and self.line == 1

    def onNewLine(self) -> None:
        new_line = re.sub(r"[^\\r\\n\\f]+", "", self.text)
        spaces = re.sub(r"[\\r\\n\\f]+", "", self.text)
        next_char = self._input.LA(1)
        previous_was_layout = self._last_token is None or self._last_token.type in {
            self.NEWLINE,
            self.INDENT,
            self.DEDENT,
        }

        if self._opened > 0 or (next_char in (10, 13, 35) and previous_was_layout):
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
            if char == "\\t":
                count += 8 - (count % 8)
            else:
                count += 1
        return count
''',
        encoding="utf-8",
    )
    (OUTPUT_DIR / "Python3ParserBase.py").write_text(
        '''"""Base class for Python3Parser."""

from antlr4.Parser import Parser


class Python3ParserBase(Parser):
    """Base class for Python3 parser."""

    def CannotBePlusMinus(self) -> bool:
        next_token = self._input.LT(1)
        return getattr(next_token, "text", None) not in {"+", "-"}

    def CannotBeDotLpEq(self) -> bool:
        next_token = self._input.LT(1)
        return getattr(next_token, "text", None) not in {".", "(", "="}
''',
        encoding="utf-8",
    )

    _patch_generated_parser()


def _patch_generated_parser() -> None:
    """Patch Java 'this' references to Python 'self'."""
    # Patch parser
    parser_path = OUTPUT_DIR / "Python3Parser.py"
    content = parser_path.read_text(encoding="utf-8")
    content = content.replace("this.", "self.")
    content = content.replace(" this.", " self.")
    parser_path.write_text(content, encoding="utf-8")

    # Patch lexer
    lexer_path = OUTPUT_DIR / "Python3Lexer.py"
    content = lexer_path.read_text(encoding="utf-8")
    content = content.replace("this.", "self.")
    content = content.replace(" this.", " self.")
    lexer_path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
