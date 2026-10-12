from caddsuite.application.engine_discovery import (
    EngineDiscoveryReport,
    EnginePaths,
    EngineReadiness,
    discover_engine_paths,
)


def test_discover_engine_paths_returns_valid_report() -> None:
    report = discover_engine_paths()
    assert isinstance(report, EngineDiscoveryReport)
    assert isinstance(report.paths, EnginePaths)
    assert isinstance(report.readiness, EngineReadiness)
    assert isinstance(report.missing_prerequisites, list)
    assert report.paths.caddsuite_python is not None
