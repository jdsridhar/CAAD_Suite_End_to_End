"""Reproducible 3D conformer generation with artifact-backed normalized output."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from io import StringIO
from typing import Annotated, Any, Literal

from pydantic import Field

from caddsuite.chem.standardize import InvalidStructure, _rdkit
from caddsuite.contracts.base import ArtifactRef, ContractModel
from caddsuite.contracts.registry import CompoundForm, Conformer
from caddsuite.domain.identity import new_ulid


class EmbeddingPolicy(ContractModel):
    """Settings that affect seeded conformer generation and minimization."""

    generator: Literal["ETKDGv3"] = "ETKDGv3"
    seed: Annotated[int, Field(ge=0, le=2_147_483_647)]
    random_coordinates_fallback: bool = True
    optimizer: Literal["MMFF94", "UFF"] | None = "MMFF94"
    max_iterations: Annotated[int, Field(ge=1)] = 2000


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """A normalized conformer record plus the in-memory molecule and SDF artifact bytes."""

    conformer: Conformer
    molecule: Any
    sdf_bytes: bytes
    warnings: tuple[str, ...]


def embed_conformer(
    form: CompoundForm,
    *,
    policy: EmbeddingPolicy,
    register_artifact: Callable[[bytes, str], ArtifactRef],
) -> EmbeddingResult:
    """Embed one calculation form and register its SDF through an injected artifact writer.

    The callback keeps filesystem/database policy out of the chemistry layer. It must store
    the supplied bytes content-addressably and return an ArtifactRef.
    """
    Chem, rdBase, _descriptors, _standardize, AllChem = _rdkit()

    molecule = Chem.MolFromSmiles(form.smiles)
    if molecule is None:
        raise InvalidStructure("RDKit could not parse the normalized CompoundForm SMILES")
    molecule = Chem.AddHs(molecule)
    params = AllChem.ETKDGv3()
    params.randomSeed = policy.seed
    status = AllChem.EmbedMolecule(molecule, params)
    if status != 0 and policy.random_coordinates_fallback:
        params.useRandomCoords = True
        status = AllChem.EmbedMolecule(molecule, params)
    if status != 0:
        raise InvalidStructure(
            f"ETKDGv3 embedding failed for form {form.id} with seed {policy.seed}"
        )

    warnings: list[str] = []
    optimizer_converged: bool | None = None
    energy: float | None = None
    if policy.optimizer == "MMFF94":
        try:
            properties = AllChem.MMFFGetMoleculeProperties(molecule, mmffVariant="MMFF94")
            if properties is None:
                warnings.append(
                    "MMFF94 parameters are unavailable; embedded geometry is unoptimized"
                )
            else:
                force_field = AllChem.MMFFGetMoleculeForceField(molecule, properties)
                if force_field is None:
                    warnings.append(
                        "MMFF94 force field could not be constructed; geometry is unoptimized"
                    )
                else:
                    status = AllChem.MMFFOptimizeMolecule(
                        molecule,
                        mmffVariant="MMFF94",
                        maxIters=policy.max_iterations,
                    )
                    optimizer_converged = status == 0
                    optimized_field = AllChem.MMFFGetMoleculeForceField(molecule, properties)
                    energy = (
                        float(optimized_field.CalcEnergy()) if optimized_field is not None else None
                    )
                    if not optimizer_converged:
                        warnings.append(
                            f"MMFF94 minimization did not converge within "
                            f"{policy.max_iterations} iterations"
                        )
        except Exception as exc:
            warnings.append(f"MMFF94 minimization failed; embedded geometry retained: {exc}")
    elif policy.optimizer == "UFF":
        try:
            if not AllChem.UFFHasAllMoleculeParams(molecule):
                warnings.append("UFF parameters are unavailable; embedded geometry is unoptimized")
            else:
                status = AllChem.UFFOptimizeMolecule(molecule, maxIters=policy.max_iterations)
                optimizer_converged = status == 0
                force_field = AllChem.UFFGetMoleculeForceField(molecule)
                energy = float(force_field.CalcEnergy()) if force_field is not None else None
                if not optimizer_converged:
                    warnings.append(
                        f"UFF minimization did not converge within "
                        f"{policy.max_iterations} iterations"
                    )
        except Exception as exc:
            warnings.append(f"UFF minimization failed; embedded geometry retained: {exc}")

    molecule.SetProp("CADDSUITE_RDKIT_VERSION", rdBase.rdkitVersion)
    molecule.SetProp("_Name", form.id)
    molecule.SetProp("CADDSUITE_FORM_ID", form.id)
    molecule.SetProp("CADDSUITE_GENERATOR", policy.generator)
    molecule.SetProp("CADDSUITE_SEED", str(policy.seed))
    if policy.optimizer:
        molecule.SetProp("CADDSUITE_OPTIMIZER", policy.optimizer)

    stream = StringIO()
    writer = Chem.SDWriter(stream)
    writer.write(molecule)
    writer.close()
    sdf_bytes = stream.getvalue().encode("utf-8")
    artifact = register_artifact(sdf_bytes, "conformer_structure")
    expected_sha256 = hashlib.sha256(sdf_bytes).hexdigest()
    if artifact.sha256 != expected_sha256:
        raise ValueError(
            "conformer artifact registration must return the SHA-256 digest of the supplied bytes"
        )

    conformer = Conformer(
        id=new_ulid(),
        form_id=form.id,
        generator=policy.generator,
        seed=policy.seed,
        n_generated=1,
        selected_by="single_embedding",
        optimizer=policy.optimizer,
        optimizer_converged=optimizer_converged,
        energy_kcal_per_mol=energy,
        structure=artifact,
    )
    return EmbeddingResult(
        conformer=conformer,
        molecule=molecule,
        sdf_bytes=sdf_bytes,
        warnings=tuple(warnings),
    )
