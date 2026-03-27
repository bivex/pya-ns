"""Adapters for external analysis tools."""

from __future__ import annotations


def to_cytoscape(payload: dict[str, object]) -> dict[str, object]:
    if "documents" in payload:
        documents = payload["documents"]
    else:
        documents = [payload]

    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    for document in documents:
        for symbol in document["symbols"]:
            nodes.append({"data": symbol})
        for reference in document["references"]:
            edges.append(
                {
                    "data": {
                        "id": f'{reference["source_id"]}->{reference["target_id"]}:{reference["relationship"]}',
                        "source": reference["source_id"],
                        "target": reference["target_id"],
                        "relationship": reference["relationship"],
                        "location": reference["location"],
                        "line": reference["line"],
                        "column": reference["column"],
                    }
                }
            )
    for reference in payload.get("bundle_references", []):
        edges.append(
            {
                "data": {
                    "id": f'{reference["source_id"]}->{reference["target_id"]}:{reference["relationship"]}',
                    "source": reference["source_id"],
                    "target": reference["target_id"],
                    "relationship": reference["relationship"],
                    "location": reference["location"],
                    "line": reference["line"],
                    "column": reference["column"],
                }
            }
        )
    return {"nodes": nodes, "edges": edges}


def to_graphviz_dot(payload: dict[str, object]) -> str:
    if "documents" in payload:
        documents = payload["documents"]
    else:
        documents = [payload]

    lines = ["digraph pya {", '  rankdir="LR";', '  node [shape="box"];']
    for document in documents:
        for symbol in document["symbols"]:
            symbol_id = _dot_escape(symbol["symbol_id"])
            label = _dot_escape(f'{symbol["kind"]}: {symbol["name"]}')
            lines.append(f'  "{symbol_id}" [label="{label}"];')
        for reference in document["references"]:
            source_id = _dot_escape(reference["source_id"])
            target_id = _dot_escape(reference["target_id"])
            relationship = _dot_escape(reference["relationship"])
            lines.append(f'  "{source_id}" -> "{target_id}" [label="{relationship}"];')
    for reference in payload.get("bundle_references", []):
        source_id = _dot_escape(reference["source_id"])
        target_id = _dot_escape(reference["target_id"])
        relationship = _dot_escape(reference["relationship"])
        lines.append(f'  "{source_id}" -> "{target_id}" [label="{relationship}"];')
    lines.append("}")
    return "\n".join(lines)


def _dot_escape(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')
