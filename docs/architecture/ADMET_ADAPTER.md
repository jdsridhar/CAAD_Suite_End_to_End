# Property-prediction adapter: RDKit rules (Phase 5.1)

## Audit and scope

The frozen `autodock-autopilot-main/analysis/admet.py` implementation computes molecular
descriptors, Lipinski/Veber/Ghose/Egan filters, PAINS and Brenk substructure alerts, QED,
ESOL, and a constant-valued Abbott-style heuristic. It has no predictive models for absorption,
clearance, CYP activity, BBB penetration, or toxicity. The previous name `ADMETPredictor`
overstates what those calculations establish. The port therefore calls them property
predictions, calculated descriptors, drug-likeness rules, or structural alerts as appropriate.

The legacy implementation also counts heavy atoms for the Ghose 20–70 criterion. The rule
is stated in terms of total atoms, so the adapter counts implicit hydrogens by making them
explicit in a temporary RDKit molecule. The calculation molecule itself is unchanged.

## Interface

`caddsuite.ports.properties.PropertyPredictor` accepts a typed request containing a `Compound`,
an optional explicit `CompoundForm`, and requested endpoint/group IDs. With no form, the adapter
uses `Compound.parent.canonical_smiles` (neutral-parent policy in ADR-0014). Each result is a
`PropertyPrediction` with a `PredictionKind`, unit, explicit definition and model details when
applicable. `RDKitRulesParameters` makes every threshold and QED weighting inspectable and
serializable. The `PropertyPredictionSet` contract links the run to its `compound_id`; its
`form_id` is empty when the neutral parent was analyzed, and its `parameters` retain effective
settings.

The port returns predictions; workflow persistence/accession assignment stays in the
application layer. RDKit is imported only when this adapter is constructed and remains an
optional `caddsuite[chem]` dependency. Unknown endpoints, malformed structures, or mismatched
compound/form lineage raise errors rather than returning an `available: false` pseudo-result.

## Preserved and corrected methods

| Output family | Method and interpretation |
|---|---|
| Physicochemistry | RDKit MolWt, Crippen logP/MR, TPSA, HBD/HBA, rotors, rings, heavy/total atoms, fraction Csp3, formal charge. Calculated descriptors, not biological endpoints. |
| Lipinski, Veber, Ghose, Egan | Configurable threshold counts/pass flags. These are heuristics for screening, not efficacy or safety classifiers. The Ghose atom count includes hydrogens. |
| PAINS, Brenk | RDKit FilterCatalog matches and descriptions. Alerts are not toxicity probabilities and do not automatically exclude compounds. |
| QED | RDKit QED with explicit mean (default) or max weighting. A desirability index, not a probability of activity or safety. |
| ESOL | Delaney linear-regression estimate and mass-concentration conversion. Applicability domain is recorded as not evaluated; the output is not a measured solubility. |
| Legacy bioavailability indicator | Available only when explicitly requested. Preserves the old 0.55/0.17/0.11 constant heuristic under a name that does not suggest a calibrated probability. |

Thresholds are defaults from the cited filters, exposed in `RDKitRulesParameters`, and must be
stored with each `PropertyPredictionSet`. The source code and adapter version are separately
recorded in workflow provenance. This adapter has no uncertainty estimate for the rule outputs;
ESOL likewise has no per-compound prediction interval here.

## Scientific references

- Lipinski et al., *Experimental and computational approaches to estimate solubility and
  permeability in drug discovery and development settings*, [DOI: 10.1016/S0169-409X(00)00129-0](https://doi.org/10.1016/S0169-409X(00)00129-0).
- Veber et al., *Molecular properties that influence the oral bioavailability of drug
  candidates*, [DOI: 10.1021/jm020017n](https://doi.org/10.1021/jm020017n).
- Ghose et al., *A Knowledge-Based Approach in Designing Combinatorial or Medicinal Chemistry
  Libraries for Drug Discovery*, [DOI: 10.1021/cc9800071](https://doi.org/10.1021/cc9800071).
- Egan et al., Prediction of Drug Absorption Using Multivariate Statistics*,
  [DOI: 10.1021/jm990146l](https://doi.org/10.1021/jm990146l).
- Bickerton et al., *Quantifying the chemical beauty of drugs*,
  [DOI: 10.1038/nchem.1243](https://doi.org/10.1038/nchem.1243).
- Delaney, *ESOL: Estimating Aqueous Solubility Directly from Molecular Structure*,
  [DOI: 10.1021/ci034243x](https://doi.org/10.1021/ci034243x).
- Baell and Holloway, *New Substructure Filters for Removal of Pan Assay Interference
  Compounds (PAINS) from Screening Libraries and for Their Exclusion in Bioassays*,
  [DOI: 10.1021/jm901137j](https://doi.org/10.1021/jm901137j).
- Brenk et al., *Lessons Learnt from Assembling Screening Libraries for Drug Discovery for
  Neglected Diseases*, [DOI: 10.1002/cmdc.200700139](https://doi.org/10.1002/cmdc.200700139).

## Learning note

The port separates **what was calculated** from **what a user may conclude**. `PredictionKind`
and the endpoint definition travel with each number so reports can preserve that distinction.
A future ML predictor can implement the same port while supplying its own model version,
training-data reference, applicability-domain method and uncertainty. The workflow layer does
not need to know whether results came from RDKit rules or a trained model.

## Optional ML predictor evaluation (ADMET-AI, 2026-09-24)

ADMET-AI is a reasonable future ML adapter candidate: its official package exposes Python/CLI prediction, and the original paper evaluated models across 41 Therapeutics Data Commons datasets. The current upstream repository identifies its `main` line as v2, trained with Chemprop v2 on updated data; it explicitly says v2 predictions differ from the published v1 paper/web-server models. PyPI lists package version 2.0.1, MIT package license, Python >=3.11, with a 14.3 MB wheel. See the [upstream README](https://github.com/swansonk14/admet_ai), [peer-reviewed paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC11226862/), and [PyPI release metadata](https://pypi.org/project/admet-ai/).

**Decision:** defer a platform adapter for now. Keep the core `caddsuite` environment free of the ML stack and run a future adapter in an isolated worker/plugin environment. Before integration, review the license terms for the exact model weights and training/reference data separately from the MIT code package; pin the package/model artifacts and hashes; map each endpoint's units and class/regression semantics; verify how uncertainty and applicability are represented (do not infer either from a score); and run a small, documented benchmark against independent examples. The peer-reviewed performance results describe the paper's v1 models and must not be attributed automatically to the separately retrained v2 package.

No ADMET-AI prediction was run in this phase. The platform therefore records no fabricated ML output and makes no accuracy claim for a future adapter.
