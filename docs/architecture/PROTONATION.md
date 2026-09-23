# pH-dependent ligand forms (Phase 4.3)

## Architecture

The chemistry service depends on the ProtonationEnumerator protocol, which describes the required capability without naming a vendor. DimorphiteDLProtonator is the initial adapter and is loaded lazily. A future pKa predictor or user-installed engine can implement the same protocol without changing CompoundForm or the workflow engine.

The default policy evaluates at pH 7.4 with a recorded precision and maximum variant count. Every candidate is validated by RDKit, canonicalized, de-duplicated, and checked for element-preserving heavy-atom graph isomorphism to the standardized parent. Bond-order changes are permitted because proton transfer and resonance representations may alter bond orders; a different heavy-atom skeleton is rejected. Candidate formal charge, pH, method name, and method version become a CompoundForm contract.

## Decision behavior

One distinct candidate is returned as an automatic result. Multiple candidates yield CHEM.PROTONATION_AMBIGUOUS with a structured DecisionRequest: the user can select one candidate or explicitly run all as separate forms. No candidate is assigned a population probability or ranked as more likely. An empty output, invalid candidate, possible truncation at max_variants, or heavy-atom graph change fails closed.

## Dependency and compatibility

Dimorphite-DL 2.0.2 is Apache-2.0 and its conda-forge build requires RDKit <2026. Therefore the core environment now explicitly uses the compatible RDKit 2025 series. This is an environment dependency bound, not a claim that 2025.09.6 is scientifically superior; the existing legacy docking environment remains untouched. Both versions and the protonation tool version are captured in environment and form provenance.

The upstream project documents known SMARTS/pKa edge cases, including tertiary amides being treated as basic amines in some cases. Predictions are model outputs, not measured pKa values. This limitation must remain visible to users and in generated reports. The broad biological pH range and precision affect enumeration and must be stored with run parameters.

## Validation and learning notes

Real adapter checks use acetic acid (deprotonated at pH 7.4) and trimethylamine (two possible states). A fake enumerator verifies ambiguity, deduplication, invalid outputs, empty results, truncation, and graph-change handling independently of third-party runtime behavior.

A pH-specific form is a model-generated chemical hypothesis. When more than one output is plausible, the scientifically honest workflow preserves the alternatives and asks the user how to branch. The decision is part of provenance because the chosen charge state can materially change docking, force-field parameters, and quantum calculations.
