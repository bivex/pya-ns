"""Additional control-flow diagram export formats."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from html import escape
from pathlib import Path

from pya.domain.control_flow import (
    ActionFlowStep,
    ControlFlowDiagram,
    ControlFlowStep,
    DoCatchFlowStep,
    ForInFlowStep,
    IfFlowStep,
    SwitchFlowStep,
    WhileFlowStep,
    WithFlowStep,
)
from pya.domain.errors import ExportError


class DiagramExporter:
    def render_mermaid(self, diagram: ControlFlowDiagram) -> str:
        lines = ["flowchart TD"]
        counter = 0
        for function in diagram.functions:
            fn_id = f"fn_{counter}"
            counter += 1
            lines.append(f'  subgraph {fn_id}["{_mermaid_escape(function.qualified_name)}"]')
            previous_id: str | None = None
            for step in function.steps:
                previous_id, counter = _render_mermaid_step(lines, step, previous_id, counter)
            if previous_id is None:
                empty_id = f"node_{counter}"
                counter += 1
                lines.append(f'    {empty_id}["No structured steps"]')
            lines.append("  end")
        if len(lines) == 1:
            lines.append('  empty["No functions found"]')
        return "\n".join(lines) + "\n"

    def render_svg(self, diagram: ControlFlowDiagram) -> str:
        rows = []
        for function in diagram.functions:
            rows.append(f"<tspan x='24' dy='28'>Function: {escape(function.qualified_name)}</tspan>")
            for line in _flatten_steps(function.steps, indent=1):
                rows.append(f"<tspan x='24' dy='22'>{escape(line)}</tspan>")
            rows.append("<tspan x='24' dy='28'></tspan>")
        if not rows:
            rows.append("<tspan x='24' dy='28'>No functions found</tspan>")
        height = max(220, 60 + len(rows) * 24)
        return (
            f"<svg xmlns='http://www.w3.org/2000/svg' width='1280' height='{height}' viewBox='0 0 1280 {height}'>"
            "<rect width='100%' height='100%' fill='#0b1220'/>"
            "<rect x='16' y='16' width='1248' height='"
            f"{height - 32}"
            "' rx='14' fill='#111827' stroke='#3f5378'/>"
            f"<text x='24' y='36' fill='#cfd8f6' font-size='16' font-family='JetBrains Mono, monospace'>"
            f"{escape(diagram.source_location)}</text>"
            "<text x='24' y='64' fill='#82aaff' font-size='14' font-family='JetBrains Mono, monospace'>"
            + "".join(rows)
            + "</text></svg>"
        )

    def render_png(self, diagram: ControlFlowDiagram) -> bytes:
        svg = self.render_svg(diagram)
        with tempfile.TemporaryDirectory(prefix="pya-svg-") as temp_dir:
            temp_path = Path(temp_dir)
            svg_path = temp_path / "diagram.svg"
            png_path = temp_path / "diagram.png"
            svg_path.write_text(svg, encoding="utf-8")

            converters = (
                ["magick", str(svg_path), str(png_path)],
                ["convert", str(svg_path), str(png_path)],
                ["rsvg-convert", "-o", str(png_path), str(svg_path)],
                ["sips", "-s", "format", "png", str(svg_path), "--out", str(png_path)],
            )
            for command in converters:
                if shutil.which(command[0]) is None:
                    continue
                result = subprocess.run(command, capture_output=True, text=True, check=False)
                if result.returncode == 0 and png_path.exists():
                    return png_path.read_bytes()

        raise ExportError(
            "PNG export requires an SVG rasterizer such as ImageMagick (`magick`), "
            "`rsvg-convert`, or macOS `sips`."
        )


def _render_mermaid_step(
    lines: list[str],
    step: ControlFlowStep,
    previous_id: str | None,
    counter: int,
) -> tuple[str, int]:
    node_id = f"node_{counter}"
    counter += 1

    if isinstance(step, ActionFlowStep):
        lines.append(f'    {node_id}["{_mermaid_escape(step.label)}"]')
    elif isinstance(step, IfFlowStep):
        lines.append(f'    {node_id}{{"{_mermaid_escape(step.condition)}"}}')
        then_prev = node_id
        for child in step.then_steps:
            then_prev, counter = _render_mermaid_step(lines, child, then_prev, counter)
        else_prev = node_id
        for child in step.else_steps:
            else_prev, counter = _render_mermaid_step(lines, child, else_prev, counter)
    elif isinstance(step, WhileFlowStep):
        lines.append(f'    {node_id}{{"while {_mermaid_escape(step.condition)}"}}')
        branch_prev = node_id
        for child in step.body_steps:
            branch_prev, counter = _render_mermaid_step(lines, child, branch_prev, counter)
        lines.append(f"    {branch_prev} --> {node_id}")
    elif isinstance(step, ForInFlowStep):
        lines.append(f'    {node_id}{{"for {_mermaid_escape(step.header)}"}}')
        branch_prev = node_id
        for child in step.body_steps:
            branch_prev, counter = _render_mermaid_step(lines, child, branch_prev, counter)
        lines.append(f"    {branch_prev} --> {node_id}")
    elif isinstance(step, WithFlowStep):
        lines.append(f'    {node_id}["{_mermaid_escape(step.header)}"]')
        branch_prev = node_id
        for child in step.body_steps:
            branch_prev, counter = _render_mermaid_step(lines, child, branch_prev, counter)
    elif isinstance(step, SwitchFlowStep):
        lines.append(f'    {node_id}{{"match {_mermaid_escape(step.expression)}"}}')
        for case in step.cases:
            case_id = f"node_{counter}"
            counter += 1
            lines.append(f'    {case_id}["{_mermaid_escape(case.label)}"]')
            lines.append(f"    {node_id} --> {case_id}")
            case_prev = case_id
            for child in case.steps:
                case_prev, counter = _render_mermaid_step(lines, child, case_prev, counter)
    elif isinstance(step, DoCatchFlowStep):
        lines.append(f'    {node_id}["try"]')
        branch_prev = node_id
        for child in step.body_steps:
            branch_prev, counter = _render_mermaid_step(lines, child, branch_prev, counter)
        for catch in step.catches:
            catch_id = f"node_{counter}"
            counter += 1
            lines.append(f'    {catch_id}["catch {_mermaid_escape(catch.pattern)}"]')
            lines.append(f"    {node_id} --> {catch_id}")
            catch_prev = catch_id
            for child in catch.steps:
                catch_prev, counter = _render_mermaid_step(lines, child, catch_prev, counter)
    else:
        raise TypeError(f"unsupported step type: {type(step)!r}")

    if previous_id is not None:
        lines.append(f"    {previous_id} --> {node_id}")
    return node_id, counter


def _flatten_steps(steps: tuple[ControlFlowStep, ...], *, indent: int) -> list[str]:
    lines: list[str] = []
    prefix = "  " * indent
    for step in steps:
        if isinstance(step, ActionFlowStep):
            lines.append(f"{prefix}- {step.label}")
        elif isinstance(step, IfFlowStep):
            lines.append(f"{prefix}- if {step.condition}")
            lines.extend(_flatten_steps(step.then_steps, indent=indent + 1))
            if step.else_steps:
                lines.append(f"{prefix}- else")
                lines.extend(_flatten_steps(step.else_steps, indent=indent + 1))
        elif isinstance(step, WhileFlowStep):
            lines.append(f"{prefix}- while {step.condition}")
            lines.extend(_flatten_steps(step.body_steps, indent=indent + 1))
        elif isinstance(step, ForInFlowStep):
            lines.append(f"{prefix}- for {step.header}")
            lines.extend(_flatten_steps(step.body_steps, indent=indent + 1))
        elif isinstance(step, WithFlowStep):
            lines.append(f"{prefix}- {step.header}")
            lines.extend(_flatten_steps(step.body_steps, indent=indent + 1))
        elif isinstance(step, SwitchFlowStep):
            lines.append(f"{prefix}- match {step.expression}")
            for case in step.cases:
                lines.append(f"{prefix}  - {case.label}")
                lines.extend(_flatten_steps(case.steps, indent=indent + 2))
        elif isinstance(step, DoCatchFlowStep):
            lines.append(f"{prefix}- try")
            lines.extend(_flatten_steps(step.body_steps, indent=indent + 1))
            for catch in step.catches:
                lines.append(f"{prefix}  - catch {catch.pattern}")
                lines.extend(_flatten_steps(catch.steps, indent=indent + 2))
    return lines


def _mermaid_escape(text: str) -> str:
    return text.replace('"', "'")
