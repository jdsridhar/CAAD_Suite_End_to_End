"""Capture and deterministically group RCSB candidates for redocking curation."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import platform
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
CLUSTER_URL = "https://cdn.rcsb.org/resources/sequence/clusters/clusters-by-entity-30.txt"
ROWS_PER_PAGE = 10_000
DEFAULT_SEED = 20_260_929
PILOT_PDB_IDS = frozenset({"1M17", "3ERT", "5NIU"})

QUERY = {
    "query": {
        "type": "group",
        "logical_operator": "and",
        "nodes": [
            {
                "type": "terminal",
                "service": "text",
                "parameters": {
                    "attribute": "exptl.method",
                    "operator": "exact_match",
                    "value": "X-RAY DIFFRACTION",
                },
            },
            {
                "type": "terminal",
                "service": "text",
                "parameters": {
                    "attribute": "rcsb_entry_info.resolution_combined",
                    "operator": "less_or_equal",
                    "value": 2.5,
                },
            },
            {
                "type": "terminal",
                "service": "text",
                "parameters": {
                    "attribute": "entity_poly.rcsb_entity_polymer_type",
                    "operator": "exact_match",
                    "value": "Protein",
                },
            },
            {
                "type": "terminal",
                "service": "text",
                "parameters": {
                    "attribute": "entity_poly.rcsb_sample_sequence_length",
                    "operator": "greater_or_equal",
                    "value": 50,
                },
            },
            {
                "type": "group",
                "logical_operator": "and",
                "nodes": [
                    {
                        "type": "terminal",
                        "service": "text",
                        "parameters": {
                            "attribute": "rcsb_nonpolymer_instance_annotation.type",
                            "operator": "exact_match",
                            "value": "HAS_NO_COVALENT_LINKAGE",
                        },
                    }
                ],
            },
        ],
    },
    "return_type": "polymer_entity",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stable_order_key(seed: int, *identifiers: str) -> str:
    """Version-independent pseudorandom order key for a seeded selection."""
    payload = "\0".join((str(seed), *identifiers)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def parse_cluster_file(cluster_bytes: bytes) -> dict[str, tuple[str, ...]]:
    """Map every RCSB polymer entity in the pinned cluster file to its full cluster."""
    try:
        text = cluster_bytes.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError("RCSB cluster file must be ASCII") from exc
    membership: dict[str, tuple[str, ...]] = {}
    for line_number, line in enumerate(text.splitlines(), start=1):
        members = tuple(sorted(set(line.split())))
        if not members:
            continue
        for member in members:
            if member in membership:
                raise ValueError(
                    f"entity {member} appears in multiple clusters (line {line_number})"
                )
            membership[member] = members
    return membership


def order_candidates(
    entity_ids: list[str], cluster_bytes: bytes, seed: int
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Group captured entities and return seeded order plus explicit exclusions."""
    membership = parse_cluster_file(cluster_bytes)
    grouped: dict[str, dict[str, Any]] = {}
    unclustered: list[str] = []
    pilot_excluded: list[str] = []
    for entity_id in sorted(set(entity_ids)):
        pdb_id = entity_id.split("_", maxsplit=1)[0].upper()
        if pdb_id in PILOT_PDB_IDS:
            pilot_excluded.append(entity_id)
            continue
        members = membership.get(entity_id)
        if members is None:
            unclustered.append(entity_id)
            continue
        cluster_id = members[0]
        entry = grouped.setdefault(
            cluster_id,
            {
                "cluster_id": cluster_id,
                "cluster_size": len(members),
                "candidate_entity_ids": [],
            },
        )
        entry["candidate_entity_ids"].append(entity_id)

    result: list[dict[str, Any]] = []
    for cluster_id, group in grouped.items():
        candidates = sorted(
            group["candidate_entity_ids"],
            key=lambda candidate: (stable_order_key(seed, cluster_id, candidate), candidate),
        )
        result.append(
            {
                **group,
                "candidate_entity_ids_seeded": candidates,
            }
        )
    result.sort(
        key=lambda group: (
            stable_order_key(seed, str(group["cluster_id"])),
            str(group["cluster_id"]),
        )
    )
    return result, unclustered, pilot_excluded


def _post_json(payload: dict[str, Any], timeout_s: int = 60) -> bytes:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        SEARCH_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "CADD-Suite-redocking-curation/0.1",
        },
        method="POST",
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 3:
                raise
        except urllib.error.URLError:
            if attempt == 3:
                raise
        time.sleep(2**attempt)
    raise RuntimeError("RCSB request retry loop ended unexpectedly")


def _get_bytes(url: str, timeout_s: int = 90) -> tuple[bytes, dict[str, str]]:
    if url != CLUSTER_URL:
        raise ValueError("only the pinned RCSB cluster URL may be downloaded")
    request = urllib.request.Request(  # noqa: S310
        url,
        headers={"User-Agent": "CADD-Suite-redocking-curation/0.1"},
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
                return response.read(), {
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
    raise RuntimeError("RCSB download retry loop ended unexpectedly")


def _page_query(start: int, rows: int) -> dict[str, Any]:
    payload = json.loads(json.dumps(QUERY))
    payload["request_options"] = {
        "paginate": {"start": start, "rows": rows},
        "results_verbosity": "compact",
    }
    return payload


def _identifier(hit: Any) -> str:
    if isinstance(hit, str):
        return hit
    if isinstance(hit, dict) and isinstance(hit.get("identifier"), str):
        return hit["identifier"]
    raise ValueError(f"unexpected RCSB hit shape: {type(hit).__name__}")


def capture(output: Path, *, seed: int = DEFAULT_SEED, rows: int = ROWS_PER_PAGE) -> Path:
    """Capture every query hit and the cluster snapshot, then write a hashed catalog."""
    if output.exists():
        raise FileExistsError(f"output directory must not already exist: {output}")
    if not 1 <= rows <= ROWS_PER_PAGE:
        raise ValueError(f"rows must be between 1 and {ROWS_PER_PAGE}")
    output.mkdir(parents=True)
    pages_dir = output / "pages"
    pages_dir.mkdir()

    first_body = _post_json(_page_query(0, rows))
    first = json.loads(first_body)
    entity_count = int(first.get("total_count", 0))
    if entity_count <= 0:
        raise ValueError("RCSB returned an empty candidate universe")

    page_records: list[dict[str, Any]] = []
    entity_ids: list[str] = []
    start = 0
    body = first_body
    while start < entity_count:
        page_index = len(page_records)
        parsed = json.loads(body)
        if int(parsed.get("total_count", -1)) != entity_count:
            raise ValueError("RCSB candidate entity count changed between pages")
        hits = parsed.get("result_set", [])
        if not isinstance(hits, list) or not hits:
            raise ValueError(f"RCSB returned no candidates at page offset {start}")
        identifiers = [_identifier(hit) for hit in hits]
        page_path = pages_dir / f"page-{page_index:03d}.json"
        page_path.write_bytes(body)
        page_records.append(
            {
                "start": start,
                "rows": len(identifiers),
                "path": page_path.relative_to(output).as_posix(),
                "sha256": sha256(body),
                "query_id": parsed.get("query_id"),
            }
        )
        entity_ids.extend(identifiers)
        start += len(identifiers)
        if start < entity_count:
            body = _post_json(_page_query(start, rows))

    if len(entity_ids) != entity_count or len(set(entity_ids)) != entity_count:
        raise ValueError("RCSB paginated candidate hits do not reconcile to total_count")

    cluster_bytes, cluster_headers = _get_bytes(CLUSTER_URL)
    cluster_path = output / "rcsb_clusters_by_entity_30.txt.gz"
    compressed_clusters = gzip.compress(cluster_bytes, compresslevel=9, mtime=0)
    cluster_path.write_bytes(compressed_clusters)
    groups, unclustered, pilot_excluded = order_candidates(entity_ids, cluster_bytes, seed)
    clustered_entity_count = sum(len(group["candidate_entity_ids"]) for group in groups)
    if clustered_entity_count + len(unclustered) + len(pilot_excluded) != entity_count:
        raise ValueError("cluster membership join does not reconcile to candidate count")

    query_bytes = (json.dumps(QUERY, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (output / "search_query.json").write_bytes(query_bytes)
    catalog = {
        "schema": "caddsuite.redocking-candidate-catalog/1",
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "source": SEARCH_URL,
        "query_sha256": sha256(query_bytes),
        "query": QUERY,
        "cluster_source": CLUSTER_URL,
        "cluster_file": {
            "path": cluster_path.name,
            "source_sha256": sha256(cluster_bytes),
            "stored_sha256": sha256(compressed_clusters),
            **cluster_headers,
        },
        "grouping": {
            "method": "RCSB weekly polymer-entity sequence clusters",
            "similarity_cutoff_percent": 30,
            "draw_seed": seed,
            "draw_order": (
                "ascending SHA-256 of UTF-8(seed NUL cluster-id [NUL candidate-entity-id])"
            ),
            "python_version": platform.python_version(),
        },
        "reported_entity_count": entity_count,
        "captured_entity_count": len(entity_ids),
        "clustered_candidate_entity_count": clustered_entity_count,
        "uncategorized_entity_count": len(unclustered),
        "pilot_excluded_entity_count": len(pilot_excluded),
        "cluster_count_with_candidates": len(groups),
        "pages": page_records,
        "groups_seeded": groups,
        "uncategorized_entities": [
            {
                "entity_id": entity_id,
                "status": "excluded_before_curation",
                "reason": "not_present_in_pinned_30_percent_cluster_file",
            }
            for entity_id in unclustered
        ],
        "pilot_excluded_entities": [
            {
                "entity_id": entity_id,
                "status": "excluded_before_curation",
                "reason": "belongs_to_frozen_redocking_pilot",
            }
            for entity_id in pilot_excluded
        ],
    }
    catalog_path = output / "candidate_catalog.json"
    catalog_bytes = (json.dumps(catalog, indent=2, sort_keys=True) + "\n").encode("utf-8")
    catalog_path.write_bytes(catalog_bytes)
    receipt = {
        "schema": "caddsuite.redocking-candidate-capture/1",
        "candidate_catalog": catalog_path.name,
        "candidate_catalog_sha256": sha256(catalog_bytes),
        "query_sha256": catalog["query_sha256"],
        "cluster_file_source_sha256": catalog["cluster_file"]["source_sha256"],
        "cluster_file_stored_sha256": catalog["cluster_file"]["stored_sha256"],
        "captured_at_utc": catalog["captured_at_utc"],
        "reported_entity_count": entity_count,
        "captured_entity_count": len(entity_ids),
        "clustered_candidate_entity_count": clustered_entity_count,
        "uncategorized_entity_count": len(unclustered),
        "pilot_excluded_entity_count": len(pilot_excluded),
        "cluster_count_with_candidates": len(groups),
        "page_count": len(page_records),
    }
    receipt_path = output / "capture_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return receipt_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--rows", type=int, default=ROWS_PER_PAGE)
    args = parser.parse_args()
    receipt = capture(args.output, seed=args.seed, rows=args.rows)
    print(f"Captured RCSB candidate catalog: {receipt}")


if __name__ == "__main__":
    main()
