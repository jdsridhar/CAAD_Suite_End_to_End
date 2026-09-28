"""Select a seeded, sequence-diverse redocking cohort from frozen RCSB candidates."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from . import curate_candidates
except ImportError:  # Direct script execution.
    import curate_candidates

USER_AGENT = "CADD-Suite-redocking-curation/0.1"
PDB_ID = re.compile(r"^[0-9][A-Za-z0-9]{3}$")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_hash(value: Any) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _atomic_json(path: Path, value: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _download_structure(pdb_id: str) -> tuple[bytes, dict[str, str]]:
    if not PDB_ID.fullmatch(pdb_id):
        raise ValueError(f"invalid PDB identifier: {pdb_id!r}")
    url = f"https://files.rcsb.org/download/{pdb_id.upper()}.cif.gz"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                return response.read(), {
                    "url": url,
                    "last_modified": response.headers.get("Last-Modified", ""),
                    "content_length": response.headers.get("Content-Length", ""),
                }
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 3:
                raise
        except urllib.error.URLError:
            if attempt == 3:
                raise
        time.sleep(2**attempt)
    raise RuntimeError("RCSB structure retry loop ended unexpectedly")


def _read_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return records
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        entity_id = record.get("entity_id")
        if not isinstance(entity_id, str) or entity_id in records:
            raise ValueError(f"invalid or duplicate curation record at line {number}")
        records[entity_id] = record
    return records


def _cohort_hash_source() -> dict[str, str]:
    return {
        "selector_sha256": _sha256(Path(__file__).read_bytes()),
        "reviewer_sha256": _sha256(Path(curate_candidates.__file__).read_bytes()),
    }


def select_cohort(
    catalog_path: Path,
    output: Path,
    *,
    cohort_size: int = 30,
    resume: bool = False,
    structure_cache: Path | None = None,
) -> Path:
    """Review seeded cluster/member order, preserving all decisions and artifacts."""
    if not 1 <= cohort_size <= 30:
        raise ValueError("cohort_size must be between 1 and the preregistered 30 cases")
    catalog_bytes = catalog_path.read_bytes()
    catalog_hash = _sha256(catalog_bytes)
    catalog = json.loads(catalog_bytes)
    seed = int(catalog["grouping"]["draw_seed"])
    groups = catalog["groups_seeded"]
    protocol_path = Path("docs/validation/REDOCKING_BENCHMARK_PROTOCOL.md")
    expected = {
        **_cohort_hash_source(),
        "catalog_sha256": catalog_hash,
        "protocol_sha256": _sha256(protocol_path.read_bytes()),
        "seed": seed,
        "cohort_size": cohort_size,
    }
    if output.exists() and any(output.iterdir()) and not (output / "progress.json").exists():
        raise FileExistsError(f"curation output is nonempty and has no checkpoint: {output}")
    output.mkdir(parents=True, exist_ok=True)
    structures = output / "structures"
    structures.mkdir(exist_ok=True)
    decisions_path = output / "candidate_decisions.jsonl"
    state_path = output / "progress.json"
    if state_path.exists():
        if not resume:
            raise FileExistsError(f"curation output already exists; pass --resume: {output}")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if any(state.get(key) != value for key, value in expected.items()):
            raise ValueError("resume inputs or curation software hashes differ from checkpoint")
    else:
        if resume:
            raise FileNotFoundError(f"no curation checkpoint to resume in {output}")
        state = {
            **expected,
            "next_group": 0,
            "next_member": 0,
            "selected": [],
            "structure_sources": {},
        }
        if structure_cache is not None:
            cache_structures = structure_cache / "structures"
            cache_progress = structure_cache / "progress.json"
            if not cache_structures.is_dir() or not cache_progress.is_file():
                raise ValueError("structure cache must point to a completed curation checkpoint")
            cached_state = json.loads(cache_progress.read_text(encoding="utf-8"))
            state["structure_sources"].update(cached_state.get("structure_sources", {}))
            for cached_file in cache_structures.glob("*.cif.gz"):
                target_file = structures / cached_file.name
                if target_file.exists():
                    continue
                data = cached_file.read_bytes()
                gzip.decompress(data)  # Reject truncated/corrupt cache entries before reuse.
                temp_file = target_file.with_suffix(".cif.gz.tmp")
                temp_file.write_bytes(data)
                os.replace(temp_file, target_file)
            _atomic_json(state_path, state)
        else:
            _atomic_json(state_path, state)

    decisions = _read_jsonl(decisions_path)

    selected: list[dict[str, Any]] = state["selected"]
    selected_ids = {case["entity_id"] for case in selected}
    for decision in decisions.values():
        recovered = decision.get("selected_case")
        if (
            decision.get("status") == "selected"
            and recovered
            and recovered["entity_id"] not in selected_ids
        ):
            selected.append(recovered)
            selected_ids.add(recovered["entity_id"])
    state["selected"] = selected
    _atomic_json(state_path, state)
    if len(selected) >= cohort_size:
        return _finalize(catalog, output, decisions, selected, state)

    group_index, member_index = int(state["next_group"]), int(state["next_member"])
    with decisions_path.open("a", encoding="utf-8") as decision_file:
        while group_index < len(groups) and len(selected) < cohort_size:
            group = groups[group_index]
            cluster_id = str(group["cluster_id"])
            members = group["candidate_entity_ids_seeded"]
            if member_index >= len(members):
                group_index, member_index = group_index + 1, 0
                state.update({"next_group": group_index, "next_member": member_index})
                _atomic_json(state_path, state)
                continue
            entity_id = str(members[member_index])
            if entity_id in decisions:
                prior = decisions[entity_id]
                member_index += 1
                if prior.get("status") == "selected":
                    group_index, member_index = group_index + 1, 0
                state.update(
                    {"next_group": group_index, "next_member": member_index, "selected": selected}
                )
                _atomic_json(state_path, state)
                continue

            pdb_id, entity_number = entity_id.split("_", 1)
            compressed_path = structures / f"{pdb_id.lower()}.cif.gz"
            source = state["structure_sources"].get(pdb_id.upper(), {})
            try:
                if compressed_path.exists():
                    compressed = compressed_path.read_bytes()
                else:
                    compressed, source = _download_structure(pdb_id)
                    temp = compressed_path.with_suffix(".cif.gz.tmp")
                    temp.write_bytes(compressed)
                    os.replace(temp, compressed_path)
                    state["structure_sources"][pdb_id.upper()] = source
                cif_bytes = gzip.decompress(compressed)
                review = curate_candidates.evaluate_cif(cif_bytes, entity_number)
                ligand = next(
                    (item for item in review.get("ligand_instances", []) if item["eligible"]),
                    None,
                )
                eligible = bool(review["eligible"] and ligand is not None)
                record: dict[str, Any] = {
                    "entity_id": entity_id,
                    "cluster_id": cluster_id,
                    "status": "selected" if eligible else "ineligible",
                    "reasons": []
                    if eligible
                    else sorted(
                        set(
                            review.get("reasons", [])
                            + [
                                reason
                                for item in review.get("ligand_instances", [])
                                for reason in item["reasons"]
                            ]
                        )
                    ),
                    "pdb_id": pdb_id.upper(),
                    "source_url": source.get(
                        "url", f"https://files.rcsb.org/download/{pdb_id.upper()}.cif.gz"
                    ),
                    "structure_gzip_sha256": _sha256(compressed),
                    "structure_cif_sha256": _sha256(cif_bytes),
                    "structure_path": f"structures/{pdb_id.lower()}.cif.gz",
                    "review": review,
                }
                if eligible:
                    selected_case = {
                        "case_id": f"REDOCK-{len(selected) + 1:03d}",
                        "cluster_id": cluster_id,
                        "entity_id": entity_id,
                        "pdb_id": pdb_id.upper(),
                        "structure_path": record["structure_path"],
                        "structure_gzip_sha256": record["structure_gzip_sha256"],
                        "structure_cif_sha256": record["structure_cif_sha256"],
                        "ligand": ligand["ligand"],
                        "eligibility_review": review,
                    }
                    record["selected_case"] = selected_case
                    selected.append(selected_case)
            except Exception as exc:  # Preserve failed retrievals/parses in the denominator.
                record = {
                    "entity_id": entity_id,
                    "cluster_id": cluster_id,
                    "status": "review_failed",
                    "pdb_id": pdb_id.upper(),
                    "reasons": [
                        f"structure retrieval or review failed: {type(exc).__name__}: {exc}"
                    ],
                }
            decisions[entity_id] = record
            decision_file.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            decision_file.flush()
            os.fsync(decision_file.fileno())
            member_index += 1
            if record["status"] == "selected":
                group_index, member_index = group_index + 1, 0
            state.update(
                {"next_group": group_index, "next_member": member_index, "selected": selected}
            )
            _atomic_json(state_path, state)
            if len(decisions) % 10 == 0:
                print(
                    f"reviewed {len(decisions)} candidates; selected {len(selected)}/{cohort_size}",
                    flush=True,
                )
    return _finalize(catalog, output, decisions, selected, state)


def _finalize(
    catalog: dict[str, Any],
    output: Path,
    decisions: dict[str, dict[str, Any]],
    selected: list[dict[str, Any]],
    state: dict[str, Any],
) -> Path:
    selected_clusters = {case["cluster_id"] for case in selected}
    for group in catalog["groups_seeded"]:
        cluster_id = group["cluster_id"]
        for entity_id in group["candidate_entity_ids_seeded"]:
            if entity_id not in decisions:
                represented = cluster_id in selected_clusters
                decisions[entity_id] = {
                    "entity_id": entity_id,
                    "cluster_id": cluster_id,
                    "status": "not_assessed_cluster_represented"
                    if represented
                    else "not_assessed_cohort_complete",
                    "reasons": [
                        "cluster already represented by an earlier eligible candidate"
                        if represented
                        else "cohort filled before this cluster was assessed"
                    ],
                }
    for item in catalog.get("uncategorized_entities", []):
        entity_id = item["entity_id"]
        decisions.setdefault(
            entity_id,
            {
                "entity_id": entity_id,
                "status": "excluded_unclustered",
                "reasons": ["entity absent from pinned RCSB cluster snapshot"],
            },
        )
    for item in catalog.get("pilot_excluded_entities", []):
        entity_id = item["entity_id"]
        decisions.setdefault(
            entity_id,
            {
                "entity_id": entity_id,
                "status": "excluded_pilot",
                "reasons": ["entry belongs to frozen diagnostic pilot"],
            },
        )
    captured_count = int(catalog["captured_entity_count"])
    if len(decisions) != captured_count:
        raise ValueError(
            f"candidate decision count does not reconcile: {len(decisions)} != {captured_count}"
        )
    decisions_path = output / "candidate_decisions.jsonl"
    temp = decisions_path.with_suffix(".jsonl.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        for entity_id in sorted(decisions):
            handle.write(
                json.dumps(decisions[entity_id], sort_keys=True, separators=(",", ":")) + "\n"
            )
    os.replace(temp, decisions_path)
    payload: dict[str, Any] = {
        "schema": "caddsuite.redocking-cohort/1",
        "frozen_at_utc": datetime.now(UTC).isoformat(),
        "seed": state["seed"],
        "selection_order": (
            "first eligible member in seeded member order within seeded cluster order"
        ),
        "capture": {
            "captured_at_utc": catalog["captured_at_utc"],
            "reported_entity_count": catalog["reported_entity_count"],
            "query_sha256": catalog["query_sha256"],
            "cluster_source": catalog["cluster_source"],
            "cluster_file_source_sha256": catalog["cluster_file"]["source_sha256"],
            "cluster_file_stored_sha256": catalog["cluster_file"]["stored_sha256"],
            "catalog_sha256": state["catalog_sha256"],
        },
        "protocol_sha256": state["protocol_sha256"],
        "reviewer_sha256": state["reviewer_sha256"],
        "selector_sha256": state["selector_sha256"],
        "software": {
            "python": sys.version,
            "platform": platform.platform(),
            "biopython": importlib.metadata.version("biopython"),
            "rdkit": importlib.metadata.version("rdkit"),
            "numpy": importlib.metadata.version("numpy"),
        },
        "requested_cases": state["cohort_size"],
        "selected_case_count": len(selected),
        "cohort_frozen": len(selected) == state["cohort_size"],
        "candidate_decisions_sha256": _sha256(decisions_path.read_bytes()),
        "cases": selected,
        "decision_status_counts": {
            status: sum(row["status"] == status for row in decisions.values())
            for status in sorted({row["status"] for row in decisions.values()})
        },
        "source_structures": state.get("structure_sources", {}),
        "limitations": [
            "Not-assessed candidates are not asserted to be scientifically ineligible.",
            "Docking has not run; an incomplete cohort must not proceed to docking.",
        ],
    }
    payload["manifest_sha256"] = _canonical_hash(payload)
    manifest = output / "cohort_manifest.json"
    _atomic_json(manifest, payload)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cohort-size", type=int, default=30)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--structure-cache", type=Path)
    args = parser.parse_args()
    print(
        select_cohort(
            args.catalog,
            args.out,
            cohort_size=args.cohort_size,
            resume=args.resume,
            structure_cache=args.structure_cache,
        )
    )


if __name__ == "__main__":
    main()
