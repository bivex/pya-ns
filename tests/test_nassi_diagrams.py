import json
import re
import subprocess
import sys
from pathlib import Path

from pya.application.control_flow import (
    BuildNassiDiagramCommand,
    BuildNassiDirectoryCommand,
    NassiDiagramService,
)
from pya.domain.control_flow import (
    ActionFlowStep,
    ControlFlowDiagram,
    DoCatchFlowStep,
    ForInFlowStep,
    FunctionControlFlow,
    IfFlowStep,
    SwitchFlowStep,
    WhileFlowStep,
)
from pya.domain.model import SourceUnit, SourceUnitId
from pya.infrastructure.antlr.control_flow_extractor import AntlrPythonControlFlowExtractor
from pya.infrastructure.filesystem.source_repository import FileSystemSourceRepository
from pya.infrastructure.rendering.diagram_exporter import DiagramExporter
from pya.infrastructure.rendering.nassi_html_renderer import HtmlNassiDiagramRenderer


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


def _build_service() -> NassiDiagramService:
    _ensure_generated_parser()
    return NassiDiagramService(
        source_repository=FileSystemSourceRepository(),
        extractor=AntlrPythonControlFlowExtractor(),
        renderer=HtmlNassiDiagramRenderer(),
    )


def test_nassi_service_builds_html_document() -> None:
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "control_flow.py"))
    )

    assert document.function_count >= 1
    assert "Pya" in document.html


def test_nassi_service_builds_directory_bundle() -> None:
    service = _build_service()
    bundle = service.build_directory_diagrams(
        BuildNassiDirectoryCommand(root_path=str(ROOT / "tests" / "fixtures"))
    )

    assert bundle.document_count == 3
    assert bundle.root_path == str((ROOT / "tests" / "fixtures").resolve())
    assert any(document.source_location.endswith("control_flow.py") for document in bundle.documents)


def test_nassi_service_handles_class_container(tmp_path: Path) -> None:
    service = _build_service()
    source_path = tmp_path / "class_fixture.py"
    source_path.write_text(
        """
class Direction:
    def score(self):
        return 1
""".strip(),
        encoding="utf-8",
    )

    document = service.build_file_diagram(BuildNassiDiagramCommand(path=str(source_path)))

    assert document.function_count == 1
    assert document.function_names == ("Direction.score",)
    assert "Direction" in document.html


def test_match_case_is_extracted_as_switch_flow() -> None:
    _ensure_generated_parser()
    repository = FileSystemSourceRepository()
    extractor = AntlrPythonControlFlowExtractor()
    diagram = extractor.extract(repository.load_file(str(ROOT / "tests" / "fixtures" / "control_flow.py")))

    match_case_function = next(function for function in diagram.functions if function.name == "match_case")
    assert any(isinstance(step, SwitchFlowStep) for step in match_case_function.steps)


def test_html_diagram_is_interactive() -> None:
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "control_flow.py"))
    )

    assert "<details class=\"function-panel\" open>" in document.html
    assert "Collapse" in document.html
    assert "panel.addEventListener(\"toggle\"" in document.html


def test_mermaid_and_svg_exports_are_available() -> None:
    service = _build_service()
    exporter = DiagramExporter()
    diagram = service.extractor.extract(
        service.source_repository.load_file(str(ROOT / "tests" / "fixtures" / "control_flow.py"))
    )

    mermaid = exporter.render_mermaid(diagram)
    svg = exporter.render_svg(diagram)

    assert mermaid.startswith("flowchart TD")
    assert "match value" in mermaid
    assert svg.startswith("<svg")
    assert "Function: match_case" in svg


def test_loop_else_and_try_else_are_extracted() -> None:
    _ensure_generated_parser()
    repository = FileSystemSourceRepository()
    extractor = AntlrPythonControlFlowExtractor()
    diagram = extractor.extract(repository.load_file(str(ROOT / "tests" / "fixtures" / "control_flow.py")))

    loop_else_function = next(function for function in diagram.functions if function.name == "loop_else")
    assert any(isinstance(step, ForInFlowStep) and step.else_steps for step in loop_else_function.steps)
    assert any(isinstance(step, WhileFlowStep) and step.else_steps for step in loop_else_function.steps)

    try_else_function = next(function for function in diagram.functions if function.name == "try_else")
    try_step = next(step for step in try_else_function.steps if isinstance(step, DoCatchFlowStep))
    assert try_step.else_steps
    assert any(catch.pattern == "except ValueError as exc" for catch in try_step.catches)


def test_renderer_shows_loop_else_and_try_else_sections() -> None:
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "control_flow.py"))
    )

    assert "For value in range(limit)" in document.html
    assert "While total &lt; 0" in document.html
    assert "Catch except ValueError as exc" in document.html
    assert document.html.count(">Else<") >= 2


# ---------------------------------------------------------------------------
# If depth rendering tests
# ---------------------------------------------------------------------------


class TestIfDepthRendering:
    """If-cap rendering with depth-coded badges and colors."""

    def test_depth_badge_zero_is_empty(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        assert renderer._depth_badge(0) == ""

    def test_depth_badges_1_to_10_use_circled_digits(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        assert renderer._depth_badge(1) == " ①"
        assert renderer._depth_badge(5) == " ⑤"
        assert renderer._depth_badge(10) == " ⑩"

    def test_depth_badges_11_to_20_use_second_range(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        assert renderer._depth_badge(11) == " ⑪"
        assert renderer._depth_badge(15) == " ⑮"
        assert renderer._depth_badge(20) == " ⑳"

    def test_depth_badges_21_to_35_use_third_range(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        assert renderer._depth_badge(21) == " ㉑"
        assert renderer._depth_badge(30) == " ㉚"
        assert renderer._depth_badge(35) == " ㉟"

    def test_depth_badges_36_to_50_use_fourth_range(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        assert renderer._depth_badge(36) == " ㊱"
        assert renderer._depth_badge(40) == " ㊵"
        assert renderer._depth_badge(50) == " ㊿"

    def test_depth_css_generates_51_levels(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        css = renderer._depth_css()
        assert ".ns-if-depth-0-triangle" in css
        assert ".ns-if-depth-50-triangle" in css

    def test_depth_css_cycles_colors(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        css = renderer._depth_css()
        assert "var(--blue-dim)" in css
        assert "var(--green-dim)" in css
        assert "var(--purple-dim)" in css
        assert "var(--teal-dim)" in css
        assert "var(--amber-dim)" in css

    def test_depth_css_includes_body_gradients(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        css = renderer._depth_css()
        assert ".ns-if-depth-0-triangle" in css
        assert ".ns-if-depth-0-diagonal" in css

    def test_render_if_cap_at_depth_zero(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        html = renderer._render_if_cap("x > 0", depth=0)
        assert 'class="ns-if-cap ns-if-depth-0"' in html
        assert '<svg class="ns-if-svg"' in html
        assert "x &gt; 0" in html
        assert 'width="400"' in html
        assert 'height="72"' in html

    def test_render_if_cap_at_depth_five(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        html = renderer._render_if_cap("x > 0", depth=5)
        assert 'class="ns-if-cap ns-if-depth-5"' in html
        assert "⑤" in html

    def test_render_if_cap_at_depth_twenty_clips_badge(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        html = renderer._render_if_cap("x > 0", depth=20)
        assert 'class="ns-if-cap ns-if-depth-20"' in html
        assert "⑳" in html

    def test_render_if_cap_at_depth_thirty_five(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        html = renderer._render_if_cap("x > 0", depth=35)
        assert 'class="ns-if-cap ns-if-depth-35"' in html
        assert "㉟" in html

    def test_render_if_cap_at_depth_thirty_six_jumps_unicode(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        html = renderer._render_if_cap("x > 0", depth=36)
        assert 'class="ns-if-cap ns-if-depth-36"' in html
        assert "㊱" in html

    def test_render_if_cap_at_depth_fifty(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        html = renderer._render_if_cap("x > 0", depth=50)
        assert 'class="ns-if-cap ns-if-depth-50"' in html
        assert "㊿" in html

    def test_render_if_cap_clips_at_max_depth(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        html = renderer._render_if_cap("x > 0", depth=100)
        assert 'class="ns-if-cap ns-if-depth-50"' in html
        assert "㊿" in html

    def test_render_if_cap_expands_svg_for_long_conditions(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        html = renderer._render_if_cap(
            "request.user.profile.permissions.can_access_scoped_resource and "
            "request.execution_context.region.is_allowed_for_this_operation",
            depth=2,
        )
        match = re.search(r'viewBox="0 0 (\d+) (\d+)"', html)
        assert match is not None
        width = int(match.group(1))
        height = int(match.group(2))
        assert width > 400
        assert height >= 72

    def test_nested_if_layout_css_can_expand_horizontally_for_deep_branches(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        diagram = ControlFlowDiagram(
            source_location="nested.py",
            functions=(
                FunctionControlFlow(
                    name="process_complex_data",
                    signature="def process_complex_data(data: list) -> Result",
                    container=None,
                    steps=(
                        IfFlowStep(
                            condition="item.is_valid",
                            then_steps=(
                                IfFlowStep(
                                    condition="item.has_priority",
                                    then_steps=(ActionFlowStep("handle_urgent(item)"),),
                                    else_steps=(ActionFlowStep("handle_normal(item)"),),
                                ),
                            ),
                            else_steps=(
                                IfFlowStep(
                                    condition="item.can_recover",
                                    then_steps=(ActionFlowStep("recover(item)"),),
                                    else_steps=(ActionFlowStep("discard(item)"),),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )

        css = renderer.render(diagram).split("<style>", 1)[1].split("</style>", 1)[0]

        assert re.search(
            r"\.viewer \{[^}]*width: max-content;[^}]*min-width: min\(1200px, calc\(100vw - 48px\)\);",
            css,
            re.DOTALL,
        )
        assert re.search(
            r"\.function-body > \.ns-sequence \{[^}]*width: max-content;[^}]*min-width: 100%;",
            css,
            re.DOTALL,
        )
        assert re.search(
            r"\.ns-sequence \{[^}]*width: max-content;[^}]*min-width: 100%;",
            css,
            re.DOTALL,
        )
        assert re.search(
            r"\.ns-branches \{[^}]*grid-template-columns: repeat\(2, max-content\);[^}]*width: max-content;[^}]*min-width: 100%;",
            css,
            re.DOTALL,
        )
        assert "580px" not in css

    def test_if_branches_use_green_and_red_highlight_classes(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        html = renderer._render_step(
            IfFlowStep(
                condition="flag",
                then_steps=(ActionFlowStep("return success"),),
                else_steps=(ActionFlowStep("return failure"),),
            ),
            depth=0,
        )

        assert 'class="ns-branch ns-branch-yes"' in html
        assert 'class="ns-branch ns-branch-no"' in html
        assert "rgba(158, 206, 106" in renderer.render(
            ControlFlowDiagram(
                source_location="branch-colors.py",
                functions=(
                    FunctionControlFlow(
                        name="f",
                        signature="def f()",
                        container=None,
                        steps=(
                            IfFlowStep(
                                condition="flag",
                                then_steps=(ActionFlowStep("return success"),),
                                else_steps=(ActionFlowStep("return failure"),),
                            ),
                        ),
                    ),
                ),
            )
        )
        assert "rgba(247, 118, 142" in renderer.render(
            ControlFlowDiagram(
                source_location="branch-colors.py",
                functions=(
                    FunctionControlFlow(
                        name="f",
                        signature="def f()",
                        container=None,
                        steps=(
                            IfFlowStep(
                                condition="flag",
                                then_steps=(ActionFlowStep("return success"),),
                                else_steps=(ActionFlowStep("return failure"),),
                            ),
                        ),
                    ),
                ),
            )
        )


def test_nassi_cli_writes_html_file(tmp_path: Path) -> None:
    _ensure_generated_parser()
    output_path = tmp_path / "control_flow.html"

    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "nassi-file",
            str(ROOT / "tests" / "fixtures" / "control_flow.py"),
            "--out",
            str(output_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["function_count"] >= 1
    assert payload["output_path"] == str(output_path.resolve())
    assert output_path.exists()
    assert "Nassi-Shneiderman Control Flow" in output_path.read_text(encoding="utf-8")


def test_nassi_dir_cli_writes_html_bundle(tmp_path: Path) -> None:
    _ensure_generated_parser()
    output_dir = tmp_path / "nassi-bundle"

    result = subprocess.run(
        [
            "uv",
            "run",
            "pya",
            "nassi-dir",
            str(ROOT / "tests" / "fixtures"),
            "--out",
            str(output_dir),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["document_count"] == 3
    assert payload["output_dir"] == str(output_dir.resolve())
    assert payload["index_path"] == str((output_dir / "index.html").resolve())
    assert len(payload["documents"]) == 3
    assert (output_dir / "index.html").exists()
    assert "Pya NSD Index" in (output_dir / "index.html").read_text(encoding="utf-8")
