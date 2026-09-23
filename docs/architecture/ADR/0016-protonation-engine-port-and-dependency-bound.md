# ADR-0016: Protonation engine port and dependency bound

- **Status:** Accepted (2026-09-24)
- **Date:** 2026-09-24
- **Related:** ADR-0003, ADR-0004, ADR-0012, ADR-0014

## Context

The platform needs pH-specific calculation forms but must not couple its workflow core to a single protonation implementation. ADR-0014 selects Dimorphite-DL as the initial method and requires human review when multiple states are returned. Protonation can produce several plausible outputs; they are alternatives, not model-provided population probabilities.

The current conda-forge Dimorphite-DL 2.0.2 package requires RDKit <2026. The prior core environment had RDKit 2026.03.6, so adding the adapter without recording this constraint would produce an unsatisfiable or silently altered environment.

## Decision

1. Define a small ProtonationEnumerator protocol in the chemistry service. It accepts a parent SMILES and explicit pH policy, and returns candidate SMILES. Workflow code consumes normalized CompoundForm contracts and does not call Dimorphite-DL directly.
2. Implement DimorphiteDLProtonator as the first adapter. Keep it optional and discoverable by importing only when protonation is requested.
3. Pin Dimorphite-DL 2.0.2 and constrain the caddsuite chemistry extra to RDKit >=2025.3,<2026. The Conda environment lock records the resolved Linux packages. Legacy application environments remain unchanged.
4. Validate each output, canonicalize and deduplicate it, and reject outputs that alter element-preserving heavy-atom connectivity. A single distinct form can proceed; multiple forms produce CHEM.PROTONATION_AMBIGUOUS and require selecting one or explicitly running all.
5. Persist the pH, precision, maximum variant setting, engine version, and selected form in normalized contracts and run provenance.

## Alternatives considered

- Directly import Dimorphite-DL from workflow stages: rejected because it couples orchestration to one package and makes future protonation engines invasive.
- Silently pick the first candidate: rejected because enumeration order is not a calibrated probability or scientific ranking.
- Keep RDKit 2026.03.6 and use conda Dimorphite-DL: currently unsatisfiable due to the package's declared RDKit upper bound.
- Use an unbounded pip dependency: rejected because tool/API drift weakens reproducibility.

## Consequences

Protonation behavior is replaceable at the service boundary, and ambiguous state selection is explicit. The core chemistry environment uses the compatible RDKit 2025 series. Dimorphite-DL documents edge cases, including tertiary-amide classification; its output remains a computational prediction and must be reported with method/version and limitations.

Revisit the RDKit upper bound if an upstream Dimorphite-DL release supports RDKit 2026 or an alternative adapter is selected and validated.
