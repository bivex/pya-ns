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
