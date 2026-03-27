import json
import subprocess
import sys
from pathlib import Path

from pya.application.dto import ParseDirectoryCommand, ParseFileCommand
from pya.application.use_cases import ParsingJobService
from pya.infrastructure.antlr.parser_adapter import AntlrPythonSyntaxParser
from pya.infrastructure.filesystem.source_repository import FileSystemSourceRepository
from pya.infrastructure.system import (
    InMemoryParsingJobRepository,
    StructuredLoggingEventPublisher,
    SystemClock,
)


ROOT = Path(__file__).resolve().parent.parent


def _ensure_generated_parser() -> None:
    generated_parser = (
        ROOT / "src" / "pya" / "infrastructure" / "antlr" / "generated" / "python3" / "Python3Parser.py"
    )
    if generated_parser.exists():
        return
    subprocess.run(
        [sys.executable, "scripts/generate_python_parser.py"],
        cwd=ROOT,
        check=True,
    )


def _build_service() -> ParsingJobService:
    _ensure_generated_parser()
    return ParsingJobService(
        source_repository=FileSystemSourceRepository(),
        parser=AntlrPythonSyntaxParser(),
        event_publisher=StructuredLoggingEventPublisher(),
        clock=SystemClock(),
        job_repository=InMemoryParsingJobRepository(),
    )


def test_parse_file_extracts_structure() -> None:
    service = _build_service()
    report = service.parse_file(ParseFileCommand(path=str(ROOT / "tests" / "fixtures" / "valid.py")))

    assert report.summary.source_count == 1
    assert report.summary.technical_failure_count == 0
    assert report.sources[0].status in {"succeeded", "succeeded_with_diagnostics"}
    assert {element.kind for element in report.sources[0].structural_elements} >= {
        "import",
        "class",
        "function",
        "decorator",
        "variable",
    }
    assert any(element.name == "APP_NAME" for element in report.sources[0].structural_elements)


def test_parse_directory_returns_report_for_all_files() -> None:
    service = _build_service()
    report = service.parse_directory(ParseDirectoryCommand(root_path=str(ROOT / "tests" / "fixtures")))

    assert report.summary.source_count == 3
    assert len(report.sources) == 3


def test_parse_file_handles_class_declaration(tmp_path: Path) -> None:
    service = _build_service()
    source_path = tmp_path / "class_parse.py"
    source_path.write_text(
        """
class Mode:
    def title(self) -> str:
        return "active"
""".strip(),
        encoding="utf-8",
    )

    report = service.parse_file(ParseFileCommand(path=str(source_path)))

    assert report.summary.source_count == 1
    assert report.summary.technical_failure_count == 0
    assert {element.kind for element in report.sources[0].structural_elements} >= {"class", "function"}


def test_cli_outputs_json() -> None:
    _ensure_generated_parser()
    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "parse-file",
            str(ROOT / "tests" / "fixtures" / "valid.py"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["summary"]["source_count"] == 1


def test_parse_file_cache_writes_content_addressed_entry(tmp_path: Path) -> None:
    _ensure_generated_parser()
    cache_dir = tmp_path / "cache"
    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "parse-file",
            str(ROOT / "tests" / "fixtures" / "valid.py"),
            "--cache-dir",
            str(cache_dir),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert any(cache_dir.glob("*.json"))


def test_parse_file_supports_match_case_via_structure_fallback() -> None:
    _ensure_generated_parser()
    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "parse-file",
            str(ROOT / "examples" / "feature_tour.py"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["summary"]["technical_failure_count"] == 0
    assert any(
        element["kind"] == "decorator"
        for element in payload["sources"][0]["structural_elements"]
    )
