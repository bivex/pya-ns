"""Feature tour for Pya parsing and control-flow visualization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def traced(label: str):
    def decorate(func):
        def wrapper(*args, **kwargs):
            print(f"[{label}] start")
            return func(*args, **kwargs)

        return wrapper

    return decorate


@dataclass
class TourConfig:
    root: Path
    retries: int = 2


@traced("tour")
def scan_workspace(config: TourConfig) -> list[str]:
    discovered: list[str] = []

    for path in sorted(config.root.iterdir()):
        if path.is_dir():
            discovered.append(f"dir:{path.name}")
        else:
            discovered.append(f"file:{path.name}")

    return discovered


def classify_entry(entry: str) -> str:
    match entry.split(":", 1):
        case ["dir", name] if name.startswith("."):
            return "hidden-directory"
        case ["dir", _]:
            return "directory"
        case ["file", name] if name.endswith(".py"):
            return "python-file"
        case ["file", _]:
            return "other-file"
        case _:
            return "unknown"


def build_report(config: TourConfig) -> dict[str, int]:
    stats = {
        "directories": 0,
        "python_files": 0,
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
        else:
            stats["other_files"] += 1

    return stats


def persist_report(config: TourConfig, report: dict[str, int]) -> str:
    output_path = config.root / "feature-tour-report.txt"

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
