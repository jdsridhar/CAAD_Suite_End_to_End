"""PDBFixer worker, invoked inside the dedicated cadd Conda environment."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare(request: dict[str, Any]) -> dict[str, Any]:
    """Prepare selected protein chains and return explicit changes and versions."""
    from openmm import __version__ as openmm_version  # type: ignore[import-not-found]
    from openmm.app import PDBxFile  # type: ignore[import-not-found]
    from pdbfixer import PDBFixer  # type: ignore[import-not-found]

    source = Path(request["input_mmcif"]).resolve(strict=True)
    destination = Path(request["output_mmcif"]).resolve()
    if source == destination:
        raise ValueError("input and output mmCIF paths must differ")
    selected_values = request["selected_chain_ids"]
    if not isinstance(selected_values, list) or any(
        not isinstance(item, str) or not item for item in selected_values
    ):
        raise ValueError("selected_chain_ids must be a list of non-empty chain IDs")
    selected = set(selected_values)
    if len(selected) != len(selected_values):
        raise ValueError("selected_chain_ids must not contain duplicates")
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {destination}")
    ph = float(request["ph"])
    if not 0 <= ph <= 14:
        raise ValueError("ph must be between 0 and 14")
    with source.open("r", encoding="utf-8") as input_stream:
        fixer = PDBFixer(pdbxfile=input_stream)
    chains = list(fixer.topology.chains())
    available = {str(chain.id) for chain in chains}
    unknown = selected - available
    if unknown:
        raise ValueError(f"selected chains absent from topology: {sorted(unknown)}")
    fixer.removeChains(chainIds=sorted(available - selected))
    fixer.findMissingResidues()
    gaps = []
    topology_chains = list(fixer.topology.chains())
    sequence_by_id = {str(sequence.chainId): sequence.residues for sequence in fixer.sequences}
    for (chain_index, insertion_index), residue_names in sorted(fixer.missingResidues.items()):
        chain = topology_chains[chain_index]
        residues = list(chain.residues())
        position = (
            "n_terminal"
            if insertion_index == 0
            else ("c_terminal" if insertion_index >= len(residues) else "internal")
        )
        modelled = position == "internal" and bool(request.get("fill_internal_gaps", True))
        gaps.append(
            {
                "chain_id": str(chain.id),
                "insertion_index": insertion_index,
                "position": position,
                "residue_names": list(residue_names),
                "modelled": modelled,
                "sequence_length": len(sequence_by_id.get(str(chain.id), "")),
            }
        )
        if not modelled:
            del fixer.missingResidues[(chain_index, insertion_index)]
    fixer.findNonstandardResidues()
    replacements = [
        {
            "chain_id": str(residue.chain.id),
            "residue_id": str(residue.id),
            "from": residue.name,
            "to": standard.name,
        }
        for residue, standard in fixer.nonstandardResidues
    ]
    fixer.replaceNonstandardResidues()
    removed_residues = fixer.removeHeterogens(keepWater=bool(request.get("keep_water", False)))
    removed = [
        {"chain_id": str(residue.chain.id), "residue_id": str(residue.id), "name": residue.name}
        for residue in removed_residues
    ]
    fixer.findMissingAtoms()
    missing_atom_count = sum(len(names) for names in fixer.missingAtoms.values())
    fixer.addMissingAtoms()
    fixer.addMissingHydrogens(pH=ph)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            PDBxFile.writeFile(fixer.topology, fixer.positions, stream, keepIds=True)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "protocol": "caddsuite.pdbfixer-worker/1",
        "input_sha256": _sha256(source),
        "output_sha256": _sha256(destination),
        "pdbfixer_version": importlib.metadata.version("pdbfixer"),
        "openmm_version": openmm_version,
        "selected_chain_ids": sorted(selected),
        "ph": ph,
        "missing_residues": gaps,
        "nonstandard_replacements": replacements,
        "removed_components": removed,
        "missing_heavy_atom_count": missing_atom_count,
        "output_atom_count": sum(1 for _ in fixer.topology.atoms()),
        "output_residue_count": sum(1 for _ in fixer.topology.residues()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = prepare(json.loads(args.request.read_text(encoding="utf-8")))
        print(json.dumps({"ok": True, "result": result}, sort_keys=True))
        return 0
    except Exception as exc:
        print(
            json.dumps({"ok": False, "error_type": type(exc).__name__, "error": str(exc)}),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
