"""Application service for running local GROMACS solution builder and CAS registration."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.contracts.base import ArtifactRef, SoftwareRef
from caddsuite.contracts.md import (
    BoxSpec,
    ComponentForceField,
    ForceFieldComponent,
    ForceFieldFamily,
    MDProtocol,
    MDStage,
    MDStageKind,
    MDSystem,
    Parameterization,
)
from caddsuite.contracts.md_plan import MDStagePlan
from caddsuite.contracts.system import SystemBuildResult
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import new_ulid
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.storage.models import ArtifactRow, ProjectArtifactRow, ProjectRow
from caddsuite.structure.gromacs_solution_builder import (
    GromacsSolutionBuilder,
    SolutionBuilderConfig,
    validate_production_settings,
)
from caddsuite.validation import default_registry
from caddsuite.validation.force_field_profiles import get_gromacs_solution_profile_id

logger = logging.getLogger("caddsuite.gromacs_solution_service")


def _extract_box_spec_from_gro(gro_path: Path, box_type: str) -> BoxSpec:
    """Extract a valid BoxSpec from the last line of a GROMACS .gro file."""
    lines = gro_path.read_text(encoding="utf-8", errors="replace").splitlines()
    box_line = ""
    for line in reversed(lines):
        line = line.strip()
        if line:
            box_line = line
            break
    parts = [float(p) for p in box_line.split()]
    if len(parts) == 3:
        xx, yy, zz = parts
        vectors = ((xx, 0.0, 0.0), (0.0, yy, 0.0), (0.0, 0.0, zz))
    elif len(parts) >= 9:
        xx, yy, zz, v1y, v1z, v2x, v2z, v3x, v3y = parts[:9]
        vectors = ((xx, v1y, v1z), (v2x, yy, v2z), (v3x, v3y, zz))
    else:
        vectors = ((5.0, 0.0, 0.0), (0.0, 5.0, 0.0), (0.0, 0.0, 5.0))

    if "dodec" in box_type.lower():
        shape = "rhombic_dodecahedron"
    elif "octa" in box_type.lower():
        shape = "truncated_octahedron"
    elif all(abs(vectors[i][j]) < 1e-12 for i in range(3) for j in range(3) if i != j):
        shape = "rectangular"
    else:
        shape = "triclinic"

    return BoxSpec(shape=shape, vectors_nm=vectors)


def build_local_solution_system(
    project_id: str,
    sessions: sessionmaker[Session],
    store: ArtifactStore,
    *,
    target_artifact_id: str | None = None,
    forcefield: str = "amber14sb",
    water_model: str = "tip3p",
    box_type: str = "dodecahedron",
    padding_nm: float = 1.0,
    conc_molar: float = 0.15,
    neutralize: bool = True,
    positive_ion: str = "NA",
    negative_ion: str = "CL",
    length_ns: float = 1.0,
    timestep_fs: float = 2.0,
    temp_k: float = 300.0,
) -> dict[str, Any]:
    """Execute local GROMACS solution builder pipeline and register prepared artifacts in CAS."""
    effective_length_ns = float(length_ns)
    effective_timestep_fs = float(timestep_fs)
    effective_temp_k = float(temp_k)
    n_steps = validate_production_settings(
        length_ns=effective_length_ns,
        timestep_fs=effective_timestep_fs,
        temp_k=effective_temp_k,
    )
    with sessions() as session:
        if session.get(ProjectRow, project_id) is None:
            msg = f"Project {project_id!r} not found."
            raise KeyError(msg)

        target_row: ArtifactRow | None = None
        if target_artifact_id:
            target_row = session.get(ArtifactRow, target_artifact_id)
            if not target_row:
                msg = f"Target artifact {target_artifact_id!r} not found."
                raise FileNotFoundError(msg)
        else:
            stmt = (
                select(ArtifactRow)
                .join(ProjectArtifactRow, ProjectArtifactRow.artifact_id == ArtifactRow.id)
                .where(ProjectArtifactRow.project_id == project_id)
            )
            candidates = list(session.scalars(stmt).all())
            pdb_candidates = [
                c for c in candidates if (c.original_name or "").lower().endswith(".pdb")
            ]
            prepared_pdb = [
                c for c in pdb_candidates if "prepared" in (c.original_name or "").lower()
            ]
            if prepared_pdb:
                target_row = prepared_pdb[0]
            elif pdb_candidates:
                target_row = pdb_candidates[0]
            elif candidates:
                target_row = candidates[0]
            else:
                msg = (
                    "No receptor structure artifact found in this project. "
                    "Please upload a protein PDB file before running the local solution builder."
                )
                raise FileNotFoundError(msg)

        target_path = store.path_for(target_row.sha256)
        if not target_path.is_file():
            msg = f"Artifact payload missing in CAS store for {target_row.id}."
            raise FileNotFoundError(msg)

    with tempfile.TemporaryDirectory() as td:
        out_dir = Path(td)
        input_filename = target_row.original_name or "input_protein.pdb"
        if not input_filename.lower().endswith((".pdb", ".gro")):
            input_filename += ".pdb"
        input_pdb_path = out_dir / input_filename
        shutil.copyfile(target_path, input_pdb_path)

        cfg = SolutionBuilderConfig(
            forcefield=forcefield,
            water_model=water_model,
            box_type=box_type,
            box_padding_nm=padding_nm,
            ion_concentration_m=conc_molar,
            neutralize=neutralize,
            positive_ion=positive_ion,
            negative_ion=negative_ion,
        )
        builder = GromacsSolutionBuilder(config=cfg)
        summary = builder.build_system(
            protein_pdb=input_pdb_path,
            output_dir=out_dir,
        )

        builder.write_production_mdp(
            out_dir / "production.mdp",
            length_ns=effective_length_ns,
            timestep_fs=effective_timestep_fs,
            temp_k=effective_temp_k,
        )

        box_spec = _extract_box_spec_from_gro(out_dir / "system.gro", box_type)

        artifact_refs: dict[str, dict[str, Any]] = {}
        registered_by_name: dict[str, dict[str, Any]] = {}
        files_to_register = [
            ("coordinates", out_dir / "system.gro", "system.gro", "chemical/x-gro"),
            ("topology", out_dir / "topol.top", "topol.top", "chemical/x-top"),
            ("parameter", out_dir / "posre.itp", "posre.itp", "text/plain"),
            ("index", out_dir / "index.ndx", "index.ndx", "text/plain"),
            ("protocol", out_dir / "production.mdp", "production.mdp", "text/plain"),
            ("protocol", out_dir / "ions.mdp", "ions.mdp", "text/plain"),
            ("protocol", out_dir / "em.mdp", "em.mdp", "text/plain"),
        ]
        for extra_itp in sorted(out_dir.glob("*.itp")):
            if extra_itp.name != "posre.itp" and extra_itp.is_file():
                files_to_register.append(("parameter", extra_itp, extra_itp.name, "text/plain"))

        with sessions.begin() as session:
            for role, path, orig_name, media_type in files_to_register:
                if not path.is_file():
                    continue
                blob = store.put_file(path)
                art = register_blob(
                    session,
                    blob,
                    kind="input",
                    media_type=media_type,
                    original_name=orig_name,
                )
                link = session.get(ProjectArtifactRow, (project_id, art.id, role))
                if link is None:
                    session.add(
                        ProjectArtifactRow(
                            project_id=project_id,
                            artifact_id=art.id,
                            role=role,
                        )
                    )
                ref_payload = {
                    "id": art.id,
                    "sha256": art.sha256,
                    "role": role,
                    "original_name": orig_name,
                }
                artifact_refs[role] = ref_payload
                registered_by_name[orig_name] = ref_payload

    gro_ref = ArtifactRef(
        artifact_id=artifact_refs["coordinates"]["id"],
        role="coordinates",
        sha256=artifact_refs["coordinates"]["sha256"],
    )
    top_ref = ArtifactRef(
        artifact_id=artifact_refs["topology"]["id"],
        role="topology",
        sha256=artifact_refs["topology"]["sha256"],
    )
    ndx_ref = (
        ArtifactRef(
            artifact_id=artifact_refs["index"]["id"],
            role="index",
            sha256=artifact_refs["index"]["sha256"],
        )
        if "index" in artifact_refs
        else None
    )
    prod_mdp_ref = (
        ArtifactRef(
            artifact_id=registered_by_name["production.mdp"]["id"],
            role="mdp",
            sha256=registered_by_name["production.mdp"]["sha256"],
        )
        if "production.mdp" in registered_by_name
        else None
    )
    ions_mdp_ref = (
        ArtifactRef(
            artifact_id=registered_by_name["ions.mdp"]["id"],
            role="mdp",
            sha256=registered_by_name["ions.mdp"]["sha256"],
        )
        if "ions.mdp" in registered_by_name
        else None
    )

    extra_itp_artifacts = {
        name: ArtifactRef(
            artifact_id=ref["id"],
            role="parameter",
            sha256=ref["sha256"],
        )
        for name, ref in registered_by_name.items()
        if name.endswith(".itp")
    }

    gmx_engine_inputs: dict[str, ArtifactRef] = {
        "coordinates": gro_ref,
        "topology": top_ref,
        "system.gro": gro_ref,
        "topol.top": top_ref,
        **({"index": ndx_ref, "index.ndx": ndx_ref} if ndx_ref else {}),
        **({"mdp": prod_mdp_ref, "production.mdp": prod_mdp_ref} if prod_mdp_ref else {}),
        **({"ions.mdp": ions_mdp_ref} if ions_mdp_ref else {}),
        **extra_itp_artifacts,
    }

    builder_software = SoftwareRef(
        name="gromacs",
        version="2026.3",
        kind=SoftwareKind.ENGINE,
        license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
    )

    ff_lower = forcefield.lower()
    ff_family = ForceFieldFamily.CHARMM if "charmm" in ff_lower else ForceFieldFamily.AMBER

    profile_id = get_gromacs_solution_profile_id(forcefield, water_model)
    param_id = new_ulid()

    parameterization = Parameterization(
        id=param_id,
        ff_family=ff_family,
        protein_ff=forcefield,
        ligand_method="None",
        ligand_charge_model="None",
        water_model=water_model,
        ion_parameters="Standard ions",
        tool=builder_software,
        compatibility_profile_id=profile_id,
        component_force_fields={
            ForceFieldComponent.PROTEIN: ComponentForceField(family=ff_family, name=forcefield),
            ForceFieldComponent.LIGAND: ComponentForceField(family=ff_family, name="None"),
            ForceFieldComponent.WATER: ComponentForceField(family=ff_family, name=water_model),
            ForceFieldComponent.IONS: ComponentForceField(family=ff_family, name="Standard ions"),
        },
        quality={"topology_format": "GROMACS"},
        artifacts=extra_itp_artifacts,
    )

    sys_id = new_ulid()
    complex_id = new_ulid()

    system = MDSystem(
        id=sys_id,
        complex_id=complex_id,
        compound_id=None,
        form_id=None,
        parameterization_id=param_id,
        builder=builder_software,
        box=box_spec,
        n_atoms=summary.total_atoms,
        net_charge=0.0,
        composition={
            "protein_atoms": summary.solute_atoms,
            "water_molecules": summary.water_molecules,
            "positive_ions": summary.positive_ions,
            "negative_ions": summary.negative_ions,
        },
        engine_inputs={"gromacs": gmx_engine_inputs},
    )

    protocol = MDProtocol(
        stages=(
            MDStage(
                kind=MDStageKind.PRODUCTION,
                integrator="md",
                n_steps=n_steps,
                timestep_fs=effective_timestep_fs,
                temperature_K=effective_temp_k,
            ),
        )
    )

    issues = tuple(
        default_registry().run(
            "system_build",
            {"parameterization": parameterization, "md_system": system},
        )
    )

    raw_artifacts = {
        "coordinates": gro_ref,
        "topology": top_ref,
        "system.gro": gro_ref,
        "topol.top": top_ref,
        **({"index": ndx_ref, "index.ndx": ndx_ref} if ndx_ref else {}),
        **({"mdp": prod_mdp_ref, "production.mdp": prod_mdp_ref} if prod_mdp_ref else {}),
        **({"ions.mdp": ions_mdp_ref} if ions_mdp_ref else {}),
        **extra_itp_artifacts,
    }
    normalized_artifacts = {
        "coordinates": gro_ref,
        "topology": top_ref,
        "system.gro": gro_ref,
        "topol.top": top_ref,
        **({"index": ndx_ref, "index.ndx": ndx_ref} if ndx_ref else {}),
        **extra_itp_artifacts,
    }

    system_build = SystemBuildResult(
        id=new_ulid(),
        request_id=new_ulid(),
        complex_id=complex_id,
        builder=builder_software,
        parameterization=parameterization,
        system=system,
        protocol=protocol,
        raw_artifacts=raw_artifacts,
        normalized_artifacts=normalized_artifacts,
        validation_issues=issues,
    )

    plan_artifacts = {
        "coordinates": "system.gro",
        "topology": "topol.top",
        **({"md_parameters": "production.mdp"} if prod_mdp_ref else {}),
        **({"index": "index.ndx"} if ndx_ref else {}),
    }

    stage_plan = MDStagePlan(
        engine="gromacs",
        stage_index=0,
        artifacts=plan_artifacts,
    )

    return {
        "status": "success",
        "system_build": system_build.model_dump(mode="json"),
        "stage_input": stage_plan.model_dump(mode="json"),
        "info": {
            "system_id": sys_id,
            "atoms": summary.total_atoms,
            "engine": "gromacs",
            "length_ns": effective_length_ns,
            "timestep_fs": effective_timestep_fs,
            "temperature_K": effective_temp_k,
            "identity": (
                f"Local GROMACS Built ({summary.total_atoms:,d} atoms, "
                f"{summary.water_molecules:,d} waters)"
            ),
            "is_local_build": True,
            "water_molecules": summary.water_molecules,
            "positive_ions": summary.positive_ions,
            "negative_ions": summary.negative_ions,
            "box_vectors_nm": summary.box_vectors_nm,
            "box_volume_nm3": summary.box_volume_nm3,
            "target_artifact_id": target_row.id,
            "target_name": target_row.original_name,
        },
    }
