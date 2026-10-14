"""Application service for running local GROMACS solution builder and CAS registration."""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.domain.identity import new_ulid
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.storage.models import ArtifactRow, ProjectArtifactRow, ProjectRow
from caddsuite.structure.gromacs_solution_builder import (
    GromacsSolutionBuilder,
    SolutionBuilderConfig,
)

logger = logging.getLogger("caddsuite.gromacs_solution_service")


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

        artifact_refs: dict[str, dict[str, Any]] = {}
        files_to_register = [
            ("coordinates", out_dir / "system.gro", "system.gro", "chemical/x-gro"),
            ("topology", out_dir / "topol.top", "topol.top", "chemical/x-top"),
            ("parameter", out_dir / "posre.itp", "posre.itp", "text/plain"),
            ("index", out_dir / "index.ndx", "index.ndx", "text/plain"),
            ("protocol", out_dir / "ions.mdp", "ions.mdp", "text/plain"),
        ]

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
                artifact_refs[role] = {
                    "id": art.id,
                    "sha256": art.sha256,
                    "role": role,
                    "original_name": orig_name,
                }

    gro_ref = artifact_refs["coordinates"]
    top_ref = artifact_refs["topology"]
    ndx_ref = artifact_refs.get("index")
    mdp_ref = artifact_refs.get("protocol")

    sys_id = new_ulid()
    build_id = new_ulid()
    n_steps = max(1000, round(((length_ns or 1.0) * 1_000_000) / (timestep_fs or 2.0)))

    system_build = {
        "schema_version": "system_build_result/1.0",
        "id": build_id,
        "request_id": new_ulid(),
        "complex_id": new_ulid(),
        "builder": {
            "adapter_id": "system_builder.gromacs_solution_builder",
            "engine": "gromacs",
            "version": "2026.3",
        },
        "parameterization": {
            "id": new_ulid(),
            "compatibility_profile_id": "caddsuite.charmm_gui.gromacs.charmm36m_cgenff_v1",
            "protein_ff": forcefield,
            "ligand_method": "None",
            "ligand_charge_model": "None",
            "water_model": water_model,
            "ion_parameters": "Standard ions",
        },
        "system": {
            "id": sys_id,
            "complex_id": new_ulid(),
            "compound_id": new_ulid(),
            "form_id": new_ulid(),
            "n_atoms": summary.total_atoms,
            "net_charge": 0,
            "parameterization_id": new_ulid(),
            "engine_inputs": {
                "gromacs": {
                    "topology": {
                        "artifact_id": top_ref["id"],
                        "role": "topology",
                        "sha256": top_ref["sha256"],
                    },
                    "coordinates": {
                        "artifact_id": gro_ref["id"],
                        "role": "coordinates",
                        "sha256": gro_ref["sha256"],
                    },
                    **(
                        {
                            "index": {
                                "artifact_id": ndx_ref["id"],
                                "role": "index",
                                "sha256": ndx_ref["sha256"],
                            }
                        }
                        if ndx_ref
                        else {}
                    ),
                    **(
                        {
                            "mdp": {
                                "artifact_id": mdp_ref["id"],
                                "role": "mdp",
                                "sha256": mdp_ref["sha256"],
                            }
                        }
                        if mdp_ref
                        else {}
                    ),
                }
            },
        },
        "protocol": {
            "stages": [
                {
                    "kind": "production",
                    "integrator": "md",
                    "n_steps": n_steps,
                    "timestep_fs": timestep_fs or 2.0,
                    "length_ns": length_ns or 1.0,
                    "temperature_K": temp_k or 300.0,
                }
            ]
        },
        "raw_artifacts": {
            "coordinates": {
                "artifact_id": gro_ref["id"],
                "role": "coordinates",
                "sha256": gro_ref["sha256"],
            },
            "topology": {
                "artifact_id": top_ref["id"],
                "role": "topology",
                "sha256": top_ref["sha256"],
            },
            **(
                {
                    "index": {
                        "artifact_id": ndx_ref["id"],
                        "role": "index",
                        "sha256": ndx_ref["sha256"],
                    }
                }
                if ndx_ref
                else {}
            ),
            **(
                {
                    "mdp": {
                        "artifact_id": mdp_ref["id"],
                        "role": "mdp",
                        "sha256": mdp_ref["sha256"],
                    }
                }
                if mdp_ref
                else {}
            ),
        },
        "normalized_artifacts": {
            "coordinates": {
                "artifact_id": gro_ref["id"],
                "role": "coordinates",
                "sha256": gro_ref["sha256"],
            },
            "topology": {
                "artifact_id": top_ref["id"],
                "role": "topology",
                "sha256": top_ref["sha256"],
            },
            **(
                {
                    "index": {
                        "artifact_id": ndx_ref["id"],
                        "role": "index",
                        "sha256": ndx_ref["sha256"],
                    }
                }
                if ndx_ref
                else {}
            ),
        },
        "validation_issues": [],
    }

    stage_input = {
        "schema_version": "md_stage_plan/1.0",
        "engine": "gromacs",
        "stage_index": 0,
        "artifacts": {
            "coordinates": {
                "artifact_id": gro_ref["id"],
                "role": "coordinates",
                "sha256": gro_ref["sha256"],
            },
            "topology": {
                "artifact_id": top_ref["id"],
                "role": "topology",
                "sha256": top_ref["sha256"],
            },
            **(
                {
                    "index": {
                        "artifact_id": ndx_ref["id"],
                        "role": "index",
                        "sha256": ndx_ref["sha256"],
                    }
                }
                if ndx_ref
                else {}
            ),
            **(
                {
                    "mdp": {
                        "artifact_id": mdp_ref["id"],
                        "role": "mdp",
                        "sha256": mdp_ref["sha256"],
                    }
                }
                if mdp_ref
                else {}
            ),
        },
    }

    return {
        "status": "success",
        "system_build": system_build,
        "stage_input": stage_input,
        "info": {
            "system_id": sys_id,
            "atoms": summary.total_atoms,
            "engine": "gromacs",
            "length_ns": length_ns or 1.0,
            "timestep_fs": timestep_fs or 2.0,
            "temperature_K": temp_k or 300.0,
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
