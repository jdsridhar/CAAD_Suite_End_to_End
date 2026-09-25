"""Static PLIP normalization and explicitly geometric polar-contact behavior."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from caddsuite.adapters.interactions.geometric import (
    GeometricPolarContactAdapter,
    GeometricPolarContactParameters,
)
from caddsuite.adapters.interactions.plip import PlipAdapter, PlipParameters, PlipPlanError
from caddsuite.contracts.analysis import (
    InteractionAnalysisMethod,
    InteractionAnalysisRequest,
    InteractionType,
    ResidueRef,
)
from caddsuite.contracts.base import ArtifactRef, EntityRef
from caddsuite.domain.identity import new_ulid
from caddsuite_worker.geometric_polar_worker import _run as run_geometric_worker


def _artifact(role: str, digest: str = "a" * 64) -> ArtifactRef:
    return ArtifactRef(artifact_id=new_ulid(), role=role, sha256=digest)


def _request(
    method: InteractionAnalysisMethod = InteractionAnalysisMethod.PLIP,
) -> InteractionAnalysisRequest:
    return InteractionAnalysisRequest(
        id=new_ulid(),
        pose=EntityRef(kind="docking_pose", id=new_ulid()),
        target=EntityRef(kind="target", id=new_ulid()),
        complex_structure=_artifact("assembled_complex"),
        ligand_residue=ResidueRef(resname="LIG", chain="Z", resnum=999),
        method=method,
    )


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atom(
    record: str,
    serial: int,
    atom_name: str,
    resname: str,
    chain: str,
    resnum: int,
    x: float,
    element: str,
) -> str:
    return (
        f"{record:<6}{serial:5d} {atom_name:>4s} {resname:>3s} {chain}{resnum:4d} "
        f"   {x:8.3f}{0.0:8.3f}{0.0:8.3f}{1.0:6.2f}{0.0:6.2f}          {element:>2s}\n"
    )


def test_plip_plan_is_external_cli_and_has_no_implicit_fallback(tmp_path: Path):
    request = _request()
    root = tmp_path.resolve()
    (root / "complex.pdb").write_text("END\n", encoding="ascii")
    request = request.model_copy(
        update={
            "complex_structure": request.complex_structure.model_copy(
                update={"sha256": _hash(root / "complex.pdb")}
            )
        }
    )
    adapter = PlipAdapter()
    config = PlipParameters(plip_executable="/opt/plip/bin/plip")
    plan = adapter.plan_request(
        request,
        parameters=config.model_dump(),
        staged_inputs={str(request.complex_structure.artifact_id): Path("complex.pdb")},
        working_directory=root,
    )
    assert plan.commands[0].argv == (
        "/opt/plip/bin/plip",
        "-f",
        "complex.pdb",
        "-o",
        "plip-output",
        "-x",
        "-t",
        "--name",
        "caddsuite",
        "--model",
        "1",
    )
    assert "plip-output/caddsuite_report.xml" in plan.expected_outputs
    assert not hasattr(plan.commands[0], "shell")
    geometric_request = request.model_copy(
        update={"method": InteractionAnalysisMethod.GEOMETRIC_POLAR_CONTACT}
    )
    assert adapter.validate_request(geometric_request)


def test_plip_parser_selects_exact_requested_bindingsite_and_preserves_provenance(
    tmp_path: Path,
):
    request = _request()
    root = tmp_path.resolve()
    output = root / "plip-output"
    output.mkdir()
    xml = """<report plipversion="2.4.1">
      <bindingsite><identifiers><hetid>ATP</hetid><chain>A</chain><position>10</position></identifiers></bindingsite>
      <bindingsite><identifiers><hetid>LIG</hetid><chain>Z</chain><position>999</position></identifiers>
        <interactions><hydrogen_bonds><hydrogen_bond>
          <restype>ASP</restype><resnr>42</resnr><reschain>A</reschain>
          <dist_h-a>2.80</dist_h-a><don_angle>142.0</don_angle>
        </hydrogen_bond></hydrogen_bonds><hydrophobic_interactions>
          <hydrophobic_interaction><restype>LEU</restype><resnr>55</resnr>
          <reschain>B</reschain><dist>3.90</dist>
          </hydrophobic_interaction></hydrophobic_interactions></interactions>
      </bindingsite>
    </report>"""
    report = output / "caddsuite_report.xml"
    report.write_text(xml, encoding="utf-8")
    raw = _artifact("plip_xml", _hash(report))
    log = _artifact("plip_stderr", "b" * 64)
    result = PlipAdapter().normalize_result(
        request,
        {"report_path": "plip-output/caddsuite_report.xml"},
        raw_result_artifact=raw,
        source_artifacts={"complex": request.complex_structure},
        log_artifacts={"stderr": log},
        working_directory=root,
    )
    assert result.method.version == "2.4.1"
    assert result.request_id == request.id
    assert result.raw_result == raw
    assert result.interactions[0].type is InteractionType.HYDROPHOBIC
    assert result.interactions[1].type is InteractionType.HYDROGEN_BOND
    assert result.interactions[1].distance_A == 2.8
    assert result.interactions[1].angle_deg == 142
    assert result.warnings


def test_plip_fails_when_requested_ligand_has_zero_or_multiple_bindingsites(tmp_path: Path):
    request = _request()
    root = tmp_path.resolve()
    (root / "report.xml").write_text(
        '<report plipversion="x"><bindingsite><identifiers><hetid>WRONG</hetid>'
        "<chain>Z</chain><position>999</position></identifiers></bindingsite></report>",
        encoding="utf-8",
    )
    raw = _artifact("plip_xml", _hash(root / "report.xml"))
    with pytest.raises(PlipPlanError, match="exactly one bindingsite"):
        PlipAdapter().normalize_result(
            request,
            {"report_path": "report.xml"},
            raw_result_artifact=raw,
            source_artifacts={"complex": request.complex_structure},
            log_artifacts={"stderr": _artifact("plip_stderr", "b" * 64)},
            working_directory=root,
        )


def test_plip_rejects_xml_entities(tmp_path: Path):
    request = _request()
    report = tmp_path / "report.xml"
    report.write_text(
        '<!DOCTYPE report [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        '<report plipversion="x"><bindingsite><identifiers><hetid>&xxe;</hetid>'
        "</identifiers></bindingsite></report>",
        encoding="utf-8",
    )
    with pytest.raises(PlipPlanError, match="cannot be parsed"):
        PlipAdapter()._parse_report(report, request)


def test_geometric_worker_emits_only_polar_contacts_and_normalizes_ids(tmp_path: Path):
    request = _request(InteractionAnalysisMethod.GEOMETRIC_POLAR_CONTACT)
    pdb = tmp_path / "complex.pdb"
    pdb.write_text(
        "".join(
            (
                _atom("ATOM", 10, "N", "ASP", "A", 42, 0.0, "N"),
                _atom("ATOM", 11, "C", "ASP", "A", 42, 0.0, "C"),
                _atom("ATOM", 12, "O", "GLU", "A", 43, 8.0, "O"),
                _atom("HETATM", 1001, "O1", "LIG", "Z", 999, 3.5, "O"),
                _atom("HETATM", 1002, "C1", "LIG", "Z", 999, 4.0, "C"),
                _atom("HETATM", 2001, "O", "HOH", "W", 1, 3.0, "O"),
                "END\n",
            )
        ),
        encoding="ascii",
    )
    request = request.model_copy(
        update={
            "complex_structure": request.complex_structure.model_copy(update={"sha256": _hash(pdb)})
        }
    )
    request_path = tmp_path / "worker.request.json"
    payload = {
        "protocol": "caddsuite.geometric-polar-contact/1",
        "request_id": str(request.id),
        "pose": request.pose.model_dump(mode="json"),
        "target": request.target.model_dump(mode="json"),
        "complex_structure": {"path": "complex.pdb", "sha256": _hash(pdb)},
        "ligand_residue": request.ligand_residue.model_dump(mode="json"),
        "model_number": 1,
        "polar_contact_cutoff_A": 3.6,
        "polar_elements": ["N", "O", "S"],
    }
    request_path.write_text(json.dumps(payload), encoding="utf-8")
    run_geometric_worker(request_path, "out")
    result_path = tmp_path / "out/profile.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert len(result["interactions"]) == 1
    contact = result["interactions"][0]
    assert contact["type"] == "polar_contact"
    assert contact["residue"] == {
        "chain": "A",
        "resname": "ASP",
        "resnum": 42,
        "icode": None,
    }
    assert contact["ligand_atoms"] == [1001]
    assert contact["protein_atoms"] == [10]
    assert contact["distance_A"] == 3.5

    source = request.complex_structure.model_copy(update={"sha256": _hash(pdb)})
    result_contract = GeometricPolarContactAdapter().normalize_result(
        request,
        result,
        raw_result_artifact=_artifact("geometric_profile", _hash(result_path)),
        source_artifacts={"complex": source},
        log_artifacts={"stderr": _artifact("worker_stderr", "c" * 64)},
        working_directory=tmp_path,
    )
    assert all(item.type is InteractionType.POLAR_CONTACT for item in result_contract.interactions)
    assert result_contract.method.kind.value == "adapter"
    assert "not a hydrogen-bond" in " ".join(result_contract.warnings)


def test_geometric_plan_uses_confined_worker_and_explicit_method(tmp_path: Path):
    request = _request(InteractionAnalysisMethod.GEOMETRIC_POLAR_CONTACT)
    root = tmp_path.resolve()
    (root / "complex.pdb").write_text("END\n", encoding="ascii")
    request = request.model_copy(
        update={
            "complex_structure": request.complex_structure.model_copy(
                update={"sha256": _hash(root / "complex.pdb")}
            )
        }
    )
    plan = GeometricPolarContactAdapter().plan_request(
        request,
        parameters=GeometricPolarContactParameters(
            python_executable="/usr/bin/python3",
            worker_script="src/caddsuite_worker/geometric_polar_worker.py",
        ).model_dump(),
        staged_inputs={str(request.complex_structure.artifact_id): Path("complex.pdb")},
        working_directory=root,
    )
    assert plan.commands[0].argv[:2] == (
        "/usr/bin/python3",
        "src/caddsuite_worker/geometric_polar_worker.py",
    )
    assert plan.expected_outputs == ("geometric-polar-output/profile.json",)
