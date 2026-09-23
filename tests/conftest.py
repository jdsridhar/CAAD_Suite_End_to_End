"""Shared fixtures.

Many tests use real numbers from the legacy projects audited on 2026-09-23 (e.g. the
5NIU_STD MM-GBSA result, the 8J3V blind-docking box, the 2M2D_LIG production protocol).
The tests therefore also document why each rule exists.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def make_software() -> Callable[..., SoftwareRef]:
    def _make(
        name: str = "test-engine",
        version: str = "1.0",
        kind: SoftwareKind = SoftwareKind.ENGINE,
        license_class: LicenseClass = LicenseClass.OPEN_SOURCE_PERMISSIVE,
    ) -> SoftwareRef:
        return SoftwareRef(name=name, version=version, kind=kind, license_class=license_class)

    return _make


@pytest.fixture
def make_artifact() -> Callable[..., ArtifactRef]:
    def _make(role: str = "test") -> ArtifactRef:
        return ArtifactRef(artifact_id=new_ulid(), role=role)

    return _make
