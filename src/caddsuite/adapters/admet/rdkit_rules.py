"""RDKit physicochemical descriptors, drug-likeness rules and structural alerts.

This is a rules/descriptor adapter, not an experimental ADMET predictor. RDKit remains an
optional dependency and is loaded only when this adapter is instantiated.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal, cast

from pydantic import Field, model_validator

from caddsuite.chem.standardize import ChemistryDependencyError, _rdkit
from caddsuite.contracts.base import ContractModel, SoftwareRef
from caddsuite.contracts.properties import (
    ApplicabilityDomain,
    PredictionKind,
    PropertyPrediction,
)
from caddsuite.domain.enums import LicenseClass, SoftwareKind
from caddsuite.ports.properties import PropertyPredictionRequest


class RDKitRulesParameters(ContractModel):
    """Explicit published filter limits and selected QED weighting.

    Values are configurable so a user can reproduce the conventional rule set or state a
    project-specific policy. The effective model dump belongs in run provenance.
    """

    lipinski_mw_max_Da: float = Field(default=500.0, gt=0, allow_inf_nan=False)
    lipinski_logp_max: float = Field(default=5.0, allow_inf_nan=False)
    lipinski_hbd_max: int = Field(default=5, ge=0)
    lipinski_hba_max: int = Field(default=10, ge=0)
    lipinski_pass_max_violations: int = Field(default=1, ge=0)
    veber_rotatable_bonds_max: int = Field(default=10, ge=0)
    veber_tpsa_max_A2: float = Field(default=140.0, ge=0, allow_inf_nan=False)
    ghose_mw_range_Da: tuple[float, float] = (160.0, 480.0)
    ghose_logp_range: tuple[float, float] = (-0.4, 5.6)
    ghose_molar_refractivity_range: tuple[float, float] = (40.0, 130.0)
    ghose_total_atoms_range: tuple[int, int] = (20, 70)
    egan_tpsa_max_A2: float = Field(default=131.6, ge=0, allow_inf_nan=False)
    egan_logp_max: float = Field(default=5.88, allow_inf_nan=False)
    qed_weighting: Literal["mean", "max"] = "mean"

    @model_validator(mode="after")
    def ranges_are_ordered(self) -> RDKitRulesParameters:
        for name in (
            "ghose_mw_range_Da",
            "ghose_logp_range",
            "ghose_molar_refractivity_range",
            "ghose_total_atoms_range",
        ):
            lower, upper = getattr(self, name)
            if lower >= upper:
                raise ValueError(f"{name} lower bound must be below its upper bound")
        return self


class PropertyPredictionError(ValueError):
    """Input chemistry or requested endpoint cannot be evaluated."""


class RDKitRulesPredictor:
    """Calculate classical descriptors/rules on the neutral parent by default."""

    adapter_id = "admet.rdkit_rules"
    version = "0.1.0"

    _GROUPS: ClassVar[dict[str, tuple[str, ...]]] = {
        "physicochemistry": (
            "molecular_weight",
            "crippen_logp",
            "tpsa",
            "hbd",
            "hba",
            "rotatable_bonds",
            "ring_count",
            "aromatic_ring_count",
            "heavy_atom_count",
            "total_atom_count",
            "fraction_csp3",
            "molar_refractivity",
            "formal_charge",
        ),
        "drug_likeness": (
            "lipinski_violations",
            "lipinski_pass",
            "veber_violations",
            "veber_pass",
            "ghose_violations",
            "egan_violations",
            "qed",
        ),
        "structural_alerts": (
            "pains_alerts",
            "pains_count",
            "brenk_alerts",
            "brenk_count",
        ),
        "solubility": ("esol_log_s", "esol_mg_per_ml"),
        "legacy_bioavailability_indicator": ("legacy_bioavailability_indicator",),
    }

    def __init__(self, parameters: RDKitRulesParameters | None = None) -> None:
        self.parameters = parameters or RDKitRulesParameters()
        try:
            self._Chem, self._rdBase, _rdmd, _standardize, _all_chem = _rdkit()
            from rdkit.Chem import QED, Crippen, Descriptors, Lipinski, rdMolDescriptors
            from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams
        except ImportError as exc:  # _rdkit also reports this; guard submodule imports.
            raise ChemistryDependencyError(
                "RDKit is required for rule-based property calculations; install caddsuite[chem]"
            ) from exc
        self._descriptors: Any = cast(Any, Descriptors)
        self._Crippen: Any = cast(Any, Crippen)
        self._Lipinski: Any = cast(Any, Lipinski)
        self._QED: Any = cast(Any, QED)
        self._rdMolDescriptors: Any = cast(Any, rdMolDescriptors)
        self._FilterCatalog: Any = cast(Any, FilterCatalog)
        self._FilterCatalogParams: Any = cast(Any, FilterCatalogParams)
        self.engine_version = str(self._rdBase.rdkitVersion)
        self.software = SoftwareRef(
            name="RDKit",
            version=self.engine_version,
            kind=SoftwareKind.LIBRARY,
            license_class=LicenseClass.OPEN_SOURCE_PERMISSIVE,
        )

    def supported_endpoints(self) -> frozenset[str]:
        return frozenset(
            endpoint for group in self._GROUPS.values() for endpoint in group
        ) | frozenset(self._GROUPS)

    def predict(self, request: PropertyPredictionRequest) -> tuple[PropertyPrediction, ...]:
        endpoints = self._expand_endpoints(request.endpoints)
        smiles = (
            request.form.smiles
            if request.form is not None
            else request.compound.parent.canonical_smiles
        )
        molecule = self._Chem.MolFromSmiles(smiles)
        if molecule is None:
            raise PropertyPredictionError("RDKit could not parse the selected analysis SMILES")
        if (
            request.form is None
            and self._Chem.GetFormalCharge(molecule) != request.compound.parent.formal_charge
        ):
            raise PropertyPredictionError(
                "neutral-parent SMILES formal charge does not match the compound identity"
            )

        params = self.parameters
        desc = self._descriptors
        rdmd = self._rdMolDescriptors
        mw = float(desc.MolWt(molecule))
        logp = float(self._Crippen.MolLogP(molecule))
        tpsa = float(rdmd.CalcTPSA(molecule))
        hbd = int(self._Lipinski.NumHDonors(molecule))
        hba = int(self._Lipinski.NumHAcceptors(molecule))
        rotb = int(self._Lipinski.NumRotatableBonds(molecule))
        ring_count = int(rdmd.CalcNumRings(molecule))
        aromatic_rings = int(rdmd.CalcNumAromaticRings(molecule))
        heavy = int(molecule.GetNumHeavyAtoms())
        total_atoms = int(self._Chem.AddHs(molecule).GetNumAtoms())
        csp3 = float(rdmd.CalcFractionCSP3(molecule))
        molar_refractivity = float(self._Crippen.MolMR(molecule))
        formal_charge = int(self._Chem.GetFormalCharge(molecule))

        lipinski_violations = sum(
            (
                mw > params.lipinski_mw_max_Da,
                logp > params.lipinski_logp_max,
                hbd > params.lipinski_hbd_max,
                hba > params.lipinski_hba_max,
            )
        )
        veber_violations = sum(
            (rotb > params.veber_rotatable_bonds_max, tpsa > params.veber_tpsa_max_A2)
        )
        ghose_violations = sum(
            (
                not params.ghose_mw_range_Da[0] <= mw <= params.ghose_mw_range_Da[1],
                not params.ghose_logp_range[0] <= logp <= params.ghose_logp_range[1],
                not params.ghose_molar_refractivity_range[0]
                <= molar_refractivity
                <= params.ghose_molar_refractivity_range[1],
                not params.ghose_total_atoms_range[0]
                <= total_atoms
                <= params.ghose_total_atoms_range[1],
            )
        )
        egan_violations = sum((tpsa > params.egan_tpsa_max_A2, logp > params.egan_logp_max))

        aromatic_heavy = sum(
            atom.GetIsAromatic() and atom.GetAtomicNum() > 1 for atom in molecule.GetAtoms()
        )
        aromatic_proportion = aromatic_heavy / max(heavy, 1)
        esol_log_s = 0.16 - 0.63 * logp - 0.0062 * mw + 0.066 * rotb - 0.74 * aromatic_proportion
        esol_mg_per_ml = (10**esol_log_s) * mw
        qed_function = (
            self._QED.weights_mean if params.qed_weighting == "mean" else self._QED.weights_max
        )
        qed_value = float(qed_function(molecule))

        predictions: dict[str, PropertyPrediction] = {}

        def add(
            name: str,
            value: float | int | bool | str | tuple[str, ...],
            kind: PredictionKind,
            definition: str,
            *,
            unit: str | None = None,
            model: str | None = None,
            model_version: str | None = None,
            training_data: str | None = None,
            applicability_domain: ApplicabilityDomain | None = None,
        ) -> None:
            if name in endpoints:
                predictions[name] = PropertyPrediction(
                    endpoint=name,
                    kind=kind,
                    value=value,
                    unit=unit,
                    model=model,
                    model_version=model_version,
                    training_data=training_data,
                    applicability_domain=applicability_domain,
                    definition=definition,
                )

        descriptor_definitions = {
            "molecular_weight": (
                mw,
                "Da",
                "RDKit average molecular weight; implicit hydrogens included.",
            ),
            "crippen_logp": (
                logp,
                "dimensionless",
                "RDKit Wildman-Crippen calculated octanol/water logP.",
            ),
            "tpsa": (tpsa, "angstrom^2", "RDKit topological polar surface area."),
            "hbd": (hbd, "count", "RDKit Lipinski hydrogen-bond donor count."),
            "hba": (hba, "count", "RDKit Lipinski hydrogen-bond acceptor count."),
            "rotatable_bonds": (
                rotb,
                "count",
                "RDKit Lipinski rotatable-bond count.",
            ),
            "ring_count": (ring_count, "count", "RDKit ring count."),
            "aromatic_ring_count": (
                aromatic_rings,
                "count",
                "RDKit aromatic ring count.",
            ),
            "heavy_atom_count": (heavy, "count", "Heavy atoms; hydrogen excluded."),
            "total_atom_count": (
                total_atoms,
                "count",
                "All atoms including implicit hydrogens made explicit for counting.",
            ),
            "fraction_csp3": (
                csp3,
                "dimensionless",
                "Fraction of carbon atoms assigned sp3 hybridization by RDKit.",
            ),
            "molar_refractivity": (
                molar_refractivity,
                "cm^3/mol",
                "RDKit Wildman-Crippen calculated molar refractivity.",
            ),
            "formal_charge": (
                formal_charge,
                "elementary_charge",
                "Formal molecular charge from the selected SMILES.",
            ),
        }
        for name, (descriptor_value, descriptor_unit, definition) in descriptor_definitions.items():
            add(
                name,
                descriptor_value,
                PredictionKind.CALCULATED_DESCRIPTOR,
                definition,
                unit=descriptor_unit,
            )

        rule_definitions = {
            "lipinski_violations": (
                lipinski_violations,
                "count",
                f"Number of configured Lipinski violations; "
                f"{params.lipinski_pass_max_violations} or fewer passes. Limits: "
                f"MW>{params.lipinski_mw_max_Da:g} Da, "
                f"logP>{params.lipinski_logp_max:g}, "
                f"HBD>{params.lipinski_hbd_max}, HBA>{params.lipinski_hba_max}.",
            ),
            "lipinski_pass": (
                lipinski_violations <= params.lipinski_pass_max_violations,
                None,
                f"Configured Lipinski rule pass: violations <= "
                f"{params.lipinski_pass_max_violations}; this is a heuristic screen.",
            ),
            "veber_violations": (
                veber_violations,
                "count",
                f"Number of configured Veber violations: rotatable bonds>"
                f"{params.veber_rotatable_bonds_max} or "
                f"TPSA>{params.veber_tpsa_max_A2:g} Å^2.",
            ),
            "veber_pass": (
                veber_violations == 0,
                None,
                "Configured Veber screen passes only when neither threshold is violated.",
            ),
            "ghose_violations": (
                ghose_violations,
                "count",
                f"Number of Ghose filter violations; MW {params.ghose_mw_range_Da}, "
                f"logP {params.ghose_logp_range}, molar refractivity "
                f"{params.ghose_molar_refractivity_range}, total atoms incl. H "
                f"{params.ghose_total_atoms_range}.",
            ),
            "egan_violations": (
                egan_violations,
                "count",
                f"Number of configured Egan violations: "
                f"TPSA>{params.egan_tpsa_max_A2:g} Å^2 or "
                f"logP>{params.egan_logp_max:g}.",
            ),
        }
        for name, (rule_value, rule_unit, definition) in rule_definitions.items():
            add(name, rule_value, PredictionKind.RULE, definition, unit=rule_unit)

        add(
            "qed",
            qed_value,
            PredictionKind.CALCULATED_DESCRIPTOR,
            f"RDKit QED with {params.qed_weighting} weighting; a drug-likeness "
            "desirability index, not an activity or safety probability.",
            unit="dimensionless",
            model="RDKit QED",
            model_version=self.engine_version,
        )

        alert_endpoints = {"pains_alerts", "pains_count", "brenk_alerts", "brenk_count"}
        if alert_endpoints.intersection(endpoints):
            alert_values = self._alerts(molecule)
            for name in sorted(alert_endpoints):
                if name not in endpoints:
                    continue
                catalog_key = "pains" if name.startswith("pains") else "brenk"
                catalog_name = "PAINS A/B/C" if catalog_key == "pains" else "Brenk"
                alerts = alert_values[catalog_key]
                alert_value: int | tuple[str, ...] = (
                    alerts if name.endswith("alerts") else len(alerts)
                )
                add(
                    name,
                    alert_value,
                    PredictionKind.STRUCTURAL_ALERT,
                    f"RDKit {catalog_name} FilterCatalog match(es); substructure "
                    "alerts are not toxicity predictions.",
                    unit="count" if name.endswith("count") else None,
                    model=f"RDKit FilterCatalog {catalog_name}",
                    model_version=self.engine_version,
                )

        esol_endpoints = {"esol_log_s", "esol_mg_per_ml"}
        if esol_endpoints.intersection(endpoints):
            esol_domain = ApplicabilityDomain(in_domain=None, method="not_evaluated")
            esol_data = "Delaney 2004, 2,874 measured solubilities; doi:10.1021/ci034243x"
            esol_definition = (
                "ESOL linear-regression estimate from calculated Crippen logP, MW, rotatable "
                "bonds and aromatic-heavy-atom proportion; not an experimental measurement."
            )
            add(
                "esol_log_s",
                esol_log_s,
                PredictionKind.ML_PREDICTION,
                esol_definition,
                unit="log10(mol/L)",
                model="ESOL (Delaney)",
                model_version="2004",
                training_data=esol_data,
                applicability_domain=esol_domain,
            )
            add(
                "esol_mg_per_ml",
                esol_mg_per_ml,
                PredictionKind.ML_PREDICTION,
                "ESOL-estimated molar solubility converted to mass concentration using the "
                "selected-form molecular weight; not an experimental measurement.",
                unit="mg/mL",
                model="ESOL (Delaney)",
                model_version="2004",
                training_data=esol_data,
                applicability_domain=esol_domain,
            )

        if "legacy_bioavailability_indicator" in endpoints:
            if (
                lipinski_violations <= params.lipinski_pass_max_violations
                and tpsa <= params.veber_tpsa_max_A2
            ):
                indicator = 0.55
            elif veber_violations == 0:
                indicator = 0.17
            else:
                indicator = 0.11
            add(
                "legacy_bioavailability_indicator",
                indicator,
                PredictionKind.RULE,
                "Unvalidated legacy Abbott-style constant heuristic; retained for comparison "
                "only and is not a probability or experimental bioavailability estimate.",
                unit="dimensionless",
                model="legacy_bioavailability_indicator",
                model_version=self.version,
            )

        return tuple(predictions[name] for name in endpoints)

    def _expand_endpoints(self, requested: tuple[str, ...]) -> tuple[str, ...]:
        all_endpoints = self.supported_endpoints()
        expanded: list[str] = []
        for name in requested:
            if name in self._GROUPS:
                expanded.extend(self._GROUPS[name])
            elif name in all_endpoints:
                expanded.append(name)
            else:
                raise PropertyPredictionError(f"unsupported RDKit rules endpoint/group {name!r}")
        if not expanded:
            raise PropertyPredictionError("at least one endpoint or endpoint group is required")
        if len(expanded) != len(set(expanded)):
            raise PropertyPredictionError("requested endpoint groups overlap and duplicate outputs")
        return tuple(expanded)

    def _alerts(self, molecule: Any) -> dict[str, tuple[str, ...]]:
        catalogs = self._FilterCatalogParams.FilterCatalogs

        def matches(names: tuple[Any, ...]) -> tuple[str, ...]:
            params = self._FilterCatalogParams()
            for catalog in names:
                params.AddCatalog(catalog)
            catalog = self._FilterCatalog(params)
            return tuple(sorted(entry.GetDescription() for entry in catalog.GetMatches(molecule)))

        return {
            "pains": matches((catalogs.PAINS_A, catalogs.PAINS_B, catalogs.PAINS_C)),
            "brenk": matches((catalogs.BRENK,)),
        }
