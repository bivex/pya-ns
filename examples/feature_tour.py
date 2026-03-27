"""Feature tour for the capabilities currently supported by Pya."""

from __future__ import annotations

import feature_support as support_tools
from dataclasses import dataclass
from pathlib import Path

from feature_support import format_summary as summarize_workspace
from support_pkg.helpers import package_summary as summarize_package


APP_NAME = "pya-feature-tour"
DEFAULT_RETRIES = 3


def traced(label: str):
    def decorate(func):
        def wrapper(*args, **kwargs):
            print(f"[{label}] start")
            return func(*args, **kwargs)

        return wrapper

    return decorate


def audit(event_name: str):
    def decorate(func):
        def wrapper(*args, **kwargs):
            print(f"audit:{event_name}")
            return func(*args, **kwargs)

        return wrapper

    return decorate


@dataclass
class TourConfig:
    root: Path
    retries: int = DEFAULT_RETRIES
    include_hidden: bool = False

    @property
    def workspace_name(self) -> str:
        match self.root.name:
            case ".git" | ".venv" | ".cache":
                return "hidden-workspace"
            case "":
                return "filesystem-root"
            case _:
                return self.root.name

    def report_path(self) -> Path:
        return self.root / "feature-tour-report.txt"


@audit("scan")
@traced("scan")
def scan_workspace(config: TourConfig) -> list[str]:
    discovered: list[str] = []

    for path in sorted(config.root.iterdir()):
        if path.name.startswith(".") and not config.include_hidden:
            continue
        elif path.is_dir():
            discovered.append(f"dir:{path.name}")
        else:
            discovered.append(f"file:{path.name}")

    return discovered


def classify_entry(entry: str) -> str:
    match entry.split(":", 1):
        case ["dir", _]:
            return "directory"
        case ["file", _] if entry.endswith(".py"):
            return "python-file"
        case ["file", _] if entry.endswith(".md"):
            return "markdown-file"
        case ["file", _]:
            return "other-file"
        case _:
            return "unknown"


def build_report(config: TourConfig) -> dict[str, int]:
    stats = {
        "directories": 0,
        "python_files": 0,
        "markdown_files": 0,
        "other_files": 0,
        "errors": 0,
    }

    try:
        entries = scan_workspace(config)
    except OSError:
        stats["errors"] += 1
        return stats

    for entry in entries:
        kind = classify_entry(entry)
        if kind == "directory":
            stats["directories"] += 1
        elif kind == "python-file":
            stats["python_files"] += 1
        elif kind == "markdown-file":
            stats["markdown_files"] += 1
        else:
            stats["other_files"] += 1

    return stats


def persist_report(config: TourConfig, report: dict[str, int]) -> str:
    output_path = config.report_path()

    with output_path.open("w", encoding="utf-8") as handle:
        for key, value in report.items():
            handle.write(f"{key}={value}\n")

    return str(output_path)


def resilient_summary(config: TourConfig) -> str:
    attempt = 0

    while attempt <= config.retries:
        try:
            report = build_report(config)
            output_path = persist_report(config, report)
            return f"saved:{output_path}"
        except PermissionError:
            attempt += 1

    return "saved:unavailable"


async def collect_async_entries(config: TourConfig) -> list[str]:
    entries = scan_workspace(config)
    await mark_async_boundary(config.workspace_name)
    return entries


async def mark_async_boundary(label: str) -> None:
    print(f"async:{label}")


def imported_status_banner(config: TourConfig):
    return summarize_workspace(config.workspace_name, support_tools.helper_label("tour"))


def packaged_status_banner(config: TourConfig):
    return summarize_package(imported_status_banner(config))


def evaluate_workspace(config: TourConfig) -> str:
    match config.workspace_name:
        case "hidden-workspace":
            return summarize_workspace(config.workspace_name, support_tools.helper_label("hidden"))
        case "filesystem-root":
            return summarize_workspace(config.workspace_name, support_tools.package_badge("root"))
        case _:
            base = summarize_workspace(config.workspace_name, resilient_summary(config))
            return summarize_package(base)


def feature_tour(root: Path) -> str:
    config = TourConfig(root=root, retries=DEFAULT_RETRIES)
    return evaluate_workspace(config)
