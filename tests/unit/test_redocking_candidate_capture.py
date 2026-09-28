from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from benchmarks.redocking import capture_candidates as capture


def _response(identifiers: list[str], *, total: int = 3) -> bytes:
    return json.dumps(
        {
            "query_id": "query",
            "total_count": total,
            "result_set": identifiers,
        }
    ).encode()


def test_seeded_cluster_and_candidate_order_is_reproducible() -> None:
    cluster_bytes = b"1ABC_1 2ABC_1\n3ABC_1\n"
    identifiers = ["1ABC_1", "2ABC_1", "3ABC_1"]

    first, unclustered, pilot_excluded = capture.order_candidates(
        identifiers, cluster_bytes, seed=20260929
    )
    second, _, _ = capture.order_candidates(identifiers, cluster_bytes, seed=20260929)

    assert first == second
    assert not unclustered
    assert not pilot_excluded
    assert len(first) == 2
    assert capture.stable_order_key(17, "cluster-a") != capture.stable_order_key(18, "cluster-a")


def test_cluster_join_preserves_candidates_without_membership() -> None:
    groups, unclustered, pilot_excluded = capture.order_candidates(
        ["1ABC_1", "2ABC_1", "9ZZZ_1", "5NIU_1"],
        b"1ABC_1 2ABC_1\n3ABC_1\n5NIU_1\n",
        seed=11,
    )

    assert sum(len(group["candidate_entity_ids"]) for group in groups) == 2
    assert unclustered == ["9ZZZ_1"]
    assert pilot_excluded == ["5NIU_1"]


def test_cluster_parser_rejects_duplicate_membership() -> None:
    with pytest.raises(ValueError, match="multiple clusters"):
        capture.parse_cluster_file(b"1ABC_1 2ABC_1\n2ABC_1 3ABC_1\n")


def test_query_freezes_xray_resolution_protein_and_non_covalent_ligand_rules() -> None:
    payload = capture._page_query(start=0, rows=500)
    encoded = json.dumps(payload, sort_keys=True)

    assert '"value": "X-RAY DIFFRACTION"' in encoded
    assert '"value": 2.5' in encoded
    assert '"value": "Protein"' in encoded
    assert '"value": 50' in encoded
    assert '"value": "HAS_NO_COVALENT_LINKAGE"' in encoded
    assert "group_by" not in payload["request_options"]


def test_capture_pages_and_hashes_query_and_cluster_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    replies = {
        0: _response(["1ABC_1"]),
        1: _response(["2ABC_1", "3ABC_1"]),
    }
    calls: list[int] = []

    def fake_post(payload: dict[str, Any], timeout_s: int = 60) -> bytes:
        start = payload["request_options"]["paginate"]["start"]
        calls.append(start)
        return replies[start]

    cluster_bytes = b"1ABC_1 2ABC_1\n3ABC_1\n4ABC_1\n"

    monkeypatch.setattr(capture, "_post_json", fake_post)
    monkeypatch.setattr(
        capture, "_get_bytes", lambda url: (cluster_bytes, {"last_modified": "pinned"})
    )
    receipt_path = capture.capture(tmp_path / "capture", seed=17, rows=1)

    receipt = json.loads(receipt_path.read_text())
    catalog = json.loads((receipt_path.parent / receipt["candidate_catalog"]).read_text())
    assert calls == [0, 1]
    assert receipt["reported_entity_count"] == 3
    assert receipt["captured_entity_count"] == 3
    assert receipt["clustered_candidate_entity_count"] == 3
    assert receipt["uncategorized_entity_count"] == 0
    assert receipt["pilot_excluded_entity_count"] == 0
    assert catalog["cluster_file"]["last_modified"] == "pinned"
    assert catalog["cluster_file"]["path"].endswith(".txt.gz")
    assert catalog["groups_seeded"][0]["cluster_size"] >= 1
    assert len(catalog["pages"]) == 2
    assert len(catalog["groups_seeded"]) == 2
    assert len(list((receipt_path.parent / "pages").glob("page-*.json"))) == 2


def test_capture_rejects_inconsistent_pages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        capture,
        "_post_json",
        lambda payload, timeout_s=60: _response(["1ABC_1"], total=2),
    )
    monkeypatch.setattr(capture, "_get_bytes", lambda url: (b"1ABC_1\n", {}))

    with pytest.raises(ValueError, match="do not reconcile"):
        capture.capture(tmp_path / "inconsistent", rows=10)
