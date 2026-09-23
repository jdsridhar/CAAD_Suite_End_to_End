"""ULIDs and accessions."""

from __future__ import annotations

from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from caddsuite.domain.identity import (
    DERIVED_KINDS,
    AccessionKind,
    compound_accession,
    derived_accession,
    is_ulid,
    new_ulid,
    parse_accession,
    run_accession,
    target_accession,
    ulid_timestamp_ms,
)

timestamps = st.integers(min_value=0, max_value=2**48 - 1)


def test_ulid_shape() -> None:
    value = new_ulid()
    assert len(value) == 26
    assert is_ulid(value)


def test_ulid_is_deterministic_given_inputs() -> None:
    a = new_ulid(timestamp_ms=1_758_600_000_000, randomness=b"\x00" * 10)
    b = new_ulid(timestamp_ms=1_758_600_000_000, randomness=b"\x00" * 10)
    assert a == b
    assert ulid_timestamp_ms(a) == 1_758_600_000_000


@given(timestamps, st.binary(min_size=10, max_size=10))
def test_ulid_timestamp_round_trip(ts: int, rnd: bytes) -> None:
    assert ulid_timestamp_ms(new_ulid(timestamp_ms=ts, randomness=rnd)) == ts


@given(timestamps, timestamps)
def test_ulids_sort_by_time(t1: int, t2: int) -> None:
    lo, hi = sorted((t1, t2))
    a = new_ulid(timestamp_ms=lo, randomness=b"\xff" * 10)
    b = new_ulid(timestamp_ms=hi, randomness=b"\x00" * 10)
    if lo < hi:
        assert a < b


def test_many_ulids_are_unique() -> None:
    values = {new_ulid() for _ in range(10_000)}
    assert len(values) == 10_000


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "01ARZ3NDEKTSV4RRFFQ69G5FA",
        "01arz3ndektsv4rrffq69g5fav",
        "01ARZ3NDEKTSV4RRFFQ69G5FAI",
        "81ARZ3NDEKTSV4RRFFQ69G5FAV",
    ],
)
def test_is_ulid_rejects_malformed(bad: str) -> None:
    assert not is_ulid(bad)


def test_ulid_input_validation() -> None:
    with pytest.raises(ValueError, match="timestamp"):
        new_ulid(timestamp_ms=-1)
    with pytest.raises(ValueError, match="10 bytes"):
        new_ulid(randomness=b"short")


def test_accession_formats_follow_the_brief() -> None:
    assert compound_accession(1) == "CMP0001"
    assert compound_accession(12345) == "CMP12345"
    assert target_accession(7) == "TGT007"
    assert run_accession(date(2026, 9, 23), 1) == "RUN-20260923-001"
    assert derived_accession("CMP0001", AccessionKind.DOCKING, 1) == "CMP0001_DOCK_001"
    assert derived_accession("CMP0001", AccessionKind.POSE, 3) == "CMP0001_POSE_003"
    assert derived_accession("CMP0001", AccessionKind.MD, 1) == "CMP0001_MD_001"
    assert derived_accession("CMP0001", AccessionKind.BINDING_ENERGY, 1) == "CMP0001_MMPBSA_001"


def test_accession_validation() -> None:
    with pytest.raises(ValueError, match="start at 1"):
        compound_accession(0)
    with pytest.raises(ValueError, match="not a compound-derived"):
        derived_accession("CMP0001", AccessionKind.TARGET, 1)
    with pytest.raises(ValueError, match="parent must be a compound"):
        derived_accession("TGT001", AccessionKind.DOCKING, 1)
    with pytest.raises(ValueError, match="unrecognized"):
        parse_accession("5NIU_LIG")  # legacy name-based identity is not an accession


@given(
    st.integers(min_value=1, max_value=99_999),
    st.sampled_from(sorted(DERIVED_KINDS)),
    st.integers(min_value=1, max_value=9_999),
)
def test_derived_accession_round_trip(cmp_no: int, kind: AccessionKind, n: int) -> None:
    parent = compound_accession(cmp_no)
    parsed = parse_accession(derived_accession(parent, kind, n))
    assert (parsed.kind, parsed.parent, parsed.number) == (kind, parent, n)


def test_run_and_compound_parse() -> None:
    parsed = parse_accession("RUN-20260923-012")
    assert parsed.kind is AccessionKind.RUN
    assert parsed.run_date == date(2026, 9, 23)
    assert parsed.number == 12
    assert parse_accession("CMP0034").number == 34
