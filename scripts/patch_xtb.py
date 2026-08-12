#!/usr/bin/env python3
"""Install a patched copy of system xtb under ./bin to fix the 6.7.1 format-string crash.

xtb 6.7.1 (Homebrew/conda builds) can abort mid-optimization with:

    Fortran runtime error: Missing comma between descriptors
    (1x,"("f7.2"%)")

Upstream main already has the correct format. This script copies the system
`xtb` binary, rewrites the broken format string in place, and ad-hoc codesigns
it on macOS so the binary can run.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

BROKEN = b'(1x,"("f7.2"%)")'
# Same length (16), valid Fortran format consuming one REAL
FIXED = b'(3x,f7.2," pct")'

assert len(BROKEN) == len(FIXED) == 16


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    dest_dir = root / "bin"
    dest = dest_dir / "xtb"

    src = shutil.which("xtb")
    if not src:
        print("error: system 'xtb' not found in PATH", file=sys.stderr)
        return 1

    data = bytearray(Path(src).read_bytes())
    idx = data.find(BROKEN)
    if idx < 0:
        # Already good or different build — still install a copy for PATH consistency
        print(f"note: broken format string not found in {src}; copying as-is")
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    else:
        data[idx : idx + len(BROKEN)] = FIXED
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        print(f"patched format string at offset {idx}")

    mode = dest.stat().st_mode
    dest.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    if sys.platform == "darwin":
        # Binary edit invalidates the code signature
        subprocess.run(
            ["codesign", "-s", "-", "-f", str(dest)],
            check=False,
            capture_output=True,
        )
        print("ad-hoc codesign applied")

    print(f"installed: {dest}")
    print("pipeline will prefer bin/xtb over PATH when present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
