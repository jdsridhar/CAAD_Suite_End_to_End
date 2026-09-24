# Force-field compatibility profiles

**Status:** Phase 6.3 implementation baseline. The rule is active; the only execution-enabled built-in profile currently represents the audited CHARMM-GUI GROMACS import declaration.

## Why profiles are explicit

A single `ff_family` label is not enough to decide whether a system is compatible. A usable compatibility declaration identifies at least the protein, ligand, water and ion parameter sets, ligand charge model, topology format, and the validation that has been performed. Some mixed-component systems have documented workflows, but the existence of one such workflow does not establish compatibility for other mixtures. GROMACS guidance cautions against arbitrary mixing; OpenFF documentation demonstrates selected combinations with caveats and cross-engine energy discrepancies. See the primary-source links below.

`Parameterization` therefore records both a primary family and typed `component_force_fields`, plus a `compatibility_profile_id`. The profile registry is separate from the workflow engine and can be extended by application/plugin composition. The current rule, `FF.FAMILY_CONSISTENCY`, runs at the `system_build` boundary before an MD engine can consume the normalized system:

- Exact match to an enabled profile: pass.
- Declaration contradicts the explicitly selected profile: blocker (`FF.FAMILY_CONSISTENCY`).
- Profile absent, unknown or registered but disabled: decision required; the workflow waits for an evidence-bearing profile or human review.
- No fallback from familiar names, suffixes, or engine readability to scientific compatibility.

## Profile inventory

| Profile | Protein | Ligand | Charge model | Water | Ions | Topology format | State |
|---|---|---|---|---|---|---|---|
| `caddsuite.charmm_gui.gromacs.charmm36m_cgenff_v1` | CHARMM36m | CGenFF | CGenFF | CHARMM TIP3P | CHARMM ions | GROMACS | Enabled for audited bundle import declarations |
| AmberTools proposal | ff14SB | GAFF2 | AM1-BCC | TIP3P | explicitly selected compatible Amber ion set | AMBER; GROMACS conversion planned | Not registered; Phase 6.4 validation required |
| OpenFF/Amber proposal | Amber protein profile + OpenFF ligand profile | OpenFF Sage | Profile-specific | Profile-specific | Profile-specific | Per explicit Interchange/engine capability | Not registered; review required |

The first row is a declaration/file-consistency profile. It does not validate force-field accuracy, CGenFF penalty acceptability, protonation quality, water/ion physical behavior, or trajectory stability. Its current system-builder adapter produces GROMACS-format input only; NAMD or OpenMM require their own input bundles/converters and capability checks.

The AmberTools and OpenFF rows are plans, not executable compatibility claims. AmberTools must capture actual `tleap`/`antechamber` versions, charge model, atom typing, missing-parameter report, water/ion set, ParmEd conversion and the agreed single-point energy tolerance before a profile is enabled. OpenFF mixed-component profiles must similarly preserve per-component families and validate interaction energies for each supported output engine.

## Extension and review

A future adapter or plugin can construct `ForceFieldCompatibilityProfile` records and register them in `ForceFieldCompatibilityRegistry`; core rule logic does not need another family-specific branch. A profile review should include:

1. Exact component force-field names and versions, charge method, water and ions.
2. Protonation/charge assumptions and any patches or custom parameters.
3. Declared nonbonded combining rules, cutoffs and long-range method where relevant.
4. Accepted topology formats and engine adapter capabilities.
5. Parser/preprocessor validation and parameter-coverage checks.
6. Cross-engine or reference-energy checks when converting formats.
7. Limitations and the source evidence used to accept the profile.

Registering a profile is not itself scientific validation. Profiles marked `supported=False` require `DECISION_REQUIRED`; incompatible values under a selected profile block rather than being silently rewritten.

## Primary references

- [GROMACS 2024.1 guidance on force-field consistency and custom molecules](https://manual.gromacs.org/2024.1/how-to/special.html)
- [AmberTools tutorial: antechamber charges and GAFF parameters with ff14SB](https://ambermd.org/tutorials/basic/tutorial5/index.php)
- [OpenFF Interchange protein-ligand example](https://docs.openforcefield.org/en/latest/examples/openforcefield/openff-interchange/protein_ligand/protein_ligand.html)
- [OpenFF mixed Sage/Amber protein example](https://docs.openforcefield.org/en/latest/examples/openforcefield/openff-toolkit/using_smirnoff_with_amber_protein_forcefield/BRD4_inhibitor_benchmark.html)
