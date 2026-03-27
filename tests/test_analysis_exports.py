import json
import subprocess
from pathlib import Path

from pya.application.analysis import AnalyzeFileCommand, SemanticAnalysisService
from pya.infrastructure.analysis.ast_semantic_analyzer import AstPythonSemanticAnalyzer
from pya.infrastructure.filesystem.source_repository import FileSystemSourceRepository


ROOT = Path(__file__).resolve().parent.parent


def _build_service() -> SemanticAnalysisService:
    return SemanticAnalysisService(
        source_repository=FileSystemSourceRepository(),
        analyzer=AstPythonSemanticAnalyzer(),
    )


def test_analysis_service_extracts_symbols_references_and_semantics() -> None:
    service = _build_service()
    document = service.analyze_file(
        AnalyzeFileCommand(path=str(ROOT / "tests" / "fixtures" / "valid.py"))
    )

    assert document.symbol_count >= 4
    assert any(symbol["kind"] == "decorator" for symbol in document.payload["symbols"])
    assert any(reference["relationship"] == "decorates" for reference in document.payload["references"])
    assert any(function["qualified_name"] == "greet" for function in document.payload["functions"])


def test_analysis_cli_supports_cytoscape_adapter() -> None:
    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "analyze-file",
            str(ROOT / "tests" / "fixtures" / "valid.py"),
            "--adapter",
            "cytoscape",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "nodes" in payload
    assert "edges" in payload


def test_analysis_cli_supports_graphviz_adapter() -> None:
    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "analyze-file",
            str(ROOT / "tests" / "fixtures" / "valid.py"),
            "--adapter",
            "graphviz-dot",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.startswith("digraph pya")


def test_analysis_dir_resolves_cross_file_references_and_survives_invalid_files() -> None:
    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "analyze-dir",
            str(ROOT / "tests" / "fixtures"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["failure_count"] == 1
    assert any(document.get("error") for document in payload["documents"])


def test_analysis_file_survives_invalid_file_with_diagnostics() -> None:
    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "analyze-file",
            str(ROOT / "tests" / "fixtures" / "invalid.py"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["diagnostics"]
    assert payload["error"]["kind"] == "syntax_error"


def test_analysis_dir_resolves_local_imports_across_example_files() -> None:
    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "analyze-dir",
            str(ROOT / "examples"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    relationships = {reference["relationship"] for reference in payload["bundle_references"]}
    assert "imports_local" in relationships or "calls_import" in relationships
    target_ids = {reference["target_id"] for reference in payload["bundle_references"]}
    assert any("feature_support.py::function::format_summary" in target for target in target_ids)
    assert any("support_pkg/helpers.py::function::package_summary" in target for target in target_ids)


def test_analysis_file_infers_common_python_types() -> None:
    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "analyze-file",
            str(ROOT / "examples" / "feature_support.py"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    functions = {function["qualified_name"]: function for function in payload["functions"]}
    assert functions["format_summary"]["inferred_return_type"] == "str"
    assert functions["helper_label"]["inferred_return_type"] == "str"
