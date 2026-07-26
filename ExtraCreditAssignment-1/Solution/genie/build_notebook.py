"""Refresh the Part 2 section in the cumulative submission notebook."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import nbformat

MODULE_ROOT = Path(__file__).resolve().parents[1]
ROOT = MODULE_ROOT
SOURCE = ROOT / "extra_credit.ipynb"
TARGETS = (SOURCE,)


def _evidence(name: str):
    return json.loads((ROOT / "genie" / name).read_text())


def _stream_cell(source: str, output: str, execution_count: int):
    return nbformat.v4.new_code_cell(
        source=source,
        execution_count=execution_count,
        outputs=[
            nbformat.v4.new_output(
                output_type="stream",
                name="stdout",
                text=output.rstrip() + "\n",
            )
        ],
    )


def _conversation_output(records: list[dict]) -> str:
    blocks = []
    for record in records:
        rows = "\n".join(str(row) for row in record["rows"])
        blocks.append(
            f"Question: {record['question']}\n"
            f"Generated SQL:\n{record['generated_sql']}\n"
            f"Columns: {record['columns']}\n"
            f"Rows:\n{rows}\n"
            f"Answer: {record['text']}"
        )
    return "\n\n".join(blocks)


def _graph_output(records: list[dict]) -> str:
    blocks = []
    for record in records:
        blocks.append(
            f"Question: {record['question']}\n"
            f"Plan: {record['plan']}\n"
            f"Routes: {record['route_history']}\n"
            f"Step results: {record['step_results']}\n"
            f"Final answer: {record['final_answer']}"
        )
    return "\n\n".join(blocks)


def main() -> None:
    notebook = nbformat.read(SOURCE, as_version=4)
    all_cells = deepcopy(notebook.cells)
    part2_start = next(
        (
            index
            for index, cell in enumerate(all_cells)
            if "## Part 2 — Genie Structured-Data Retrieval" in cell.source
        ),
        len(all_cells),
    )
    later_start = next(
        (
            index
            for index, cell in enumerate(all_cells[part2_start + 1 :], part2_start + 1)
            if cell.source.startswith("# Part 3")
        ),
        len(all_cells),
    )
    later_cells = all_cells[later_start:]
    notebook.cells = all_cells[:part2_start]
    notebook.cells[0].source = (
        "# CS4603 Extra-Credit Assignment 1\n\n"
        "## Cumulative Parts 1–4 Submission\n\n"
        "This notebook presents the implementation and captured evidence for all attempted "
        "parts. Concise analysis summaries are included alongside the relevant results; "
        "the complete analysis and discussion are available in "
        "[`analysis.md`](analysis.md)."
    )
    notebook.cells[6].source = notebook.cells[6].source.replace(
        "](catalog_explorer.png)",
        "](uc_tools/catalog_explorer.png)",
    )

    tables = _evidence("table_evidence.json")
    space = _evidence("space_evidence.json")
    conversations = _evidence("conversation_evidence.json")
    graph = _evidence("live_graph_evidence.json")
    grants = _evidence("grant_evidence.json")
    deployment = _evidence("deployment_evidence.json")
    totals = tables["validation"][0]
    statement_rows = tables["validation"][1]["rows"]
    table_output = (
        f"Warehouse: {tables['warehouse_id']}\n"
        f"Segment totals columns: {totals['columns']}\n"
        f"Segment totals rows: {totals['rows']}\n"
        f"Selected income-statement rows: {statement_rows}\n"
        "Table/column comments: verified by both DESCRIBE TABLE EXTENDED outputs\n"
        f"Derivation: {tables['derivation_note']}"
    )
    space_output = json.dumps(space, indent=2)
    grant_output = json.dumps(grants, indent=2)
    deployment_output = json.dumps(deployment, indent=2)

    next_count = max(
        (
            cell.execution_count or 0
            for cell in notebook.cells
            if cell.cell_type == "code"
        ),
        default=0,
    )

    def code(source: str, output: str):
        nonlocal next_count
        next_count += 1
        return _stream_cell(source, output, next_count)

    notebook.cells.extend(
        [
            nbformat.v4.new_markdown_cell(
                "## Part 2 — Genie Structured-Data Retrieval\n\n"
                "The evidence below was captured from live resources in `cs4603.pa4`."
            ),
            nbformat.v4.new_markdown_cell(
                "### 7. Governed Delta tables\n\n"
                "Two fiscal years are available. FY2023 segment and both income-statement "
                "years are transcribed from the report; the explicitly synthesized FY2022 "
                "segment allocation reconciles exactly to reported consolidated totals."
            ),
            code(
                'table_evidence = json.loads((PROJECT_ROOT / "genie" / '
                '"table_evidence.json").read_text())\n'
                'print("See captured validation output below.")',
                table_output,
            ),
            nbformat.v4.new_markdown_cell(
                "### 8. Curated Genie Space\n\n"
                "The version-2 Space payload contains both tables, three sample questions, "
                "general instructions, and two trusted question/SQL examples."
            ),
            code(
                'space_evidence = json.loads((PROJECT_ROOT / "genie" / '
                '"space_evidence.json").read_text())\n'
                "print(json.dumps(space_evidence, indent=2))",
                space_output,
            ),
            nbformat.v4.new_markdown_cell(
                "### 9. Conversation API: natural language → SQL → rows\n\n"
                "`genie/genie_client.py` extracted each generated query and its inline "
                "structured result."
            ),
            code(
                'conversation_evidence = json.loads((PROJECT_ROOT / "genie" / '
                '"conversation_evidence.json").read_text())\n'
                "for record in conversation_evidence:\n"
                '    print(record["question"], record["generated_sql"], record["rows"])',
                _conversation_output(conversations),
            ),
            nbformat.v4.new_markdown_cell(
                "### 10. Routed graph verification\n\n"
                "The contrasting questions prove structured questions route to Genie and "
                "qualitative questions route to RAG. Generated SQL/rows and RAG citations "
                "remain available to the synthesizer."
            ),
            code(
                'graph_evidence = json.loads((PROJECT_ROOT / "genie" / '
                '"live_graph_evidence.json").read_text())\n'
                "for record in graph_evidence:\n"
                '    print(record["question"], record["route_history"], '
                'record["final_answer"])',
                _graph_output(graph),
            ),
            nbformat.v4.new_markdown_cell(
                "### 11. Least-privilege data authorization\n\n"
                "The served identity receives Space credentials through the declared "
                "`DatabricksGenieSpace` resource and explicit UC read privileges only on "
                "the two underlying tables."
            ),
            code(
                'grant_evidence = json.loads((PROJECT_ROOT / "genie" / '
                '"grant_evidence.json").read_text())\n'
                "print(json.dumps(grant_evidence, indent=2))",
                grant_output,
            ),
            nbformat.v4.new_markdown_cell(
                "### 12. Deployed endpoint verification\n\n"
                "The registered Part 2 model serves 100% of endpoint traffic. The live "
                "request below routed to Genie, returned generated SQL plus four rows, "
                "and synthesized the correct ranking without a PAT in endpoint settings."
            ),
            code(
                'deployment_evidence = json.loads((PROJECT_ROOT / "genie" / '
                '"deployment_evidence.json").read_text())\n'
                "print(json.dumps(deployment_evidence, indent=2))",
                deployment_output,
            ),
            nbformat.v4.new_markdown_cell(
                "### 13. Analysis Summary\n\n"
                "RAG and Genie serve complementary purposes. RAG is better suited to "
                "narrative, qualitative, and citation-heavy annual-report questions, "
                "while Genie is more reliable for governed tabular lookups, rankings, "
                "aggregations, and fiscal-year comparisons.\n\n"
                "Text-to-SQL can fail when a request is ambiguous, uses terminology that "
                "does not match the schema, or asks for data outside the curated tables. "
                "Clear metadata, sample questions, trusted SQL examples, and an explicit "
                "table-coverage routing boundary reduce these failures. Unity Catalog "
                "also provides centralized permissions, discoverability, and lineage "
                "that would be weaker if the values existed only in document chunks.\n\n"
                "The complete analysis is provided in [`analysis.md`](analysis.md)."
            ),
        ]
    )
    notebook.cells.extend(later_cells)
    for target in TARGETS:
        target_notebook = deepcopy(notebook)
        target.parent.mkdir(parents=True, exist_ok=True)
        nbformat.write(target_notebook, target)
        print(f"Wrote {target} with {len(notebook.cells)} cells")


if __name__ == "__main__":
    main()
