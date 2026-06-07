from __future__ import annotations

import json
from pathlib import Path


def export_markdown_corpus(output_dir: Path, format_name: str = "jsonl") -> Path:
    if format_name != "jsonl":
        raise ValueError("Only jsonl export is supported.")
    records = []
    for path in sorted(output_dir.glob("*.md")):
        records.append(json.dumps({"path": str(path), "content": path.read_text(encoding="utf-8")}))
    corpus_path = output_dir / "corpus.jsonl"
    corpus_path.write_text("\n".join(records) + ("\n" if records else ""), encoding="utf-8")
    return corpus_path
