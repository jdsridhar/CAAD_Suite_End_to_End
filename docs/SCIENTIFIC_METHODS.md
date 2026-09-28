# Scientific methods and validation index

This index points to the method-specific implementation and evidence. Results are computational predictions and must not be described as experimental validation.

| Area | Implementation / assumptions | Validation and limits |
|---|---|---|
| Chemical identity and protonation | [Standardization](architecture/CHEMISTRY_STANDARDIZATION.md), [protonation](architecture/PROTONATION.md), ADR-0014 | Identity policy and ambiguous microstates are explicit; model pH is not a claim of a single biological protonation state. |
| Protein source, preparation, binding site | [Structure source](architecture/STRUCTURE_SOURCE.md), [protein preparation](architecture/PROTEIN_PREPARATION.md), [binding site](architecture/BINDING_SITE.md) | Preserve source structures and hashes; missing residues, removed heterogens, and site choice are provenance. |
| Docking | [Vina adapter](architecture/VINA_ADAPTER.md), [AutoDock4 adapter](architecture/AUTODOCK4_ADAPTER.md) | [Pinned redocking protocol](validation/REDOCKING_PILOT_V1.md), [results and compatibility failures](validation/G-DOCK-8.md), [CPU timing](validation/G-DOCK-9.md). The top pose missed the predeclared 2 Å cutoff for the only case that reached Vina. |
| Docking pose to MD complex | [Coordinate assembly](architecture/COMPLEX_ASSEMBLY.md), [force-field compatibility](architecture/FORCE_FIELD_COMPATIBILITY.md), [system-builder audit](architecture/SYSTEM_BUILDER_AUDIT.md) | Coordinate assembly is not parameterization. Compatibility choices and unresolved inputs must be surfaced before MD. |
| MD | [GROMACS](architecture/GROMACS_MD_ADAPTER.md), [OpenMM](architecture/OPENMM_MD_ADAPTER.md), [MD runtime](architecture/MD_RUNTIME.md) | See the linked G-MD validation records. Short integration tests validate execution and selected observables, not long-time stability or predictive binding accuracy. |
| Trajectory metrics | [Analysis input policy](architecture/TRAJECTORY_ANALYSIS.md), [plotting](architecture/TRAJECTORY_PLOTTING.md), [H-bonds](architecture/GROMACS_HBOND_ANALYSIS.md) | Metric selection, alignment, PBC handling, frame selection, and topology limitations must be reported. |
| MM/GBSA | [Legacy audit](architecture/MMGBSA_AUDIT.md) and G-MD-17/18/19 validation records | Approximate end-point estimate; frame correlation, sampling, entropy omissions, force field, and uncertainty affect interpretation. It is not exact experimental binding free energy. |
| DFT/QM | [Psi4](architecture/PSI4_ADAPTER.md), [PySCF](architecture/PYSCF_ADAPTER.md), [conceptual DFT](architecture/CONCEPTUAL_DFT_AUDIT.md) | Small-molecule calculations validate code paths and properties under their stated electronic-structure model; they do not establish target binding or activity. |
| ADMET and ranking | [ADMET adapter](architecture/ADMET_ADAPTER.md), [candidate ranking](architecture/CANDIDATE_RANKING.md) | Descriptor/rule/model outputs retain method and limitations. User-defined ranking criteria are not biological truth. |
| Reporting | [Scientific report](architecture/SCIENTIFIC_REPORTING.md), [rendering](architecture/REPORT_RENDERING.md) | Report must preserve methods, raw normalized evidence, uncertainties/warnings, and computational-vs-experimental distinction. |

Always inspect the specific run's normalized contract, parameters, warnings, source hashes, engine/software environment, and TaskAttempt provenance before interpreting a result. The architecture audit and [`TODO.md`](../TODO.md) retain known scientific risks and uncompleted validation gates.
