# QM9 difficult cases

Prefect pipeline that builds 3D geometries and optimizes QM9 “difficult” SMILES
locally with **openbabel** and **xtb**, writing one JSONL row per input line.

## Functions

- take each entry line and get the identifier and smiles string
- create 3d coordinates with openbabel, check if the generated molecule is equivalent to the starting string
- run geometry optimization with xtb, check if the final structure is still equivalent to the starting string
- put everything into a jsonl (one line for each entry):
    - identifier
    - error in obabel/xtb
    - if no error, optimized geometry and energy

Equivalence is checked via **InChI** (openbabel), so aromatic vs Kekulé SMILES
forms still match.

## Tech

- use `uv` for package management
- use polars for data handling (not pandas)
- run everything local
- open-babel is in `$PATH` as `obabel`, xtb as `xtb`

## Data format

Table: each line with a numeric identifier followed by a space and a SMILES string.

```
003899 O=C1N=CON=N1
020692 CC1=NC(=O)N=NO1
```

Input in this repo: [`qm9_unstable.csv`](qm9_unstable.csv).

## Setup

```bash
# Python deps
uv sync

# Optional but recommended on macOS with xtb 6.7.1:
# Homebrew/conda builds crash mid-opt with a Fortran format-string bug.
# This copies PATH xtb into ./bin with a one-byte-string patch:
uv run python scripts/patch_xtb.py
```

Requires `obabel` and `xtb` on `PATH`. The pipeline prefers `./bin/xtb` when present
(so the patched binary is used automatically).

## Run

```bash
# Default: qm9_unstable.csv → output/results.jsonl
uv run valence

# Custom paths
uv run valence -i qm9_unstable.csv -o output/results.jsonl

# Or invoke the flow module directly
uv run python -m valence.pipeline -i qm9_unstable.csv -o output/results.jsonl
```

## HTML report

Interactive table (SMILES, 2D drawing, openbabel 3D, xtb-optimized 3D; InChI on hover).
Paginates every 100 rows. 2D depictions are pre-rendered with `obabel` at report build time;
3D viewers use 3Dmol.js (CDN).

```bash
uv run valence-report -i output/results.jsonl -o output/results.html
# then open output/results.html in a browser (needs network only for 3Dmol.js)
```

## Output (JSONL)

One JSON object per input line. Example success:

```json
{
  "identifier": "003899",
  "smiles": "O=C1N=CON=N1",
  "error": null,
  "optimized_geometry": "8\n energy: -21.58 ...\nO  ...\n",
  "energy": -21.58,
  "equivalent_obabel": true,
  "equivalent_xtb": true,
  "inchi_start": "InChI=1S/...",
  "inchi_obabel": "InChI=1S/...",
  "inchi_xtb": "InChI=1S/..."
}
```

On failure, `error` is a short message (`obabel …` / `xtb …` / equivalence
mismatch); geometry/energy may be partial if a later step failed.
