"""Executable AutoDock Vina stage using isolated Meeko tools and normalized contracts."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypeVar

from pydantic import ValidationError
from rdkit import Chem
from sqlalchemy.orm import Session, sessionmaker

from caddsuite.adapters.docking.meeko import (
    plan_meeko_export_command,
    plan_meeko_ligand_command,
    plan_meeko_receptor_command,
)
from caddsuite.adapters.docking.vina import (
    VinaOutputError,
    VinaParameters,
    ligand_efficiency,
    parse_vina_scores,
    plan_vina_command,
    pose_coordinate_fidelity,
    split_vina_pose_models,
)
from caddsuite.contracts.base import ArtifactRef, SoftwareRef, VersionedContract
from caddsuite.contracts.docking import DockingResult, DockingRun, DockingScore, Pose
from caddsuite.contracts.execution import ResourceRequest, SoftwareEnvironment
from caddsuite.contracts.registry import Compound, CompoundForm, Conformer
from caddsuite.contracts.structure import BindingSite, PreparedReceptor, Structure
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.domain.identity import AccessionKind, new_ulid
from caddsuite.execution.local import CommandSpec, LocalExecutor
from caddsuite.storage.accessions import next_derived_accession
from caddsuite.storage.artifacts import ArtifactStore, register_blob
from caddsuite.workflow.scheduler import StageExecutionFailure, TaskInvocation

T = TypeVar("T", bound=VersionedContract)


class VinaDockingHandler:
    """Run Meeko preparation, Vina docking, and bond-order-aware SDF normalization."""

    adapter_id = "docking.vina"
    adapter_version = "0.2.0"

    def __init__(
        self,
        *,
        vina_executable: Path,
        meeko_python: Path,
        mk_prepare_receptor: Path,
        mk_prepare_ligand: Path,
        mk_export: Path,
        vina_version: str,
        meeko_version: str,
        work_root: Path,
        log_root: Path,
        executor: LocalExecutor,
        artifact_store: ArtifactStore,
        sessions: sessionmaker[Session],
        memory_MiB: int | None = None,
        software_environment: SoftwareEnvironment | None = None,
    ) -> None:
        self.vina_executable = vina_executable.resolve(strict=True)
        self.meeko_python = meeko_python.resolve(strict=True)
        self.mk_prepare_receptor = mk_prepare_receptor.resolve(strict=True)
        self.mk_prepare_ligand = mk_prepare_ligand.resolve(strict=True)
        self.mk_export = mk_export.resolve(strict=True)
        self.vina_version = vina_version
        self.engine_version = vina_version
        self.meeko_version = meeko_version
        self.work_root = work_root.resolve()
        self.log_root = log_root.resolve()
        self.executor = executor
        self.artifact_store = artifact_store
        self.sessions = sessions
        self.memory_MiB = memory_MiB
        self.software_environment = software_environment
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.log_root.mkdir(parents=True, exist_ok=True)

    def resource_request(self, invocation: TaskInvocation) -> ResourceRequest | None:
        if self.memory_MiB is None:
            return None
        raw = invocation.task.params.get("docking_parameters", invocation.task.params)
        try:
            parameters = VinaParameters.model_validate(raw)
        except ValidationError:
            return None
        return ResourceRequest(cpu_cores=parameters.cpu_cores, memory_MiB=self.memory_MiB)

    def subject_key(self, scope: str, value: VersionedContract) -> str:
        if isinstance(value, Compound):
            return str(value.id)
        if isinstance(value, CompoundForm):
            return str(value.compound_id)
        if isinstance(value, Conformer):
            return str(value.compound_id or value.form_id)
        raise TypeError(f"Vina fan-out cannot identify {type(value).__name__}")

    def artifact_hashes(
        self, inputs: Mapping[str, tuple[VersionedContract, ...]]
    ) -> Mapping[str, str]:
        conformer = self._input(inputs, "conformer", Conformer)
        receptor = self._input(inputs, "receptor", PreparedReceptor)
        form = self._input(inputs, "form", CompoundForm)
        site = self._input(inputs, "site", BindingSite)
        pdb_artifact = receptor.artifacts.get("prepared_structure_pdb")
        if (
            conformer.structure.sha256 is None
            or pdb_artifact is None
            or pdb_artifact.sha256 is None
        ):
            raise ValueError("Vina inputs require hashed ligand and prepared-receptor artifacts")
        return {
            "ligand_conformer": conformer.structure.sha256,
            "meeko_runtime": hashlib.sha256(self.meeko_version.encode()).hexdigest(),
            "prepared_receptor_pdb": pdb_artifact.sha256,
            "compound_form_contract": hashlib.sha256(form.model_dump_json().encode()).hexdigest(),
            "prepared_receptor_contract": hashlib.sha256(
                receptor.model_dump_json().encode()
            ).hexdigest(),
            "binding_site_contract": hashlib.sha256(site.model_dump_json().encode()).hexdigest(),
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
        self._validate_inputs(compound, form, conformer, receptor, structure, site)
        try:
            raw_parameters = invocation.task.params.get(
                "docking_parameters", invocation.task.params
            )
            parameters = VinaParameters.model_validate(raw_parameters)
        except ValidationError as exc:
            raise StageExecutionFailure("DOCKING.PARAMETERS_INVALID", str(exc)) from exc

        ligand_hash = conformer.structure.sha256
        receptor_ref = receptor.artifacts.get("prepared_structure_pdb")
        if ligand_hash is None or receptor_ref is None or receptor_ref.sha256 is None:
            raise StageExecutionFailure(
                "DOCKING.INPUT_ARTIFACT_MISSING",
                "The conformer SDF and prepared receptor PDB must be registered "
                "with SHA-256 hashes.",
            )
        for label, digest in (("ligand", ligand_hash), ("receptor", receptor_ref.sha256)):
            if not self.artifact_store.verify(digest):
                raise StageExecutionFailure(
                    "DOCKING.INPUT_ARTIFACT_INVALID",
                    f"The {label} artifact {digest} is missing or its SHA-256 does not match.",
                )

        work = self.work_root / f"vina-{new_ulid()}"
        work.mkdir(mode=0o700)
        artifacts: dict[str, ArtifactRef] = {
            "source_structure": structure.raw,
            "prepared_receptor_mmcif": receptor.artifacts["prepared_structure"],
            "prepared_receptor_pdb": receptor_ref,
            "ligand_conformer_input": conformer.structure.model_copy(
                update={"role": "ligand_conformer_input_sdf"}
            ),
        }
        ligand_input_sdf = work / "ligand_input.sdf"
        shutil.copyfile(self.artifact_store.path_for(ligand_hash), ligand_input_sdf)
        receptor_pdbqt = work / "receptor.pdbqt"
        receptor_json = work / "receptor.json"
        ligand_pdbqt = work / "ligand.pdbqt"
        poses_pdbqt = work / "poses.pdbqt"
        exported_sdf = work / "poses.exported.sdf"
        receptor_command = plan_meeko_receptor_command(
            python_executable=self.meeko_python,
            script=self.mk_prepare_receptor,
            receptor_pdb=self.artifact_store.path_for(receptor_ref.sha256),
            output_pdbqt=receptor_pdbqt,
            output_json=receptor_json,
            working_directory=work,
        )
        self._run("meeko_receptor", receptor_command, artifacts)
        ligand_command = plan_meeko_ligand_command(
            python_executable=self.meeko_python,
            script=self.mk_prepare_ligand,
            ligand_sdf=ligand_input_sdf,
            output_pdbqt=ligand_pdbqt,
            working_directory=work,
        )
        self._run("meeko_ligand", ligand_command, artifacts)
        vina_command = plan_vina_command(
            executable=self.vina_executable,
            receptor_pdbqt=receptor_pdbqt,
            ligand_pdbqt=ligand_pdbqt,
            site=site,
            output_pdbqt=poses_pdbqt,
            parameters=parameters,
            working_directory=work,
        )
        self._run("vina", vina_command, artifacts)
        export_command = plan_meeko_export_command(
            python_executable=self.meeko_python,
            script=self.mk_export,
            poses_pdbqt=poses_pdbqt,
            output_sdf=exported_sdf,
            working_directory=work,
        )
        self._run("meeko_export", export_command, artifacts)

        if not all(
            path.is_file() and path.stat().st_size
            for path in (receptor_pdbqt, receptor_json, ligand_pdbqt, poses_pdbqt, exported_sdf)
        ):
            raise StageExecutionFailure(
                "DOCKING.OUTPUT_MISSING",
                "Meeko or Vina exited successfully but an expected output is missing or empty.",
            )
        self._register_file(artifacts, "meeko_receptor_pdbqt", receptor_pdbqt, "chemical/x-pdbqt")
        self._register_file(
            artifacts, "meeko_receptor_parameters", receptor_json, "application/json"
        )
        self._register_file(artifacts, "meeko_ligand_pdbqt", ligand_pdbqt, "chemical/x-pdbqt")
        self._register_file(artifacts, "vina_poses_pdbqt", poses_pdbqt, "chemical/x-pdbqt")
        self._register_file(artifacts, "meeko_export_sdf", exported_sdf, "chemical/x-mdl-sdfile")

        try:
            models = split_vina_pose_models(poses_pdbqt.read_text(encoding="utf-8"))
            scores = tuple(parse_vina_scores(model, expected_modes=1)[0] for model in models)
            if len(models) > parameters.num_modes:
                raise VinaOutputError("Vina returned more poses than the configured num_modes")
            exported: list[Any] = [
                mol for mol in Chem.SDMolSupplier(str(exported_sdf), removeHs=False) if mol
            ]
            source_mols = [
                mol
                for mol in Chem.SDMolSupplier(
                    str(self.artifact_store.path_for(ligand_hash)), removeHs=False
                )
                if mol
            ]
            if len(source_mols) != 1 or len(exported) != len(models):
                raise VinaOutputError(
                    "ligand SDF input or exported pose count does not match Vina models"
                )
            source_mol: Any = source_mols[0]
            form_mol = Chem.MolFromSmiles(form.smiles)
            if form_mol is None or source_mol.GetNumConformers() != 1:
                raise VinaOutputError("registered ligand form or conformer SDF is invalid")
            canonical = Chem.MolToSmiles(form_mol, canonical=True, isomericSmiles=True)
            source_canonical = Chem.MolToSmiles(
                Chem.RemoveHs(source_mol), canonical=True, isomericSmiles=True
            )
            if canonical != source_canonical:
                raise VinaOutputError(
                    "conformer SDF chemistry does not match the selected CompoundForm"
                )
            source_numbers = tuple(atom.GetAtomicNum() for atom in source_mol.GetAtoms())
            expected_heavy = sum(number > 1 for number in source_numbers)
            if expected_heavy != compound.parent.heavy_atom_count:
                raise VinaOutputError(
                    "selected form/conformer heavy-atom count differs from its registered compound"
                )
            if Chem.GetFormalCharge(form_mol) != form.formal_charge:
                raise VinaOutputError(
                    "selected CompoundForm formal charge disagrees with its SMILES"
                )
            engine = SoftwareRef(
                name="AutoDock Vina",
                version=self.vina_version,
                kind=SoftwareKind.ENGINE,
                license_class=LicenseClass.UNKNOWN,
            )
            adapter = SoftwareRef(
                name="CADD Suite Vina adapter",
                version=self.adapter_version,
                kind=SoftwareKind.ADAPTER,
                license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
            )
            run_id = new_ulid()
            pose_ids = tuple(new_ulid() for _ in scores)
            pose_structures: list[ArtifactRef] = []
            pose_raws: list[ArtifactRef] = []
            fidelities: list[float] = []
            for index, (model, mol) in enumerate(zip(models, exported, strict=True)):
                if (
                    mol.GetNumAtoms() != len(source_numbers)
                    or mol.GetNumHeavyAtoms() != expected_heavy
                ):
                    raise VinaOutputError(
                        f"exported pose {index + 1} atom count differs from its input form"
                    )
                pose_canonical = Chem.MolToSmiles(
                    Chem.RemoveHs(mol), canonical=True, isomericSmiles=True
                )
                if pose_canonical != canonical:
                    raise VinaOutputError(
                        f"exported pose {index + 1} connectivity/stereochemistry differs "
                        "from the selected form"
                    )
                source_heavy: Any = Chem.RemoveHs(source_mol)
                exported_heavy: Any = Chem.RemoveHs(mol)
                source_heavy_indices = tuple(
                    atom.GetIdx() for atom in source_mol.GetAtoms() if atom.GetAtomicNum() > 1
                )
                canonical_query = Chem.MolFromSmiles(canonical)
                if canonical_query is None:
                    raise VinaOutputError("selected form cannot be used as an atom-mapping query")
                source_matches = source_heavy.GetSubstructMatches(
                    canonical_query, uniquify=False, useChirality=False, maxMatches=128
                )
                export_matches = exported_heavy.GetSubstructMatches(
                    canonical_query, uniquify=False, useChirality=False, maxMatches=128
                )
                heavy_conformer = exported_heavy.GetConformer()
                heavy_coordinates = tuple(
                    (
                        float(heavy_conformer.GetAtomPosition(i).x),
                        float(heavy_conformer.GetAtomPosition(i).y),
                        float(heavy_conformer.GetAtomPosition(i).z),
                    )
                    for i in range(exported_heavy.GetNumAtoms())
                )
                heavy_numbers = tuple(atom.GetAtomicNum() for atom in exported_heavy.GetAtoms())
                mapped_fidelities = []
                mapping_errors = []
                for source_match in source_matches:
                    for export_match in export_matches:
                        exported_to_source = [0] * len(export_match)
                        for canonical_index, exported_index in enumerate(export_match):
                            exported_to_source[exported_index] = source_heavy_indices[
                                source_match[canonical_index]
                            ]
                        try:
                            deviation = pose_coordinate_fidelity(
                                model,
                                source_atomic_numbers=source_numbers,
                                exported_atomic_numbers=heavy_numbers,
                                exported_coordinates_A=heavy_coordinates,
                                exported_to_source_indices=tuple(exported_to_source),
                            )
                        except VinaOutputError as exc:
                            mapping_errors.append(str(exc))
                            continue
                        mapped_fidelities.append(deviation)
                if not mapped_fidelities:
                    raise VinaOutputError(
                        f"exported pose {index + 1} has no complete heavy-atom mapping "
                        f"to the input form: {mapping_errors[:1]}"
                    )
                fidelity = min(mapped_fidelities)
                if fidelity > 0.005:
                    raise VinaOutputError(
                        f"Meeko pose conversion shifted a heavy atom by {fidelity:.4f} A"
                    )
                pose_file = work / f"pose_{index + 1:03d}.sdf"
                with Chem.SDWriter(str(pose_file)) as writer:
                    writer.write(mol)
                raw_file = work / f"pose_{index + 1:03d}.pdbqt"
                raw_file.write_text(model, encoding="utf-8", newline="\n")
                pose_structures.append(
                    self._store_file("normalized_pose_sdf", pose_file, "chemical/x-mdl-sdfile")
                )
                pose_raws.append(
                    self._store_file("raw_vina_pose_pdbqt", raw_file, "chemical/x-pdbqt")
                )
                fidelities.append(fidelity)
        except (OSError, ValueError, VinaOutputError) as exc:
            raise StageExecutionFailure("DOCKING.RESULT_NORMALIZATION_FAILED", str(exc)) from exc

        with self.sessions.begin() as session:
            run_accession = next_derived_accession(
                session, compound.project_id, compound.accession, AccessionKind.DOCKING
            )
            pose_accessions = tuple(
                next_derived_accession(
                    session, compound.project_id, compound.accession, AccessionKind.POSE
                )
                for _ in scores
            )
        poses = tuple(
            Pose(
                id=pose_ids[i],
                accession=pose_accessions[i],
                run_id=run_id,
                rank=i + 1,
                score=DockingScore(
                    value=scores[i].affinity_kcal_mol,
                    scoring_function="vina",
                    ligand_efficiency=ligand_efficiency(
                        scores[i].affinity_kcal_mol, expected_heavy
                    ),
                ),
                rmsd_to_best_lb_A=scores[i].rmsd_to_best_lb_A,
                rmsd_to_best_ub_A=scores[i].rmsd_to_best_ub_A,
                structure=pose_structures[i],
                raw=pose_raws[i],
                fidelity_max_dev_A=fidelities[i],
            )
            for i in range(len(scores))
        )
        run = DockingRun(
            id=run_id,
            accession=run_accession,
            form_id=form.id,
            conformer_id=conformer.id,
            receptor_id=receptor.id,
            site_id=site.id,
            engine=engine,
            adapter=adapter,
            params={
                **parameters.model_dump(mode="json"),
                "scoring_function": "vina",
                "center_A": list(site.center_A),
                "size_A": list(site.size_A),
                "site_method": site.method.value,
                "meeko_version": self.meeko_version,
                "meeko_ligand_charge_model": "gasteiger",
                "meeko_ligand_index_map": True,
                "meeko_receptor_input_format": "PDB",
            },
            stochastic=True,
            seed=parameters.seed,
            pose_ids=pose_ids,
        )
        return DockingResult(run=run, poses=poses, artifacts=artifacts)

    def _validate_inputs(
        self,
        compound: Compound,
        form: CompoundForm,
        conformer: Conformer,
        receptor: PreparedReceptor,
        structure: Structure,
        site: BindingSite,
    ) -> None:
        if (
            form.compound_id != compound.id
            or conformer.form_id != form.id
            or conformer.compound_id != compound.id
        ):
            raise StageExecutionFailure(
                "DOCKING.LIGAND_IDENTITY_MISMATCH",
                "Compound, CompoundForm, and Conformer identifiers do not form one ligand lineage.",
            )
        if receptor.structure_id != structure.id or site.target_id != structure.target_id:
            raise StageExecutionFailure(
                "DOCKING.TARGET_IDENTITY_MISMATCH",
                "Prepared receptor and binding site do not refer to the supplied target structure.",
            )
        source_hash = structure.raw.sha256
        prepared_hash = receptor.artifacts.get("prepared_structure")
        if site.source_structure and site.source_structure.sha256 != source_hash:
            raise StageExecutionFailure(
                "DOCKING.SITE_FRAME_MISMATCH",
                "Binding site references a different source structure.",
            )
        if site.source_receptor and (
            prepared_hash is None or site.source_receptor.sha256 != prepared_hash.sha256
        ):
            raise StageExecutionFailure(
                "DOCKING.SITE_FRAME_MISMATCH",
                "Binding site references a different prepared receptor.",
            )
        if site.source_structure is None and site.source_receptor is None:
            raise StageExecutionFailure(
                "DOCKING.SITE_SOURCE_REQUIRED",
                "Binding site must cite the structure artifact that defines its coordinate frame.",
            )

    @staticmethod
    def _input(inputs: Mapping[str, tuple[VersionedContract, ...]], name: str, kind: type[T]) -> T:
        values = inputs.get(name, ())
        if len(values) != 1 or not isinstance(values[0], kind):
            raise StageExecutionFailure(
                "DOCKING.INPUT_CONTRACT_INVALID",
                f"Input port {name!r} requires exactly one {kind.__name__} contract.",
            )
        return values[0]

    def _run(self, name: str, command: CommandSpec, artifacts: dict[str, ArtifactRef]) -> None:
        execution = self.executor.start(command, log_dir=self.log_root).wait()
        artifacts[f"{name}_stdout"] = execution.stdout
        artifacts[f"{name}_stderr"] = execution.stderr
        if execution.exit_code != 0:
            stderr = self._artifact_text(execution.stderr, limit=4000)
            stdout = self._artifact_text(execution.stdout, limit=4000)
            details = "\n".join(part for part in (stderr, stdout) if part)
            raise StageExecutionFailure(
                f"DOCKING.{name.upper()}_FAILED",
                f"{name} exited with status {execution.exit_code}: "
                f"{details or 'see stdout/stderr artifacts'}",
            )

    def _register_file(
        self, artifacts: dict[str, ArtifactRef], key: str, path: Path, media_type: str
    ) -> None:
        artifacts[key] = self._store_file(key, path, media_type)

    def _store_file(self, kind: str, path: Path, media_type: str) -> ArtifactRef:
        blob = self.artifact_store.put_file(path)
        with self.sessions.begin() as session:
            row = register_blob(
                session,
                blob,
                kind=kind,
                media_type=media_type,
                original_name=path.name,
            )
            artifact_id = row.id
        return ArtifactRef(artifact_id=artifact_id, role=kind, sha256=blob.sha256)

    def _artifact_text(self, artifact: ArtifactRef, *, limit: int) -> str:
        if artifact.sha256 is None:
            return ""
        path = self.artifact_store.path_for(artifact.sha256)
        try:
            return path.read_text(encoding="utf-8", errors="replace")[-limit:]
        except OSError:
            return ""
