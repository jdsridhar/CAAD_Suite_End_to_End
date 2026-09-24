"""Executable AutoDock4 stage with Meeko normalization and common docking contracts."""

from __future__ import annotations

import hashlib
import math
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypeVar, cast

from pydantic import ValidationError
from rdkit import Chem
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.adapters.docking.autodock4 import (
    AutoDock4OutputError,
    AutoDock4Parameters,
    AutoGrid4Parameters,
    parse_autodock4_dlg,
    plan_autodock4_command,
    plan_autogrid4_command,
    render_autodock4_dpf,
    render_autogrid4_gpf,
)
from caddsuite.adapters.docking.meeko import (
    plan_meeko_export_command,
    plan_meeko_ligand_command,
    plan_meeko_receptor_command,
)
from caddsuite.adapters.docking.vina import (
    VinaOutputError,
    ligand_efficiency,
    pose_coordinate_fidelity,
)
from caddsuite.contracts.base import ArtifactRef, ContractModel, SoftwareRef, VersionedContract
from caddsuite.contracts.docking import DockingResult, DockingRun, DockingScore, Pose
from caddsuite.contracts.registry import Compound, CompoundForm, Conformer
from caddsuite.contracts.structure import BindingSite, PreparedReceptor, Structure
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import AccessionKind, new_ulid
from caddsuite.execution.local import CommandSpec, LocalExecutor
from caddsuite.storage.accessions import next_derived_accession
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.workflow.scheduler import StageExecutionFailure, TaskInvocation

T = TypeVar("T", bound=VersionedContract)


class AutoDock4TaskParameters(ContractModel):
    """Workflow-stage parameter bundle; both maps and search are fully explicit."""

    grid: AutoGrid4Parameters
    docking: AutoDock4Parameters


class AutoDock4DockingHandler:
    """Run AutoGrid4 + AutoDock4, preserving DLG and normalized pose artifacts."""

    adapter_id = "docking.autodock4"
    adapter_version = "0.1.0"

    def __init__(
        self,
        *,
        autodock_executable: Path,
        autogrid_executable: Path,
        meeko_python: Path,
        mk_prepare_receptor: Path,
        mk_prepare_ligand: Path,
        mk_export: Path,
        autodock_version: str,
        autogrid_version: str,
        meeko_version: str,
        work_root: Path,
        log_root: Path,
        executor: LocalExecutor,
        artifact_store: ArtifactStore,
        sessions: sessionmaker[Session],
    ) -> None:
        self.autodock_executable = autodock_executable.resolve(strict=True)
        self.autogrid_executable = autogrid_executable.resolve(strict=True)
        self.meeko_python = meeko_python.resolve(strict=True)
        self.mk_prepare_receptor = mk_prepare_receptor.resolve(strict=True)
        self.mk_prepare_ligand = mk_prepare_ligand.resolve(strict=True)
        self.mk_export = mk_export.resolve(strict=True)
        self.autodock_version = autodock_version
        self.autogrid_version = autogrid_version
        self.meeko_version = meeko_version
        self.engine_version = autodock_version
        self.work_root = work_root.resolve()
        self.log_root = log_root.resolve()
        self.executor = executor
        self.artifact_store = artifact_store
        self.sessions = sessions
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.log_root.mkdir(parents=True, exist_ok=True)

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        if isinstance(value, Compound):
            return str(value.id)
        if isinstance(value, CompoundForm):
            return str(value.compound_id)
        if isinstance(value, Conformer):
            return str(value.compound_id or value.form_id)
        raise TypeError(f"AutoDock4 fan-out cannot identify {type(value).__name__}")

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        conformer = self._input(inputs, "conformer", Conformer)
        receptor = self._input(inputs, "receptor", PreparedReceptor)
        form = self._input(inputs, "form", CompoundForm)
        site = self._input(inputs, "site", BindingSite)
        pdb_ref = receptor.artifacts.get("prepared_structure_pdb")
        if conformer.structure.sha256 is None or pdb_ref is None or pdb_ref.sha256 is None:
            raise ValueError("AutoDock4 requires hashed ligand SDF and prepared receptor PDB")
        return {
            "ligand_conformer": conformer.structure.sha256,
            "prepared_receptor_pdb": pdb_ref.sha256,
            "lineage": hashlib.sha256(
                "\n".join(value.model_dump_json() for value in (form, receptor, site)).encode()
            ).hexdigest(),
            "meeko_runtime": hashlib.sha256(self.meeko_version.encode()).hexdigest(),
        }

    def gate_context(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> tuple[Mapping[str, object], frozenset[str]]:
        site = self._input(inputs, "site", BindingSite)
        return (
            {"docking.site_method": site.method.value, "docking.site_volume_A3": site.volume_A3},
            frozenset({"docking.site_method", "docking.site_volume_A3"}),
        )

    def execute(self, invocation: TaskInvocation) -> DockingResult:
        compound = self._input(invocation.inputs, "compound", Compound)
        form = self._input(invocation.inputs, "form", CompoundForm)
        conformer = self._input(invocation.inputs, "conformer", Conformer)
        receptor = self._input(invocation.inputs, "receptor", PreparedReceptor)
        structure = self._input(invocation.inputs, "target_structure", Structure)
        site = self._input(invocation.inputs, "site", BindingSite)
        self._validate_lineage(compound, form, conformer, receptor, structure, site)
        try:
            parameters = AutoDock4TaskParameters.model_validate(invocation.task.params)
        except ValidationError as exc:
            raise StageExecutionFailure("DOCKING.AD4_PARAMETERS_INVALID", str(exc)) from exc

        ligand_ref = conformer.structure
        receptor_ref = receptor.artifacts.get("prepared_structure_pdb")
        if ligand_ref.sha256 is None or receptor_ref is None or receptor_ref.sha256 is None:
            raise StageExecutionFailure(
                "DOCKING.AD4_INPUT_ARTIFACT_MISSING",
                "AutoDock4 requires the hashed conformer SDF and prepared receptor PDB.",
            )
        for label, digest in (
            ("ligand SDF", ligand_ref.sha256),
            ("receptor PDB", receptor_ref.sha256),
        ):
            if not self.artifact_store.verify(digest):
                raise StageExecutionFailure(
                    "DOCKING.AD4_INPUT_ARTIFACT_INVALID",
                    f"The {label} artifact is missing or its SHA-256 does not match.",
                )

        work = self.work_root / f"autodock4-{new_ulid()}"
        work.mkdir(mode=0o700)
        ligand_input = work / "ligand_input.sdf"
        shutil.copyfile(self.artifact_store.path_for(ligand_ref.sha256), ligand_input)
        receptor_pdbqt = work / "receptor.pdbqt"
        receptor_json = work / "receptor.json"
        ligand_pdbqt = work / "ligand.pdbqt"
        receptor_cmd = plan_meeko_receptor_command(
            python_executable=self.meeko_python,
            script=self.mk_prepare_receptor,
            receptor_pdb=self.artifact_store.path_for(receptor_ref.sha256),
            output_pdbqt=receptor_pdbqt,
            output_json=receptor_json,
            working_directory=work,
        )
        logs: dict[str, ArtifactRef] = {}
        self._run("meeko_receptor", receptor_cmd, logs)
        ligand_cmd = plan_meeko_ligand_command(
            python_executable=self.meeko_python,
            script=self.mk_prepare_ligand,
            ligand_sdf=ligand_input,
            output_pdbqt=ligand_pdbqt,
            working_directory=work,
        )
        self._run("meeko_ligand", ligand_cmd, logs)
        if (
            not receptor_pdbqt.is_file()
            or not receptor_json.is_file()
            or not ligand_pdbqt.is_file()
        ):
            raise StageExecutionFailure(
                "DOCKING.AD4_PREPARATION_OUTPUT_MISSING",
                "Meeko exited successfully without producing all required PDBQT and JSON outputs.",
            )
        self._register_file(logs, "meeko_receptor_pdbqt", receptor_pdbqt, "chemical/x-pdbqt")
        self._register_file(logs, "meeko_receptor_metadata", receptor_json, "application/json")
        self._register_file(logs, "meeko_ligand_pdbqt", ligand_pdbqt, "chemical/x-pdbqt")

        receptor_types = self._atom_types(receptor_pdbqt)
        ligand_types = self._atom_types(ligand_pdbqt)
        grid_stem = "receptor"
        gpf_path = work / "receptor.gpf"
        gpf_text = render_autogrid4_gpf(
            receptor_pdbqt=receptor_pdbqt.name,
            map_stem=grid_stem,
            receptor_types=receptor_types,
            ligand_types=ligand_types,
            site=site,
            parameters=parameters.grid,
        )
        gpf_path.write_text(gpf_text, encoding="utf-8", newline="\n")
        self._register_file(logs, "autogrid4_gpf", gpf_path, "text/plain")
        glg_path = work / "receptor.glg"
        grid_cmd = plan_autogrid4_command(
            executable=self.autogrid_executable,
            gpf_file=gpf_path,
            glg_file=glg_path,
            working_directory=work,
        )
        self._run("autogrid4", grid_cmd, logs)
        map_files = tuple(work.glob("receptor.*.map"))
        field_file = work / "receptor.maps.fld"
        expected_maps = len(ligand_types) + 2
        if len(map_files) != expected_maps or not field_file.is_file():
            raise StageExecutionFailure(
                "DOCKING.AD4_MAPS_MISSING",
                f"AutoGrid4 produced {len(map_files)} maps and field={field_file.is_file()}, "
                f"expected {expected_maps} maps plus receptor.maps.fld.",
            )
        self._register_file(logs, "autogrid4_log", glg_path, "text/plain")
        self._register_file(logs, "autogrid4_field", field_file, "application/octet-stream")
        for map_path in map_files:
            self._register_file(
                logs, f"autogrid4_{map_path.name}", map_path, "application/octet-stream"
            )

        torsdof = self._torsdof(ligand_pdbqt)
        about = self._ligand_center(ligand_pdbqt)
        dpf_path = work / "ligand.dpf"
        dpf_path.write_text(
            render_autodock4_dpf(
                ligand_pdbqt=ligand_pdbqt.name,
                map_stem=grid_stem,
                ligand_types=ligand_types,
                torsdof=torsdof,
                about_A=about,
                parameters=parameters.docking,
            ),
            encoding="utf-8",
            newline="\n",
        )
        self._register_file(logs, "autodock4_dpf", dpf_path, "text/plain")
        dlg_path = work / "ligand.dlg"
        dock_cmd = plan_autodock4_command(
            executable=self.autodock_executable,
            dpf_file=dpf_path,
            dlg_file=dlg_path,
            working_directory=work,
        )
        self._run("autodock4", dock_cmd, logs)
        if not dlg_path.is_file() or not dlg_path.stat().st_size:
            raise StageExecutionFailure(
                "DOCKING.AD4_DLG_MISSING", "AutoDock4 produced no non-empty DLG file."
            )
        self._register_file(logs, "autodock4_dlg", dlg_path, "text/plain")
        try:
            outputs = parse_autodock4_dlg(dlg_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, AutoDock4OutputError) as exc:
            raise StageExecutionFailure("DOCKING.AD4_DLG_INVALID", str(exc)) from exc

        exported_sdf = work / "exported_poses.sdf"
        export_cmd = plan_meeko_export_command(
            python_executable=self.meeko_python,
            script=self.mk_export,
            poses_pdbqt=dlg_path,
            output_sdf=exported_sdf,
            working_directory=work,
            all_dlg_poses=True,
        )
        self._run("meeko_export", export_cmd, logs)
        if not exported_sdf.is_file() or not exported_sdf.stat().st_size:
            raise StageExecutionFailure(
                "DOCKING.AD4_SDF_MISSING", "Meeko did not export normalized pose SDF records."
            )
        self._register_file(logs, "meeko_export_sdf", exported_sdf, "chemical/x-mdl-sdfile")
        return self._normalize(
            compound=compound,
            form=form,
            conformer=conformer,
            receptor=receptor,
            site=site,
            parameters=parameters,
            outputs=outputs,
            structure=structure,
            exported_sdf=exported_sdf,
            ligand_input=ligand_input,
            logs=logs,
        )

    def _normalize(
        self,
        *,
        compound: Compound,
        form: CompoundForm,
        conformer: Conformer,
        receptor: PreparedReceptor,
        site: BindingSite,
        parameters: AutoDock4TaskParameters,
        outputs: tuple[Any, ...],
        structure: Structure,
        exported_sdf: Path,
        ligand_input: Path,
        logs: dict[str, ArtifactRef],
    ) -> DockingResult:
        try:
            poses = [
                molecule
                for molecule in Chem.SDMolSupplier(str(exported_sdf), removeHs=False)
                if molecule is not None
            ]
            sources = [
                molecule
                for molecule in Chem.SDMolSupplier(str(ligand_input), removeHs=False)
                if molecule is not None
            ]
            if len(sources) != 1 or len(poses) != len(outputs):
                raise AutoDock4OutputError(
                    f"DLG has {len(outputs)} scored models; Meeko exported {len(poses)} SDF poses"
                )
            source = sources[0]
            form_mol = Chem.MolFromSmiles(form.smiles)
            if form_mol is None:
                raise AutoDock4OutputError("selected compound form has invalid SMILES")
            canonical = Chem.MolToSmiles(form_mol, canonical=True, isomericSmiles=True)
            source_heavy = Chem.RemoveHs(source)
            source_canonical = Chem.MolToSmiles(source_heavy, canonical=True, isomericSmiles=True)
            if canonical != source_canonical:
                raise AutoDock4OutputError("ligand input chemistry differs from the selected form")
            source_numbers = tuple(atom.GetAtomicNum() for atom in cast(Any, source).GetAtoms())
            if source_heavy.GetNumAtoms() != compound.parent.heavy_atom_count:
                raise AutoDock4OutputError("ligand heavy-atom count differs from compound identity")
            query = Chem.MolFromSmiles(canonical)
            if query is None:
                raise AutoDock4OutputError("selected form cannot be used as an atom-mapping query")
            source_indices = tuple(
                i for i, atom in enumerate(cast(Any, source).GetAtoms()) if atom.GetAtomicNum() > 1
            )
            source_matches = source_heavy.GetSubstructMatches(
                query, uniquify=False, useChirality=False, maxMatches=128
            )
            normalized: list[tuple[float, Any, ArtifactRef, ArtifactRef, float, int]] = []
            for output, molecule in zip(outputs, poses, strict=True):
                molecule_heavy = Chem.RemoveHs(molecule)
                if (
                    Chem.MolToSmiles(molecule_heavy, canonical=True, isomericSmiles=True)
                    != canonical
                ):
                    raise AutoDock4OutputError(
                        f"Meeko pose for AD4 run {output.run_index} changed ligand identity"
                    )
                exported_matches = molecule_heavy.GetSubstructMatches(
                    query, uniquify=False, useChirality=False, maxMatches=128
                )
                heavy_conf = molecule_heavy.GetConformer()
                xyz = tuple(
                    (
                        float(heavy_conf.GetAtomPosition(i).x),
                        float(heavy_conf.GetAtomPosition(i).y),
                        float(heavy_conf.GetAtomPosition(i).z),
                    )
                    for i in range(molecule_heavy.GetNumAtoms())
                )
                numbers = tuple(
                    atom.GetAtomicNum() for atom in cast(Any, molecule_heavy).GetAtoms()
                )
                deviations: list[float] = []
                for source_match in source_matches:
                    for exported_match in exported_matches:
                        mapping = [0] * len(exported_match)
                        for canonical_index, exported_index in enumerate(exported_match):
                            mapping[exported_index] = source_indices[source_match[canonical_index]]
                        try:
                            deviations.append(
                                pose_coordinate_fidelity(
                                    output.pdbqt_text,
                                    source_atomic_numbers=source_numbers,
                                    exported_atomic_numbers=numbers,
                                    exported_coordinates_A=xyz,
                                    exported_to_source_indices=tuple(mapping),
                                )
                            )
                        except VinaOutputError:
                            continue
                if not deviations:
                    raise AutoDock4OutputError(
                        f"no complete atom-index mapping for AD4 run {output.run_index}"
                    )
                fidelity = min(deviations)
                if fidelity > 0.005:
                    raise AutoDock4OutputError(
                        f"Meeko pose conversion shifted a heavy atom by {fidelity:.4f} A"
                    )
                pose_file = exported_sdf.parent / f"pose_run_{output.run_index:04d}.sdf"
                with Chem.SDWriter(str(pose_file)) as writer:
                    writer.write(molecule)
                raw_file = exported_sdf.parent / f"pose_run_{output.run_index:04d}.pdbqt"
                raw_file.write_text(output.pdbqt_text, encoding="utf-8", newline="\n")
                pose_ref = self._store_file(
                    "normalized_pose_sdf", pose_file, "chemical/x-mdl-sdfile"
                )
                raw_ref = self._store_file("raw_autodock4_pose_pdbqt", raw_file, "chemical/x-pdbqt")
                normalized.append(
                    (output.score_kcal_mol, molecule, pose_ref, raw_ref, fidelity, output.run_index)
                )
        except (OSError, ValueError, VinaOutputError, AutoDock4OutputError) as exc:
            raise StageExecutionFailure("DOCKING.AD4_NORMALIZATION_FAILED", str(exc)) from exc

        ordered = sorted(normalized, key=lambda item: (item[0], item[5]))
        with self.sessions.begin() as session:
            run_accession = next_derived_accession(
                session, compound.project_id, compound.accession, AccessionKind.DOCKING
            )
            pose_accessions = tuple(
                next_derived_accession(
                    session, compound.project_id, compound.accession, AccessionKind.POSE
                )
                for _ in ordered
            )
        run_id = new_ulid()
        pose_ids = tuple(new_ulid() for _ in ordered)
        poses_out = tuple(
            Pose(
                id=pose_ids[index],
                accession=pose_accessions[index],
                run_id=run_id,
                rank=index + 1,
                score=DockingScore(
                    value=score,
                    scoring_function="autodock4",
                    ligand_efficiency=ligand_efficiency(score, compound.parent.heavy_atom_count),
                ),
                structure=pose_ref,
                raw=raw_ref,
                fidelity_max_dev_A=fidelity,
            )
            for index, (score, _mol, pose_ref, raw_ref, fidelity, _run) in enumerate(ordered)
        )
        receptor_ref = receptor.artifacts["prepared_structure_pdb"]
        run = DockingRun(
            id=run_id,
            accession=run_accession,
            form_id=form.id,
            conformer_id=conformer.id,
            receptor_id=receptor.id,
            site_id=site.id,
            engine=SoftwareRef(
                name="AutoDock4",
                version=self.autodock_version,
                kind=SoftwareKind.ENGINE,
                license_class=LicenseClass.OPEN_SOURCE_COPYLEFT,
            ),
            adapter=SoftwareRef(
                name=self.adapter_id,
                version=self.adapter_version,
                kind=SoftwareKind.ADAPTER,
                license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
            ),
            params={
                **parameters.model_dump(mode="json"),
                "grid_center_A": list(site.center_A),
                "grid_size_A": list(site.size_A),
                "site_method": site.method.value,
                "autogrid4_version": self.autogrid_version,
                "meeko_version": self.meeko_version,
                "ligand_charge_model": "gasteiger",
                "pose_order": "ascending_autodock4_scoring_function_value_then_run_index",
            },
            stochastic=True,
            seed=parameters.docking.seed[0],
            pose_ids=pose_ids,
        )
        artifacts = {
            "source_structure": self._input_from_store(structure.raw),
            "prepared_receptor_pdb": receptor_ref,
            "ligand_conformer_input": conformer.structure.model_copy(
                update={"role": "ligand_conformer_input_sdf"}
            ),
            **logs,
        }
        return DockingResult(run=run, poses=poses_out, artifacts=artifacts)

    def _validate_lineage(
        self,
        compound: Compound,
        form: CompoundForm,
        conformer: Conformer,
        receptor: PreparedReceptor,
        structure: Structure,
        site: BindingSite,
    ) -> None:
        if form.compound_id != compound.id or conformer.form_id != form.id:
            raise StageExecutionFailure(
                "DOCKING.AD4_LIGAND_LINEAGE", "Ligand input lineage does not match selected form."
            )
        if conformer.compound_id not in (None, compound.id):
            raise StageExecutionFailure(
                "DOCKING.AD4_LIGAND_LINEAGE", "Conformer belongs to another compound."
            )
        if receptor.structure_id != structure.id:
            raise StageExecutionFailure(
                "DOCKING.AD4_RECEPTOR_LINEAGE", "Prepared receptor belongs to another structure."
            )
        if site.target_id != structure.target_id:
            raise StageExecutionFailure(
                "DOCKING.AD4_SITE_TARGET",
                "Binding site and receptor structure refer to different targets.",
            )
        if site.source_structure is not None:
            if site.source_structure.sha256 != structure.raw.sha256:
                raise StageExecutionFailure(
                    "DOCKING.AD4_SITE_FRAME",
                    "Binding site cites a different source-structure coordinate frame.",
                )
        elif site.source_receptor is not None:
            prepared_structure = receptor.artifacts.get("prepared_structure")
            if (
                prepared_structure is None
                or site.source_receptor.sha256 != prepared_structure.sha256
            ):
                raise StageExecutionFailure(
                    "DOCKING.AD4_SITE_FRAME",
                    "Binding site cites a different prepared-receptor coordinate frame.",
                )
        else:
            raise StageExecutionFailure(
                "DOCKING.AD4_SITE_FRAME",
                "Binding site must cite its source structure or prepared receptor frame.",
            )

    @staticmethod
    def _atom_types(pdbqt: Path) -> tuple[str, ...]:
        atom_types: set[str] = set()
        for line in pdbqt.read_text(encoding="utf-8").splitlines():
            if line.startswith(("ATOM", "HETATM")):
                fields = line.split()
                if len(fields) < 2:
                    raise StageExecutionFailure(
                        "DOCKING.AD4_ATOM_TYPES", "Malformed PDBQT atom line."
                    )
                atom_types.add(fields[-1])
        if not atom_types:
            raise StageExecutionFailure(
                "DOCKING.AD4_ATOM_TYPES", f"No atom types found in {pdbqt.name}."
            )
        return tuple(sorted(atom_types))

    @staticmethod
    def _torsdof(pdbqt: Path) -> int:
        records = [
            line.split()
            for line in pdbqt.read_text(encoding="utf-8").splitlines()
            if line.startswith("TORSDOF")
        ]
        if len(records) != 1 or len(records[0]) != 2:
            raise StageExecutionFailure(
                "DOCKING.AD4_TORSDOF", "Ligand PDBQT must contain one TORSDOF record."
            )
        try:
            return int(records[0][1])
        except ValueError as exc:
            raise StageExecutionFailure(
                "DOCKING.AD4_TORSDOF", "Ligand TORSDOF is not an integer."
            ) from exc

    @staticmethod
    def _ligand_center(pdbqt: Path) -> tuple[float, float, float]:
        coordinates = []
        for line in pdbqt.read_text(encoding="utf-8").splitlines():
            if line.startswith(("ATOM", "HETATM")):
                try:
                    coordinates.append(
                        tuple(float(line[start : start + 8]) for start in (30, 38, 46))
                    )
                except ValueError as exc:
                    raise StageExecutionFailure(
                        "DOCKING.AD4_LIGAND_COORDINATES", "Malformed ligand PDBQT coordinates."
                    ) from exc
        if not coordinates or not all(
            math.isfinite(value) for point in coordinates for value in point
        ):
            raise StageExecutionFailure(
                "DOCKING.AD4_LIGAND_COORDINATES", "Ligand PDBQT has no finite atom coordinates."
            )
        n = len(coordinates)
        return tuple(sum(point[axis] for point in coordinates) / n for axis in range(3))  # type: ignore[return-value]

    def _run(self, name: str, command: CommandSpec, artifacts: dict[str, ArtifactRef]) -> None:
        execution = self.executor.start(command, log_dir=self.log_root).wait()
        artifacts[f"{name}_stdout"] = execution.stdout
        artifacts[f"{name}_stderr"] = execution.stderr
        if execution.exit_code != 0:
            details = self._artifact_text(execution.stderr, 4000) or self._artifact_text(
                execution.stdout, 4000
            )
            raise StageExecutionFailure(
                f"DOCKING.{name.upper()}_FAILED",
                f"{name} exited {execution.exit_code}: {details or 'inspect task logs'}",
            )

    def _register_file(
        self, artifacts: dict[str, ArtifactRef], key: str, path: Path, media_type: str
    ) -> None:
        artifacts[key] = self._store_file(key, path, media_type)

    def _store_file(self, kind: str, path: Path, media_type: str) -> ArtifactRef:
        blob = self.artifact_store.put_file(path)
        with self.sessions.begin() as session:
            row = register_blob(
                session, blob, kind=kind, media_type=media_type, original_name=path.name
            )
            artifact_id = row.id
        return ArtifactRef(artifact_id=artifact_id, role=kind, sha256=blob.sha256)

    def _input_from_store(self, artifact: ArtifactRef) -> ArtifactRef:
        return artifact.model_copy(update={"role": "source_structure"})

    def _artifact_text(self, artifact: ArtifactRef, limit: int) -> str:
        if artifact.sha256 is None:
            return ""
        try:
            return self.artifact_store.path_for(artifact.sha256).read_text(
                encoding="utf-8", errors="replace"
            )[-limit:]
        except OSError:
            return ""

    @staticmethod
    def _input(inputs: Mapping[str, tuple[VersionedContract, ...]], name: str, kind: type[T]) -> T:
        values = inputs.get(name, ())
        if len(values) != 1 or not isinstance(values[0], kind):
            raise StageExecutionFailure(
                "DOCKING.AD4_INPUT_CONTRACT_INVALID",
                f"Input port {name!r} requires exactly one {kind.__name__} contract.",
            )
        return values[0]
