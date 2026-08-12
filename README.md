# QM9 difficult cases

## Functions
- take each entry line and get the identifier and smiles string
- create 3d coordinates with openbabel, check if the generated molecule is equivalent to the starting string
- run geometry optimization with xtb, check if the final structure is still equivalent to the starting string
- put everything into a jsonl (one line for each entry):
    - identifier
    - error in obabel/xtb
    - if no error, optimized geometry and energy

## Tech
- use 'uv' for package managment
- use polars for data handling (not pandas)
- run everything local
- open-babel is in $PATH as 'obabel', xtb as 'xtb'

## Data format
table each line with a numeric identifier followed by a space and a smiles string