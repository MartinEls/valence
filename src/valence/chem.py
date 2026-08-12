"""Chemistry helpers: openbabel 3D generation, xtb optimization, equivalence checks."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ENERGY_RE = re.compile(r"energy:\s*([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)")
TOTAL_ENERGY_RE = re.compile(
    r"TOTAL ENERGY\s+([-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)\s*Eh",
    re.IGNORECASE,
)


def resolve_binary(name: str) -> str:
    """Resolve an executable, preferring a project-local patched binary when present."""
    # Project bin/ (e.g. patched xtb for the known gfortran format bug)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "bin" / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    found = shutil.which(name)
    if found is None:
        raise FileNotFoundError(
            f"Required binary '{name}' not found in PATH or project bin/"
        )
    return found


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    timeout: float = 120.0,
) -> subprocess.CompletedProcess[str]:
    # openbabel may echo invalid SMILES bytes (e.g. Latin-1) in stderr
    return subprocess.run(
        cmd,
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env={**os.environ, "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS", "1")},
    )


def smiles_to_inchi(smiles: str, obabel: str | None = None) -> tuple[str | None, str | None]:
    """Convert a SMILES string to InChI via openbabel. Returns (inchi, error)."""
    obabel = obabel or resolve_binary("obabel")
    proc = _run(
        [obabel, "-ismi", "-oinchi", "--title", ""],
        input_text=smiles.strip() + "\n",
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "obabel failed").strip()
        return None, f"obabel inchi from smiles: {msg}"

    inchi = _extract_inchi(proc.stdout)
    if not inchi:
        err = (proc.stderr or "").strip() or "no InChI produced"
        return None, f"obabel inchi from smiles: {err}"
    return inchi, None


def structure_to_inchi(path: Path, obabel: str | None = None) -> tuple[str | None, str | None]:
    """Convert a structure file (xyz, etc.) to InChI. Returns (inchi, error)."""
    obabel = obabel or resolve_binary("obabel")
    proc = _run([obabel, str(path), "-oinchi"])
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "obabel failed").strip()
        return None, f"obabel inchi from structure: {msg}"

    inchi = _extract_inchi(proc.stdout)
    if not inchi:
        err = (proc.stderr or "").strip() or "no InChI produced"
        return None, f"obabel inchi from structure: {err}"
    return inchi, None


def _extract_inchi(text: str) -> str | None:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("InChI="):
            return line
    return None


def generate_3d_xyz(
    smiles: str,
    out_xyz: Path,
    *,
    obabel: str | None = None,
) -> str | None:
    """Generate 3D coordinates with openbabel --gen3d. Returns error message or None."""
    obabel = obabel or resolve_binary("obabel")
    proc = _run(
        [obabel, "-ismi", "-oxyz", "--gen3d", "-O", str(out_xyz)],
        input_text=smiles.strip() + "\n",
        timeout=180.0,
    )
    if proc.returncode != 0 or not out_xyz.is_file() or out_xyz.stat().st_size == 0:
        msg = (proc.stderr or proc.stdout or "obabel 3d generation failed").strip()
        return f"obabel 3d: {msg}"
    # openbabel sometimes exits 0 with empty/failed conversion
    if "0 molecules converted" in (proc.stderr + proc.stdout):
        return f"obabel 3d: 0 molecules converted ({(proc.stderr or '').strip()})"
    return None


def optimize_xtb(
    xyz_path: Path,
    work_dir: Path,
    *,
    xtb: str | None = None,
    gfn: int = 2,
    timeout: float = 300.0,
) -> tuple[Path | None, float | None, str | None]:
    """
    Run xtb geometry optimization in work_dir.

    Returns (optimized_xyz_path, energy_Eh, error).
    """
    xtb = xtb or resolve_binary("xtb")
    work_dir.mkdir(parents=True, exist_ok=True)

    # Copy input so xtb side-files stay local
    local_xyz = work_dir / "input.xyz"
    local_xyz.write_text(xyz_path.read_text())

    proc = _run(
        [xtb, str(local_xyz.name), "--opt", "--gfn", str(gfn), "--norestart"],
        cwd=work_dir,
        timeout=timeout,
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    opt_xyz = work_dir / "xtbopt.xyz"

    # Known macOS/gfortran format-string crash in xtb 6.7.1 optimizer
    if "Missing comma between descriptors" in combined:
        return (
            None,
            None,
            "xtb: optimizer crashed (known format-string bug in xtb 6.7.1; "
            "run `uv run python scripts/patch_xtb.py` to install a patched binary under bin/)",
        )

    if not opt_xyz.is_file():
        msg = combined.strip() or f"xtb exited {proc.returncode} without xtbopt.xyz"
        # Keep message short but useful
        tail = "\n".join(msg.splitlines()[-15:])
        return None, None, f"xtb opt: {tail}"

    energy = _parse_energy(opt_xyz, combined)
    if energy is None:
        return opt_xyz, None, "xtb opt: optimized geometry written but energy not found"

    if proc.returncode != 0 and not (work_dir / ".xtboptok").exists():
        # Geometry exists; still surface a warning as soft error only if energy missing
        pass

    return opt_xyz, energy, None


def _parse_energy(opt_xyz: Path, log_text: str) -> float | None:
    # Prefer comment line on xtbopt.xyz
    try:
        lines = opt_xyz.read_text().splitlines()
        if len(lines) >= 2:
            m = ENERGY_RE.search(lines[1])
            if m:
                return float(m.group(1))
    except OSError:
        pass

    m = TOTAL_ENERGY_RE.search(log_text)
    if m:
        return float(m.group(1))
    return None


@dataclass
class MoleculeResult:
    identifier: str
    smiles: str
    error: str | None = None
    obabel_geometry: str | None = None
    optimized_geometry: str | None = None
    energy: float | None = None
    inchi_start: str | None = None
    inchi_obabel: str | None = None
    inchi_xtb: str | None = None
    equivalent_obabel: bool | None = None
    equivalent_xtb: bool | None = None
    extras: dict = field(default_factory=dict)

    def to_json_row(self) -> dict:
        """JSONL row: identifier, error, geometries, energy, InChI diagnostics."""
        return {
            "identifier": self.identifier,
            "smiles": self.smiles,
            "error": self.error,
            "obabel_geometry": self.obabel_geometry,
            "optimized_geometry": self.optimized_geometry,
            "energy": self.energy,
            "equivalent_obabel": self.equivalent_obabel,
            "equivalent_xtb": self.equivalent_xtb,
            "inchi_start": self.inchi_start,
            "inchi_obabel": self.inchi_obabel,
            "inchi_xtb": self.inchi_xtb,
        }


def process_molecule(identifier: str, smiles: str) -> MoleculeResult:
    """Full pipeline for one molecule: 3D → equivalence → xtb opt → equivalence."""
    result = MoleculeResult(identifier=identifier, smiles=smiles)

    try:
        return _process_molecule_inner(result, identifier, smiles)
    except subprocess.TimeoutExpired as e:
        result.error = f"timeout: {e}"
        return result
    except Exception as e:  # noqa: BLE001 — surface any tool failure as a JSONL error row
        result.error = f"unexpected: {type(e).__name__}: {e}"
        return result


def _process_molecule_inner(
    result: MoleculeResult, identifier: str, smiles: str
) -> MoleculeResult:
    try:
        obabel = resolve_binary("obabel")
        xtb = resolve_binary("xtb")
    except FileNotFoundError as e:
        result.error = str(e)
        return result

    start_inchi, err = smiles_to_inchi(smiles, obabel=obabel)
    if err:
        result.error = err
        return result
    result.inchi_start = start_inchi

    with tempfile.TemporaryDirectory(prefix=f"valence_{identifier}_") as tmp:
        tmp_path = Path(tmp)
        xyz_path = tmp_path / "mol.xyz"

        err = generate_3d_xyz(smiles, xyz_path, obabel=obabel)
        if err:
            result.error = err
            return result

        result.obabel_geometry = xyz_path.read_text(encoding="utf-8", errors="replace")

        obabel_inchi, err = structure_to_inchi(xyz_path, obabel=obabel)
        if err:
            result.error = err
            return result
        result.inchi_obabel = obabel_inchi
        result.equivalent_obabel = _inchi_equivalent(start_inchi, obabel_inchi)
        if not result.equivalent_obabel:
            result.error = (
                "obabel: generated 3D structure is not equivalent to starting SMILES "
                f"(start={start_inchi}, obabel={obabel_inchi})"
            )
            return result

        opt_dir = tmp_path / "xtb"
        opt_xyz, energy, err = optimize_xtb(xyz_path, opt_dir, xtb=xtb)
        if err:
            result.error = err
            return result

        assert opt_xyz is not None
        result.optimized_geometry = opt_xyz.read_text(encoding="utf-8", errors="replace")
        result.energy = energy

        xtb_inchi, err = structure_to_inchi(opt_xyz, obabel=obabel)
        if err:
            result.error = err
            return result

        result.inchi_xtb = xtb_inchi
        result.equivalent_xtb = _inchi_equivalent(start_inchi, xtb_inchi)

        if not result.equivalent_xtb:
            result.error = (
                "xtb: optimized structure is not equivalent to starting SMILES "
                f"(start={start_inchi}, xtb={xtb_inchi})"
            )
            return result

    return result


def _inchi_equivalent(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return _normalize_inchi(a) == _normalize_inchi(b)


def _normalize_inchi(inchi: str) -> str:
    """Drop stereo layers so gen3d stereochemistry does not break equivalence."""
    # InChI layers are separated by '/'. Stereo: /t, /m, /s
    parts = inchi.strip().split("/")
    kept = [p for p in parts if not (p.startswith("t") or p.startswith("m") or p.startswith("s"))]
    return "/".join(kept)
