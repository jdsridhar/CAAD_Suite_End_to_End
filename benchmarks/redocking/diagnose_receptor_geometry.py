"""Report residue-local RDKit distance-connectivity failures in a prepared PDB.

This is a diagnostic heuristic, not a covalent-structure validator. It does not
modify coordinates or produce a receptor for docking.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from rdkit import Chem, rdBase

_ATOM_INDEX = re.compile(r"atom # (\d+)")


def diagnose(path: Path) -> dict[str, Any]:
    residues: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for line in path.read_text(encoding="ascii", errors="replace").splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            key = (line[21:22].strip(), line[22:27].strip(), line[17:20].strip())
            residues[key].append(line)

    findings = []
    for (chain, residue_id, residue_name), lines in sorted(residues.items()):
        block = "\n".join(lines) + "\nEND\n"
        with rdBase.BlockLogs():
            molecule = Chem.MolFromPDBBlock(
                block, sanitize=False, removeHs=False, proximityBonding=True
            )
            if molecule is None:
                findings.append(
                    {
                        "chain": chain,
                        "residue_id": residue_id,
                        "residue_name": residue_name,
                        "error": "RDKit could not parse residue atom records",
                    }
                )
                continue
            try:
                Chem.SanitizeMol(molecule)
            except Exception as error:  # the diagnostic must retain toolkit failure text
                finding: dict[str, Any] = {
                    "chain": chain,
                    "residue_id": residue_id,
                    "residue_name": residue_name,
                    "error": str(error),
                }
                match = _ATOM_INDEX.search(str(error))
                if match:
                    atom_index = int(match.group(1))
                    if 0 <= atom_index < molecule.GetNumAtoms():
                        atom = molecule.GetAtomWithIdx(atom_index)
                        info = atom.GetPDBResidueInfo()
                        finding["atom"] = {
                            "index": atom_index,
                            "name": info.GetName().strip() if info else None,
                            "element": atom.GetSymbol(),
                            "neighbors": [
                                {
                                    "name": neighbor.GetPDBResidueInfo().GetName().strip()
                                    if neighbor.GetPDBResidueInfo()
                                    else None,
                                    "element": neighbor.GetSymbol(),
                                }
                                for neighbor in atom.GetNeighbors()
                            ],
                        }
                findings.append(finding)
    return {
        "schema": "caddsuite.meeko-residue-geometry-diagnostic/1",
        "input": path.name,
        "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "residue_count": len(residues),
        "failed_residue_count": len(findings),
        "interpretation": (
            "RDKit distance-inferred residue graph diagnostic only; a failure does not "
            "by itself establish incorrect experimental chemistry."
        ),
        "findings": findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdb", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = diagnose(args.pdb)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "residue_count": report["residue_count"],
                "failed_residue_count": report["failed_residue_count"],
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
