import json
import subprocess
from pathlib import Path

from pya.application.analysis import AnalyzeFileCommand, SemanticAnalysisService
from pya.infrastructure.analysis.ast_semantic_analyzer import AstPythonSemanticAnalyzer
from pya.infrastructure.antlr.parser_adapter import AntlrPythonSyntaxParser
from pya.infrastructure.filesystem.source_repository import FileSystemSourceRepository


ROOT = Path(__file__).resolve().parent.parent


def _build_service() -> SemanticAnalysisService:
    return SemanticAnalysisService(
        source_repository=FileSystemSourceRepository(),
        analyzer=AstPythonSemanticAnalyzer(),
        parser=AntlrPythonSyntaxParser(),
    )


def test_analysis_service_extracts_symbols_references_and_semantics() -> None:
    service = _build_service()
    document = service.analyze_file(
        AnalyzeFileCommand(path=str(ROOT / "tests" / "fixtures" / "valid.py"))
    )

    assert document.symbol_count >= 4
    assert document.payload["parse_status"] in {"succeeded", "succeeded_with_diagnostics"}
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
    assert payload["parse_status"] == "succeeded_with_diagnostics"
    assert payload["grammar_version"]
    assert payload["parse_statistics"]["diagnostic_count"] >= 1
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


def test_analysis_dir_resolves_package_reexports_and_prefers_local_calls(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text(
        "from pkg.helpers import exported_summary\n",
        encoding="utf-8",
    )
    (pkg_dir / "helpers.py").write_text(
        "\n".join(
            [
                "def exported_summary(value: str) -> str:",
                '    return f"pkg:{value}"',
                "",
                "def shared() -> str:",
                '    return "pkg-shared"',
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "other.py").write_text(
        "\n".join(
            [
                "def shared() -> str:",
                '    return "other-shared"',
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "consumer.py").write_text(
        "\n".join(
            [
                "from pkg import exported_summary",
                "",
                "def shared() -> str:",
                '    return "local-shared"',
                "",
                "def run() -> str:",
                '    return exported_summary(shared())',
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "analyze-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    bundle_references = payload["bundle_references"]
    relationships = {reference["relationship"] for reference in bundle_references}
    assert "calls_import" in relationships
    assert "calls_local" in relationships
    target_ids = {reference["target_id"] for reference in bundle_references}
    assert any("pkg/helpers.py::function::exported_summary" in target for target in target_ids)
    assert any("consumer.py::function::shared" in target for target in target_ids)


def test_analysis_dir_skips_ambiguous_global_call_resolution(tmp_path: Path) -> None:
    (tmp_path / "alpha.py").write_text(
        "\n".join(
            [
                "def ping() -> str:",
                '    return "alpha"',
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "beta.py").write_text(
        "\n".join(
            [
                "def ping() -> str:",
                '    return "beta"',
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "consumer.py").write_text(
        "\n".join(
            [
                "def call_ping() -> str:",
                "    return ping()",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "analyze-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    call_ping_refs = [
        reference
        for reference in payload["bundle_references"]
        if "consumer.py::function::call_ping" in reference["source_id"]
    ]
    assert not any(reference["relationship"] == "calls_resolved" for reference in call_ping_refs)


def test_analysis_dir_resolves_relative_imports_across_package_modules(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "helpers.py").write_text(
        "\n".join(
            [
                "def relative_summary(value: str) -> str:",
                '    return f"rel:{value}"',
            ]
        ),
        encoding="utf-8",
    )
    (pkg_dir / "consumer.py").write_text(
        "\n".join(
            [
                "from .helpers import relative_summary",
                "",
                "def run() -> str:",
                '    return relative_summary("ok")',
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "analyze-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    target_ids = {reference["target_id"] for reference in payload["bundle_references"]}
    relationships = {reference["relationship"] for reference in payload["bundle_references"]}
    assert any("pkg/helpers.py::function::relative_summary" in target for target in target_ids)
    assert "imports_local" in relationships
    assert "calls_import" in relationships


def test_analysis_dir_resolves_star_imports_when_unambiguous(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "helpers.py").write_text(
        "\n".join(
            [
                "def exported_via_star() -> str:",
                '    return "star"',
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "consumer.py").write_text(
        "\n".join(
            [
                "from pkg.helpers import *",
                "",
                "def run() -> str:",
                "    return exported_via_star()",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "analyze-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    star_refs = [
        reference
        for reference in payload["bundle_references"]
        if reference["relationship"] == "calls_import_star"
    ]
    assert len(star_refs) == 1
    assert "pkg/helpers.py::function::exported_via_star" in star_refs[0]["target_id"]


def test_analysis_dir_respects___all___for_star_import_resolution(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "helpers.py").write_text(
        "\n".join(
            [
                '__all__ = ["public_api"]',
                "",
                "def public_api() -> str:",
                '    return "public"',
                "",
                "def hidden_api() -> str:",
                '    return "hidden"',
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "consumer.py").write_text(
        "\n".join(
            [
                "from pkg.helpers import *",
                "",
                "def run() -> str:",
                "    return public_api()",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "analyze-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    star_refs = [
        reference
        for reference in payload["bundle_references"]
        if reference["relationship"] == "calls_import_star"
    ]
    assert len(star_refs) == 1
    assert "pkg/helpers.py::function::public_api" in star_refs[0]["target_id"]


def test_analysis_dir_does_not_resolve_star_import_name_outside___all__(tmp_path: Path) -> None:
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "helpers.py").write_text(
        "\n".join(
            [
                '__all__ = ["public_api"]',
                "",
                "def public_api() -> str:",
                '    return "public"',
                "",
                "def hidden_api() -> str:",
                '    return "hidden"',
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "consumer.py").write_text(
        "\n".join(
            [
                "from pkg.helpers import *",
                "",
                "def run() -> str:",
                "    return hidden_api()",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "analyze-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    run_refs = [
        reference
        for reference in payload["bundle_references"]
        if "consumer.py::function::run" in reference["source_id"]
    ]
    assert not any(reference["relationship"] == "calls_import_star" for reference in run_refs)


def test_analysis_file_uses_return_annotations_for_local_call_inference(tmp_path: Path) -> None:
    source_path = tmp_path / "typed_calls.py"
    source_path.write_text(
        "\n".join(
            [
                "def make_label() -> str:",
                '    return "label"',
                "",
                "def run() -> str:",
                "    return make_label()",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "analyze-file",
            str(source_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    functions = {function["qualified_name"]: function for function in payload["functions"]}
    assert functions["make_label"]["inferred_return_type"] == "str"
    assert functions["run"]["inferred_return_type"] == "str"


def test_analysis_file_propagates_local_call_chain_return_types(tmp_path: Path) -> None:
    source_path = tmp_path / "chained_calls.py"
    source_path.write_text(
        "\n".join(
            [
                "def leaf() -> int:",
                "    return 7",
                "",
                "def middle():",
                "    return leaf()",
                "",
                "def top():",
                "    return middle()",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "analyze-file",
            str(source_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    functions = {function["qualified_name"]: function for function in payload["functions"]}
    assert functions["leaf"]["inferred_return_type"] == "int"
    assert functions["middle"]["inferred_return_type"] == "int"
    assert functions["top"]["inferred_return_type"] == "int"
