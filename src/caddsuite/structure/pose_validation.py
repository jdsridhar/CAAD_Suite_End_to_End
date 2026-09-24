"""Engine-neutral pose-to-form and receptor-contact validation before MD preparation."""

from __future__ import annotations

import io
import math
from typing import Annotated, Any, cast

from pydantic import Field, model_validator

from caddsuite.chem.standardize import _rdkit
from caddsuite.contracts.base import ContractModel
from caddsuite.contracts.registry import Compound, CompoundForm
from caddsuite.validation.issues import Severity, SubjectRef, ValidationIssue


class PoseValidationParameters(ContractModel):
    """Explicit geometry sanity thresholds; these are triage rules, not energy criteria."""

    severe_clash_distance_A: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 1.0
    warning_clash_distance_A: Annotated[float, Field(gt=0, allow_inf_nan=False)] = 2.0

    @model_validator(mode="after")
    def thresholds_are_ordered(self) -> PoseValidationParameters:
        if self.warning_clash_distance_A <= self.severe_clash_distance_A:
            raise ValueError("warning clash distance must exceed severe clash distance")
        return self


def validate_pose_for_system_build(
    *,
    compound: Compound,
    form: CompoundForm,
    pose_sdf: bytes,
    receptor_pdb: bytes | None = None,
    parameters: PoseValidationParameters | None = None,
) -> tuple[ValidationIssue, ...]:
    """Return blockers/warnings for chemistry identity, explicit Hs and receptor clashes.

    A call does not alter coordinates or chemistry. The caller must store this exact report
    and its parameters with the build request/result.
    """
    params = parameters or PoseValidationParameters()
    Chem, _rdBase, _rdmd, _standardize, _all_chem = _rdkit()
    issues: list[ValidationIssue] = []

    def emit(
        code: str,
        severity: Severity,
        message: str,
        *,
        evidence: dict[str, Any] | None = None,
        remediation: tuple[str, ...] = (),
    ) -> None:
        issues.append(
            ValidationIssue(
                code=code,
                severity=severity,
                subject=SubjectRef(kind="compound_form", id=form.id),
                message=message,
                evidence=evidence or {},
                remediation=remediation,
                rule_version="1.0.0",
            )
        )

    if form.compound_id != compound.id:
        emit(
            "POSE.FORM_LINEAGE_MISMATCH",
            Severity.BLOCKER,
            "selected calculation form belongs to a different compound",
        )
        return tuple(issues)

    template = Chem.MolFromSmiles(form.smiles)
    if template is None:
        emit(
            "POSE.FORM_INVALID",
            Severity.BLOCKER,
            "selected calculation form SMILES cannot be parsed",
        )
        return tuple(issues)
    if Chem.GetFormalCharge(template) != form.formal_charge:
        emit(
            "POSE.FORM_CHARGE_MISMATCH",
            Severity.BLOCKER,
            "calculation form formal charge disagrees with its SMILES",
            evidence={
                "declared_charge": form.formal_charge,
                "smiles_charge": int(Chem.GetFormalCharge(template)),
            },
        )
        return tuple(issues)

    try:
        supplier = Chem.ForwardSDMolSupplier(
            io.BytesIO(pose_sdf), sanitize=True, removeHs=False, strictParsing=True
        )
        molecules = [mol for mol in supplier if mol is not None]
    except Exception as exc:
        emit(
            "POSE.SDF_INVALID",
            Severity.BLOCKER,
            f"normalized pose SDF could not be read: {exc}",
        )
        return tuple(issues)
    if len(molecules) != 1:
        emit(
            "POSE.SDF_MOLECULE_COUNT",
            Severity.BLOCKER,
            "pose SDF must contain exactly one valid molecule",
            evidence={"molecule_count": len(molecules)},
        )
        return tuple(issues)

    pose = cast(Any, molecules[0])
    if pose.GetNumConformers() != 1:
        emit(
            "POSE.CONFORMER_COUNT",
            Severity.BLOCKER,
            "normalized pose must contain exactly one 3D conformer",
            evidence={"conformer_count": int(pose.GetNumConformers())},
        )
        return tuple(issues)
    if not pose.GetConformer().Is3D():
        emit(
            "POSE.COORDINATES_NOT_3D",
            Severity.BLOCKER,
            "normalized pose coordinates are not marked as three-dimensional",
        )
        return tuple(issues)
    coords = [pose.GetConformer().GetAtomPosition(index) for index in range(pose.GetNumAtoms())]
    if any(not all(math.isfinite(v) for v in (point.x, point.y, point.z)) for point in coords):
        emit(
            "POSE.NONFINITE_COORDINATE",
            Severity.BLOCKER,
            "pose contains a non-finite atomic coordinate",
        )
        return tuple(issues)

    pose_charge = int(Chem.GetFormalCharge(pose))
    if pose_charge != form.formal_charge:
        emit(
            "POSE.CHARGE_MISMATCH",
            Severity.BLOCKER,
            "pose formal charge differs from the selected calculation form",
            evidence={"form_charge": form.formal_charge, "pose_charge": pose_charge},
        )

    parent = compound.parent
    pose_heavy = int(pose.GetNumHeavyAtoms())
    if pose_heavy != parent.heavy_atom_count:
        emit(
            "POSE.HEAVY_ATOM_COUNT_MISMATCH",
            Severity.BLOCKER,
            "pose heavy-atom count differs from the compound identity",
            evidence={
                "expected": parent.heavy_atom_count,
                "observed": pose_heavy,
            },
        )

    expected_graph = Chem.MolToSmiles(template, canonical=True, isomericSmiles=True)
    pose_graph = Chem.MolToSmiles(Chem.RemoveHs(pose), canonical=True, isomericSmiles=True)
    if pose_graph != expected_graph:
        emit(
            "POSE.GRAPH_OR_STEREOCHEMISTRY_MISMATCH",
            Severity.BLOCKER,
            "pose bond orders or stereochemistry differ from the selected calculation form",
            evidence={
                "expected_isomeric_smiles": expected_graph,
                "pose_isomeric_smiles": pose_graph,
            },
            remediation=("Regenerate the normalized pose from the selected compound form.",),
        )

    expected_hydrogens = int(Chem.AddHs(template).GetNumAtoms() - template.GetNumHeavyAtoms())
    observed_hydrogens = sum(atom.GetAtomicNum() == 1 for atom in pose.GetAtoms())
    if observed_hydrogens != expected_hydrogens:
        emit(
            "POSE.HYDROGEN_COUNT_MISMATCH",
            Severity.BLOCKER,
            "pose explicit-hydrogen count differs from the selected form's valence-complete graph",
            evidence={
                "expected_explicit_hydrogens": expected_hydrogens,
                "observed_explicit_hydrogens": observed_hydrogens,
            },
            remediation=("Rebuild explicit hydrogens using the selected protonation form.",),
        )

    if receptor_pdb is None:
        emit(
            "POSE.CLASH_NOT_ASSESSED",
            Severity.WARNING,
            "receptor coordinates were not supplied; receptor-ligand contacts were not assessed",
            remediation=(
                "Run clash validation with the prepared receptor before system building.",
            ),
        )
        return tuple(issues)

    receptor_coords: list[tuple[float, float, float]] = []
    try:
        for line_number, line in enumerate(receptor_pdb.decode("ascii").splitlines(), start=1):
            if line[:6].strip() not in {"ATOM", "HETATM"}:
                continue
            element = line[76:78].strip().upper() if len(line) >= 78 else ""
            if not element:
                element = "".join(char for char in line[12:16] if char.isalpha())[:1].upper()
            if element in {"H", "D"}:
                continue
            if len(line) < 54:
                raise ValueError(f"atom record at line {line_number} is shorter than 54 columns")
            xyz = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
            if not all(math.isfinite(value) for value in xyz):
                raise ValueError(f"atom record at line {line_number} has non-finite coordinates")
            receptor_coords.append(xyz)
    except (UnicodeDecodeError, ValueError) as exc:
        emit(
            "POSE.RECEPTOR_COORDINATE_INVALID",
            Severity.BLOCKER,
            f"prepared receptor coordinates could not be validated: {exc}",
        )
        return tuple(issues)
    if not receptor_coords:
        emit(
            "POSE.RECEPTOR_HAS_NO_HEAVY_ATOMS",
            Severity.BLOCKER,
            "prepared receptor contains no readable heavy-atom coordinates",
        )
        return tuple(issues)

    ligand_heavy_coords = [
        (point.x, point.y, point.z)
        for index, point in enumerate(coords)
        if pose.GetAtomWithIdx(index).GetAtomicNum() > 1
    ]
    minimum = math.inf
    severe_pairs = 0
    warning_pairs = 0
    for ligand_xyz in ligand_heavy_coords:
        for receptor_xyz in receptor_coords:
            distance = math.sqrt(
                sum((a - b) ** 2 for a, b in zip(ligand_xyz, receptor_xyz, strict=True))
            )
            minimum = min(minimum, distance)
            severe_pairs += distance < params.severe_clash_distance_A
            warning_pairs += distance < params.warning_clash_distance_A

    if severe_pairs:
        emit(
            "POSE.SEVERE_RECEPTOR_CLASH",
            Severity.BLOCKER,
            "ligand and receptor heavy atoms overlap below the configured severe-clash distance",
            evidence={
                "minimum_heavy_atom_distance_A": minimum,
                "severe_threshold_A": params.severe_clash_distance_A,
                "pair_count": severe_pairs,
            },
            remediation=("Inspect the selected pose and receptor preparation before MD.",),
        )
    elif warning_pairs:
        emit(
            "POSE.CLOSE_RECEPTOR_CONTACT",
            Severity.WARNING,
            "ligand pose contains close heavy-atom contacts under the configured review threshold",
            evidence={
                "minimum_heavy_atom_distance_A": minimum,
                "review_threshold_A": params.warning_clash_distance_A,
                "pair_count": warning_pairs,
            },
            remediation=(
                "Review these contacts; the distance screen is not an energy calculation.",
            ),
        )
    return tuple(issues)
