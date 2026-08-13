#!/usr/bin/env python
"""Run ``final_mvp_demo.ipynb`` cell by cell and print a presentation transcript.

Usage:
    python notebooks/run_demo.py                      # execute every cell, print transcript
    python notebooks/run_demo.py --no-execute         # print existing outputs only
    python notebooks/run_demo.py --condensed          # print key fields only (Step 4/7)
    python notebooks/run_demo.py --inplace            # also write executed notebook back
    python notebooks/run_demo.py --save-transcript /tmp/demo.txt
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re

import nbformat
from nbclient import NotebookClient


ROOT = pathlib.Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "final_mvp_demo.ipynb"
SNAPSHOTS = (
    ROOT / "outputs" / "snapshot_2026-05-29" / "mvp_run.json",
    ROOT / "outputs" / "snapshot_2026-06-30" / "mvp_run.json",
)


def _text(value: object) -> str:
    if isinstance(value, list):
        return "".join(str(item) for item in value)
    return str(value or "")


def cell_outputs(cell: nbformat.notebooknode.NotebookNode) -> str:
    blocks: list[str] = []
    for out in cell.get("outputs", []):
        if out.get("output_type") == "stream":
            text = str(out.get("text", "")).rstrip()
            if text:
                blocks.append(text)
        elif out.get("output_type") in ("execute_result", "display_data"):
            data = out.get("data", {})
            text = (
                _text(data.get("text/markdown"))
                or _text(data.get("text/plain"))
                or _text(data.get("text/html"))
            ).strip()
            if text:
                blocks.append(text)
    return "\n\n".join(blocks)


def _evidence_summaries() -> dict[str, str]:
    """Map evidence_id -> short 'headline — source' from saved MVP snapshots."""

    summaries: dict[str, str] = {}
    for path in SNAPSHOTS:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items = (payload.get("deterministic_input") or {}).get(
            "retrieved_evidence", []
        )
        for item in items:
            evidence_id = str(item.get("evidence_id") or "").strip()
            headline = str(item.get("headline_or_summary") or "").strip()
            source = str(item.get("source") or "").strip()
            if evidence_id:
                summaries[evidence_id] = (
                    f"{headline} — {source}" if headline and source else headline or source
                )
    return summaries


def _grab(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.S)
    return match.group(1).strip() if match else ""


def _bullet_items(block: str) -> list[str]:
    items = []
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("- "):
            items.append(line[2:].strip())
    return items


def _condense_step4(output: str, summaries: dict[str, str]) -> str:
    narrative = _grab(r"\*\*Narrative state:\*\*\s*(.*?)\n\n", output)
    contra_ids = [
        item.strip()
        for item in _grab(
            r"\*\*Contradicting evidence IDs:\*\*\s*(.*?)(?=\n\*\*|\n\n\*\*)", output
        ).split(",")
        if item.strip() and item.strip() != "—"
    ]
    support_ids = [
        item.strip()
        for item in _grab(
            r"\*\*Supporting evidence IDs:\*\*\s*(.*?)(?=\n\*\*|\n\n\*\*)", output
        ).split(",")
        if item.strip() and item.strip() != "—"
    ]
    missing = _bullet_items(
        _grab(
            r"\*\*Missing / uncertain evidence:\*\*\n\n(.*?)\n\n\*\*Monitoring",
            output,
        )
    )
    monitoring = _bullet_items(
        _grab(
            r"\*\*Monitoring questions:\*\*\n\n(.*?)\n\n\*\*Invalidation",
            output,
        )
    )
    invalidation = _bullet_items(
        _grab(
            r"\*\*Invalidation conditions:\*\*\n\n(.*?)\n\n\*Evidence quality:\*",
            output,
        )
    )
    quality = _grab(
        r"\*Evidence quality:\*\s*`(.*?)`\s*·\s*\*Version:\*\s*`(.*?)`", output
    )

    def id_line(evidence_id: str) -> str:
        summary = summaries.get(evidence_id)
        return f"- `{evidence_id}` — {summary}" if summary else f"- `{evidence_id}`"

    contra_block = "\n".join(id_line(item) for item in contra_ids) or "_None_"
    support_block = "\n".join(id_line(item) for item in support_ids) or "_None_"
    missing_block = "\n".join(f"- {item}" for item in missing[:2]) or "_None_"
    monitor_block = "\n".join(f"- {item}" for item in monitoring) or "_None_"
    invalid_block = "\n".join(f"- {item}" for item in invalidation) or "_None_"

    return (
        f"### AI evidence layer — live DeepSeek (condensed)\n\n"
        f"**Read:** {narrative}\n\n"
        f"**Key counter-evidence ({len(contra_ids)}):**\n\n{contra_block}\n\n"
        f"**Key missing:**\n\n{missing_block}\n\n"
        "<details><summary>Supporting · Monitoring · Invalidation · Quality</summary>\n\n"
        f"**Supporting:**\n\n{support_block}\n\n"
        f"**Monitoring questions:**\n\n{monitor_block}\n\n"
        f"**Invalidation conditions:**\n\n{invalid_block}\n\n"
        f"**Evidence quality:** {quality}\n\n</details>"
    )


def _condense_gdelt(output: str) -> str:
    labels = ("2026-05-29", "2026-06-30")
    blocks: list[str] = []
    for index, label in enumerate(labels):
        marker = f"**GDELT news read — {label}**"
        start = output.find(marker)
        if start < 0:
            continue
        if index + 1 < len(labels):
            end = output.find(f"**GDELT news read — {labels[index + 1]}**")
        else:
            end = -1
        if end < 0:
            block = output[start:]
        else:
            block = output[start:end]

        triggers = _grab(r"Triggers:\s*(.*?)\n", block)
        trigger_summary = _grab(
            r"\*\*Trigger summary:\*\*\s*(.*?)\n\n\*\*Recent narrative:\*\*", block
        )
        pm_takeaway = _grab(
            r"\*\*PM takeaway:\*\*\s*(.*?)\n\n\*\*Evidence used:\*\*", block
        )
        recent = _grab(
            r"\*\*Recent narrative:\*\*\s*(.*?)\n\n\*\*Momentum mechanism:\*\*", block
        )
        mechanism = _grab(
            r"\*\*Momentum mechanism:\*\*\s*(.*?)\n\n\*\*Limitations:\*\*", block
        )
        limitations = _grab(
            r"\*\*Limitations:\*\*\s*(.*?)\n\n\*\*PM takeaway:\*\*", block
        )
        evidence_items = _bullet_items(
            _grab(r"\*\*Evidence used:\*\*\n\n(.*?)$", block)
        )
        top = "\n".join(f"- {item}" for item in evidence_items[:4]) or "_None_"
        all_evidence = "\n".join(f"- {item}" for item in evidence_items) or "_None_"
        blocks.append(
            f"**GDELT — {label}** (condensed)\n\n"
            f"**Triggers:** {triggers}\n\n"
            f"**Read:** {trigger_summary}\n\n"
            f"**PM takeaway:** {pm_takeaway}\n\n"
            f"**Top evidence:**\n\n{top}\n\n"
            "<details><summary>Recent narrative · Mechanism · Limitations · All evidence</summary>\n\n"
            f"**Recent narrative:** {recent}\n\n"
            f"**Momentum mechanism:** {mechanism}\n\n"
            f"**Limitations:** {limitations}\n\n"
            f"**All evidence:**\n\n{all_evidence}\n\n</details>"
        )
    return "\n\n".join(blocks)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-execute",
        action="store_true",
        help="print existing notebook outputs without re-running cells",
    )
    parser.add_argument(
        "--inplace",
        action="store_true",
        help="write the executed notebook back to disk",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=4000,
        help="truncate each cell output to this many characters",
    )
    parser.add_argument(
        "--condensed",
        action="store_true",
        help="print condensed key fields for Step 4 and Step 7",
    )
    parser.add_argument(
        "--save-transcript",
        type=pathlib.Path,
        default=None,
        help="write the printed transcript to this file",
    )
    args = parser.parse_args()

    nb = nbformat.read(NOTEBOOK, as_version=4)
    if not args.no_execute:
        client = NotebookClient(
            nb,
            timeout=1200,
            kernel_name="python3",
            resources={"metadata": {"path": str(NOTEBOOK.parent)}},
        )
        client.execute()
        if args.inplace:
            nbformat.write(nb, NOTEBOOK)

    summaries = _evidence_summaries() if args.condensed else {}
    sections: list[str] = []
    for cell in nb.cells:
        if cell.cell_type == "markdown":
            source = cell.source.strip()
            if source:
                sections.append("\n" + "=" * 72 + "\n" + source)
            continue
        output = cell_outputs(cell).strip()
        if not output:
            continue
        if args.condensed and "condensed" not in output:
            if "render_ai_evidence(evidence" in cell.source:
                output = _condense_step4(output, summaries)
            elif "render_gdelt_read(label, payload, message)" in cell.source:
                output = _condense_gdelt(output)
        if args.max_chars and len(output) > args.max_chars:
            output = output[: args.max_chars] + (
                f"\n...[truncated at {args.max_chars} chars]"
            )
        sections.append("\n" + "-" * 72 + "\n" + output)

    transcript = "\n".join(sections)
    print(transcript)
    if args.save_transcript is not None:
        args.save_transcript.write_text(transcript, encoding="utf-8")
        print(f"\n[saved transcript to {args.save_transcript}]")


if __name__ == "__main__":
    main()
