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


if __name__ == "__main__":
    main()
