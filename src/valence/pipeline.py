"""Prefect flow: QM9 difficult cases → JSONL of optimized geometries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import polars as pl
from prefect import flow, get_run_logger, task
from prefect.futures import wait

from valence.chem import MoleculeResult, process_molecule


def _error_row(identifier: str, smiles: str, error: str) -> dict:
    return {
        "identifier": identifier,
        "smiles": smiles,
        "error": error,
        "obabel_geometry": None,
        "optimized_geometry": None,
        "energy": None,
        "equivalent_obabel": None,
        "equivalent_xtb": None,
        "inchi_start": None,
        "inchi_obabel": None,
        "inchi_xtb": None,
    }


@task(name="load-smiles-table", retries=0)
def load_smiles_table(input_path: str) -> list[dict[str, str]]:
    """
    Load a table of `identifier smiles` lines with polars.

    Each line: numeric identifier, space, SMILES string.
    """
    path = Path(input_path)
    if not path.is_file():
        raise FileNotFoundError(f"Input file not found: {path}")

    # Read raw lines so SMILES with unusual characters stay intact
    raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    rows: list[dict[str, str]] = []
    for i, line in enumerate(raw, start=1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            raise ValueError(f"Line {i}: expected 'identifier smiles', got: {line!r}")
        rows.append({"identifier": parts[0], "smiles": parts[1]})

    df = pl.DataFrame(rows)
    logger = get_run_logger()
    logger.info("Loaded %d entries from %s", df.height, path)
    return df.to_dicts()


@task(name="process-molecule", retries=0, persist_result=False)
def process_molecule_task(identifier: str, smiles: str) -> dict:
    """Generate 3D, optimize with xtb, check equivalence; return a JSON-serializable row."""
    try:
        result: MoleculeResult = process_molecule(identifier, smiles)
        return result.to_json_row()
    except Exception as e:  # noqa: BLE001 — never fail the flow on one molecule
        return _error_row(identifier, smiles, f"unexpected: {type(e).__name__}: {e}")


@task(name="write-jsonl", retries=1)
def write_jsonl(rows: list[dict], output_path: str) -> str:
    """Write one JSON object per line (JSONL)."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Stable order: original submission order is preserved by caller
    with out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    logger = get_run_logger()
    n_ok = sum(1 for r in rows if r.get("error") is None)
    n_err = len(rows) - n_ok
    logger.info("Wrote %d rows (%d ok, %d errors) → %s", len(rows), n_ok, n_err, out)
    return str(out.resolve())


@flow(name="qm9-difficult-cases", log_prints=True)
def qm9_difficult_cases(
    input_path: str = "qm9_unstable.csv",
    output_path: str = "output/results.jsonl",
) -> str:
    """
    For each identifier/SMILES:

    1. Build 3D coordinates with openbabel and check InChI equivalence
    2. Optimize with xtb and check InChI equivalence again
    3. Emit JSONL: identifier, error, and (on success) optimized geometry + energy
    """
    logger = get_run_logger()
    entries = load_smiles_table(input_path)

    # Submit tasks concurrently; collect in input order
    futures = [
        process_molecule_task.submit(e["identifier"], e["smiles"]) for e in entries
    ]
    wait(futures)
    rows: list[dict] = []
    for e, f in zip(entries, futures):
        try:
            rows.append(f.result(raise_on_failure=False))
            # Prefect may return a Failed state object when raise_on_failure=False
            if not isinstance(rows[-1], dict):
                rows[-1] = _error_row(e["identifier"], e["smiles"], f"task failed: {rows[-1]}")
        except Exception as exc:  # noqa: BLE001
            rows.append(
                _error_row(
                    e["identifier"],
                    e["smiles"],
                    f"task failed: {type(exc).__name__}: {exc}",
                )
            )

    out = write_jsonl(rows, output_path)
    n_ok = sum(1 for r in rows if r.get("error") is None)
    logger.info("Done: %d/%d molecules succeeded", n_ok, len(rows))
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="QM9 difficult cases: obabel 3D + xtb opt → JSONL (Prefect)"
    )
    parser.add_argument(
        "-i",
        "--input",
        default="qm9_unstable.csv",
        help="Input table: identifier SMILES per line (default: qm9_unstable.csv)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="output/results.jsonl",
        help="Output JSONL path (default: output/results.jsonl)",
    )
    args = parser.parse_args(argv)
    result = qm9_difficult_cases(input_path=args.input, output_path=args.output)
    print(result, file=sys.stdout)


if __name__ == "__main__":
    main()
