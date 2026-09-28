# Prior-art survey: workflow infrastructure for computational chemistry

**Survey date:** 2026-09-28  
**Purpose:** identify existing systems and standards that overlap with CADD Suite, inform reuse choices, and prevent unsupported novelty claims. This is a scoped engineering survey, not a systematic literature review or exhaustive market analysis.

## Findings

| Project or standard | Relevant existing capability | Implication for CADD Suite |
|---|---|---|
| [AiiDA](https://www.nature.com/articles/s41597-020-00638-4) | Open-source computational-science workflow engine with plugin interfaces, checkpointing, remote/HPC support, and automatic data provenance graphs. | Directly overlaps with general workflow orchestration and provenance. CADD Suite should not claim these concepts as novel. Its current small local-first scheduler remains a product choice for this repository's bounded initial scope; reassess if remote HPC, large-scale queues, or mature provenance query needs exceed it. |
| [BioExcel Building Blocks (BioBB)](https://pmc.ncbi.nlm.nih.gov/articles/PMC9252775/) | Reusable Python building blocks for biomolecular simulation workflows, exposed through Python, CWL, Galaxy, and notebooks. | Reuse or interoperate with established blocks where their scientific operation and license fit. Do not duplicate mature structure-preparation or simulation utilities without a validation-based reason; keep CADD contracts and provenance around imported execution steps. |
| [Galaxy computational chemistry workflows](https://training.galaxyproject.org/training-material/topics/computational-chemistry/tutorials/cheminformatics/workflows/main_workflow.html) | User-composable cheminformatics and protein-ligand docking workflows in a general workflow platform. Galaxy also has published reproducible MD workflows. | Workflow composition and accessible computational-chemistry pipelines are established. The backend can remain UI-independent; a future Galaxy/CWL export or adapter could be valuable, but is not an MVP requirement. |
| [DockStream](https://github.com/MolecularAI/DockStream) | Wrapper for multiple ligand embedders and docking engines, with parallel docking, analysis, and REINVENT integration. Repository states it is no longer maintained. | Multi-engine docking abstraction is prior art. Its maintenance status makes it a useful design/reference source, not an assumed runtime dependency. CADD Suite should demonstrate explicit capability and normalized-result behavior with its own supported adapters. |
| [MolSSI QCSchema](https://github.com/MolSSI/QCSchema) and [QCEngine](https://molssi.github.io/QCEngine/dev/single_compute.html) | Standardized quantum-chemistry input/output schema and a dispatcher across supported electronic-structure programs. | Continue aligning quantum contracts with QCSchema where semantics match. Keep platform-specific task lifecycle, artifact, environment, and provenance records alongside the interoperable QC payload rather than inventing duplicate quantum input semantics. |
| [OpenFF Interchange](https://docs.openforcefield.org/projects/interchange/en/latest/index.html) | Representation and export of parameterized molecular-mechanics systems to engines including OpenMM, GROMACS, Amber, and LAMMPS, with documented sharp edges and limitations. | Evaluate as a potential implementation component for supported force-field paths; it does not make all protein/ligand parameterization combinations universally compatible. Preserve explicit force-field, charge, water, engine, and validation metadata. |
| [KNIME medicinal/computational chemistry workflows](https://www.sciencedirect.com/science/article/pii/S2949747724000216) | Visual node-based chemistry and data-analysis workflows with broad integrations. | Visual workflow building and integrated CADD use are established. Defer a visual editor until the backend workflow definitions and compatibility checks are stable, as already planned. |

## Architecture conclusions

1. **No general novelty claim is supported.** Workflow orchestration, provenance, plugin adapters, molecular docking wrappers, biomolecular workflow blocks, and computational chemistry workflow UIs each have substantial prior art.
2. **The project's defensible contribution is currently engineering and validation work:** incrementally preserving three independently developed applications while moving them behind versioned contracts, adapter boundaries, explicit scientific compatibility checks, and reproducible local execution. This is a project-specific integration outcome, not yet a research novelty claim.
3. **A possible future research question remains unproven:** whether explicit cross-engine structure/parameterization compatibility gates reduce silent failures or improve reproducibility for docking-to-MD workflows. It would require a defined multi-engine/multi-complex dataset, baselines, and measured failure/validation outcomes before it can be framed as a research contribution.
4. **Reuse is selective, not wholesale.** AiiDA is a possible future orchestration alternative; BioBB/OpenFF Interchange/QCSchema are candidate components or interoperability standards for specific scientific tasks. Adoption requires a scoped spike covering license, API fit, data contracts, provenance fidelity, and scientific regression behavior.
5. **Current architecture decisions remain reasonable for the validated local MVP**, but are not claims that the in-house workflow engine is superior to mature workflow managers. Revisit when remote scheduling, volume, collaboration, or provenance-query requirements justify the operational cost of migration.

## Adoption decision register

| Candidate | Decision now | Revisit trigger |
|---|---|---|
| AiiDA | Do not replace the scheduler during current adapter migration; maintain an interoperability option. | Need for multi-user service, remote/HPC queues, sustained high-throughput, or provenance graph querying beyond the current local-first model. |
| BioBB | Inspect individual blocks before implementing overlapping biomolecular utilities; no blanket dependency. | A specific block passes license, environment isolation, provenance, and golden-science checks and reduces maintenance burden. |
| Galaxy / CWL | No UI/workflow-manager migration now. Consider export/import interoperability after workflow schema stabilizes. | User demand for Galaxy operation or portable workflow exchange. |
| DockStream | Use as prior-art reference; do not depend on its unmaintained repository. | A maintained fork or specific component merits independent due diligence. |
| QCSchema / QCEngine | Keep schema alignment; consider QCEngine as a candidate engine dispatch implementation, subject to adapter and environment fit. | Add a quantum engine where QCEngine materially removes adapter code without weakening CADD provenance or supported-feature checks. |
| OpenFF Interchange | Evaluate for specific parameterization/export paths; do not present it as universal topology conversion. | A validated supported protein-ligand system can be reproduced across selected engines using the relevant supported force-field path. |
| KNIME | No dependency or UI choice now. | A user-facing visual workflow requirement emerges after backend stability. |

## Sources

- Huber et al., AiiDA 1.0, *Scientific Data* (2020), https://www.nature.com/articles/s41597-020-00638-4
- BioExcel Building Blocks workflows platform, *Bioinformatics* (2022), https://pmc.ncbi.nlm.nih.gov/articles/PMC9252775/
- Galaxy Training Network, computational chemistry protein-ligand workflow, https://training.galaxyproject.org/training-material/topics/computational-chemistry/tutorials/cheminformatics/workflows/main_workflow.html
- DockStream source repository and maintenance note, https://github.com/MolecularAI/DockStream
- MolSSI QCSchema, https://github.com/MolSSI/QCSchema
- QCEngine single-compute documentation, https://molssi.github.io/QCEngine/dev/single_compute.html
- OpenFF Interchange documentation, https://docs.openforcefield.org/projects/interchange/en/latest/index.html
- OpenFF ecosystem modeling overview, https://docs.openforcefield.org/en/latest/modelling.html
- KNIME workflows for medicinal and computational chemistry, https://www.sciencedirect.com/science/article/pii/S2949747724000216
