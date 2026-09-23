# ADR-0014: Ligand standardization and protonation policy

- **Status:** Accepted (2026-09-23; Q3 = recommendation accepted)
- **Date:** 2026-09-23
- **Related:** SCI-09, SCI-10, SCI-15, SCI-23, DOMAIN_MODEL §4.1

## Context
- The legacy apps disagree on ligand chemistry:
  - Docking neutralizes ligands (`Uncharger`) and calls the neutral form "physiologically relevant".
  - The autopilot protonates with Open Babel `-p 7.4` and silently continues unprotonated on failure.
  - The DFT app does nothing.
- 153 of 156 rows in the real docking test set are covalently bonded `[Na]` salts.
- Charge state barely affects Vina scores (no explicit electrostatics), but it **dominates** MD, MM/GBSA and QM results. The neutral forms currently flow through `complex.pdb` → CHARMM-GUI → MD.

## Decision
1. **Registry identity = standardized neutral parent.** Pipeline: MetalDisconnector → LargestFragmentChooser → Uncharger (kept from `prep_ligand.py`). The parent's InChIKey is the compound identity. Every step and its effect is recorded.
2. **Calculation forms are explicit** (`CompoundForm`). The default for docking, MD and QM is `protonated_microstate` at **pH 7.4** (configurable), generated with **Dimorphite-DL** (Apache-2.0). The tool version, pH window and precision are recorded.
   - Exactly one state within the window → used automatically (e.g. carboxylic acids deprotonated, aliphatic amines protonated).
   - More than one plausible state → **DECISION_REQUIRED**. Options: pick one, or run all as separate forms of the same compound.
3. `policy: neutral` remains available as an **explicit option**, e.g. to reproduce legacy results for regression tests. It is labelled as such in results and reports.
4. **ADMET/drug-likeness descriptors** use the **neutral parent** by default (the convention for Lipinski-type rules).
5. **Consistency checks:**
   - An MD system's ligand net charge must equal the form's formal charge (validated on CHARMM-GUI import).
   - QM uses the form's charge and multiplicity.
   - Pose strain/RMSD requires the same form (ADR-0010 rule `QM.POSE_IDENTITY`).

## Alternatives considered
| Option | Why not (as default) |
|---|---|
| Keep neutral forms | Wrong charge states for MD/MM-GBSA (SCI-09) |
| Open Babel `-p` | Crude pH model; legacy fallback was silent |
| Commercial pKa tools (Epik, MoKa, Marvin) | Licensing, not open source |
| ML pKa predictors (e.g. MolGpKa, pkasolver) | Promising; heavier dependencies and less transparent. Can be added as an alternative `ProtonationEngine` adapter later |

## Consequences
- Positive: one chemical truth per compound, with explicit and auditable forms; ambiguous chemistry reaches a human.
- Negative: more forms to manage; docking scores will differ from legacy neutral-form scores (logged as an intentional change, MIGRATION_PLAN §6).

## Revisit when
A validated pKa predictor with population estimates is adopted, or tautomer enumeration becomes necessary.

## Learning notes
Distinguish **identity** (which compound) from **form** (which protonation state or tautomer is simulated). Most silent errors between docking and MD happen in that gap.
