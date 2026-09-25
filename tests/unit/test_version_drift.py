from caddsuite.application.version_drift import version_drift


def _attempt(identifier: str, version: str, lock: str) -> dict[str, object]:
    return {
        "id": identifier,
        "payload": {
            "software": [
                {
                    "role": "engine",
                    "software": {"name": "GROMACS", "kind": "md_engine", "version": version},
                }
            ],
            "environment": {"lock_sha256": lock},
        },
    }


def test_version_and_environment_differences_are_explicit_advisory_warnings() -> None:
    result = version_drift(
        [
            _attempt("a1", "2025.1", "a" * 64),
            _attempt("a2", "2026.3", "b" * 64),
        ]
    )
    assert result["compared_attempt_count"] == 2
    warnings = result["warnings"]
    assert isinstance(warnings, list)
    assert {row["code"] for row in warnings} == {
        "PROVENANCE.SOFTWARE_VERSION_DRIFT",
        "PROVENANCE.ENVIRONMENT_DRIFT",
    }
    assert all(row["severity"] == "warning" for row in warnings)


def test_does_not_compare_unknown_versions_or_different_software() -> None:
    result = version_drift(
        [
            _attempt("a1", "unknown", "a" * 64),
            {
                "id": "a2",
                "payload": {
                    "software": [
                        {
                            "role": "engine",
                            "software": {"name": "NAMD", "kind": "md_engine", "version": "3.0"},
                        }
                    ]
                },
            },
        ]
    )
    assert result["warnings"] == []
