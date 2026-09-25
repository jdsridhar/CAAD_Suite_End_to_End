# Phase 6.4 audit — AmberTools/tleap + ParmEd builder

**Status:** audit, builder, and real conversion/energy and native OpenMM smoke regressions are complete. The Amber-to-GROMACS compatibility profile remains disabled pending a multi-system benchmark and a justified acceptance tolerance. A separate native Amber profile is enabled only for the narrowly validated OpenMM input path described below. The existing AmberTools, GROMACS and OpenMM installations were used without modification; no legacy or user MD dataset was changed.

## Existing platform boundary

- `Complex` is explicitly coordinate-only and links receptor/ligand artifacts to compound, form, target and pose IDs. Its protein artifact is the prepared receptor PDB and its ligand artifact is the normalized docked-pose SDF.
- `SystemBuildRequest` provides stable input artifact hashes, linked lineage, named selections and explicit parameters. `SystemBuilder` produces `Parameterization`, `MDSystem`, normalized `MDProtocol`, artifact refs and validation issues.
- Existing stage workers are stdlib-only JSON subprocesses. They run in foreign Conda environments and do not import the Python 3.12 platform core (ADR-0002). `LocalExecutor` receives argv arrays with `shell=False`; this is appropriate for AmberTools.
- The legacy MD app has no tleap/AmberTools builder. All audited MD system construction was manual CHARMM-GUI; its scripts consume completed GROMACS bundles.

## Read-only environment inventory (2026-09-24)

| Component | Observed installation | Notes |
|---|---|---|
| AmberTools | `/home/sridhar/miniconda3/envs/gmxMMPBSA`; Conda package 23.6; Python 3.9 | `tleap`, `antechamber`, `parmchk2`, `sqm`, and `pdb4amber` executables present |
| Antechamber | Startup banner reports 22.0 | Preserve package version and executable banner separately in provenance; do not infer they are identical |
| ParmEd | 4.3.0, in same Python 3.9 environment | LGPL-2.1-or-later; Python API exposes `GromacsTopologyFile.write` and `GromacsGroFile.write` |
| GROMACS | separate `/home/sridhar/miniconda3/envs/gmx/bin/gmx`; version 2026.3-conda_forge | CUDA-enabled; neither `gmx` nor ACPYPE is installed in the AmberTools environment |
| Force-field data | `leaprc.protein.ff14SB`, `leaprc.gaff2`, `leaprc.water.tip3p`, `frcmod.ionsjc_tip3p` exist under AmberTools data | The TIP3P leaprc documents the included Joung–Cheatham monovalent set; these exact installed bytes must be hashed into provenance |

AmberTools' Conda package metadata reports multiple upstream licenses (GPL/LGPL/BSD/MIT). Do not bundle it or its data into the Apache-2.0 platform distribution. Invoke a user-installed environment as a separate process, record its versions and parameter-file digests, and document its licensing. The existing environment was not changed.

## Relevant tool contracts observed

- `tleap -f <input>` is shell-free and accepts an explicit script file.
- `antechamber` accepts SDF input, explicit net charge (`-nc`), AM1-BCC (`-c bcc`) and GAFF2 typing (`-at gaff2`). The charge must be supplied from the selected ligand form; it is not guessed.
- `parmchk2` supports GAFF2 and emits an `frcmod`; inferred/missing parameters must be inspected and surfaced before claiming a supported profile.
- ParmEd's installed API directly reads Amber `prmtop` + `inpcrd` and writes GROMACS topology/GRO files. The adapter should use a version-pinned isolated worker and validate atom identity/order/coordinates after conversion; no interactive CLI commands or shell string are needed.
- GROMACS 2026.3 is available separately for topology preprocessing and the planned single-point cross-engine energy check.

Primary software references: [AmberTools tutorial using ff14SB with Antechamber/GAFF](https://ambermd.org/tutorials/basic/tutorial5/index.php), [ParmEd GROMACS writer API](https://parmed.github.io/ParmEd/html/api/parmed/parmed.gromacs.gromacstop.html), [ParmEd GROMACS format notes](https://parmed.github.io/ParmEd/html/gromacs.html), [GROMACS guidance on force-field consistency](https://manual.gromacs.org/2024.1/how-to/special.html).

## Design constraints before enabling an Amber profile

1. Require the input `Complex` and exact protein-PDB/ligand-SDF artifact references to agree by IDs and hashes. Reject any ambiguous ligand identity, unsupported residue, missing heavy atom, invalid formal charge, or mismatch between ligand graph and generated MOL2.
2. Require explicit parameters for protein force field, GAFF2/AM1-BCC, integer ligand charge, TIP3P, ion set, solvent padding, water/ion treatment, and any protein microstate/terminal patches. Do not silently infer histidine states or salt concentration.
3. Preserve `antechamber`, `sqm`, `parmchk2`, `tleap`, and ParmEd logs and intermediate files. Map missing/guessed parameters, residue-template failures, non-integral net charge, and unsupported topology features to structured errors/decisions.
4. Hash the actual AmberTools leaprc/frcmod parameter files used, in addition to recording package/tool versions, request parameters, worker version, input hashes and command argv.
5. Keep native AMBER `prmtop`/`inpcrd` as raw outputs. Generate GROMACS files only through ParmEd's API in its isolated Python 3.9 environment; compare atom counts, names, residue mapping, charges, box and coordinates after conversion. Select the native Amber profile for a native Amber consumer and the distinct GROMACS profile only for the converted files.
6. Execute GROMACS topology preprocessing without `-maxwarn`. For the comparison-only single-point check, explicitly align the energy reference: Sander `vdwmeth=0`, GROMACS `DispCorr=no`, and GROMACS `coulomb-modifier=None` / `vdw-modifier=None`. GROMACS documents `None` as the unmodified potential and as useful for cross-software energy comparisons ([GROMACS 2026.3 MDP reference](https://manual.gromacs.org/current/user-guide/mdp-options.html)). These settings are comparison controls, not a production MD protocol.
7. Record HMR as unknown unless explicitly performed and verified; do not infer it from a 4 fs timestep.
8. Preserve the Amber and GROMACS single-point terms, their component breakdown, effective parameters, and the measured difference. A converted topology is still not accepted solely because `grompp` succeeds.

## Real execution evidence

The opt-in regression is documented in [`../validation/G-MD-5.md`](../validation/G-MD-5.md). With AmberTools 23.6 (Antechamber banner 22.0), ParmEd 4.3.0, and GROMACS 2026.3, the tiny ethanol + two-residue GLY peptide system completed Antechamber, `parmchk2`, `tleap`, ParmEd export, `grompp`, GROMACS `mdrun -rerun`, and a Sander single-point calculation.

The topology retained all 1,376 atoms. ParmEd export had a maximum coordinate deviation of `8.4309e-5 Å` and charge delta `6.60e-9 e`. Protein heavy-atom identity validation reports the single terminal `OXT` atom that `tleap` added, and rejects other unexplained additions. Summed Amber energy components were `-3360.3308 kcal/mol`; GROMACS Potential was `-3360.9253 kcal/mol`, a measured difference of `-0.5945 kcal/mol` (`0.000177` relative to the absolute Amber total). The report deliberately sets `acceptance_tolerance: null` and `status: measured_unqualified`.

This is a successful execution and conversion regression, not a validated force-field benchmark: it uses one small, artificial system and one conformation. The GROMACS-conversion profile remains disabled. A separate 50-step OpenMM run on the same tiny Amber topology is recorded in [`../validation/G-MD-11.md`](../validation/G-MD-11.md); it demonstrates native topology consumption only and does not establish force-field accuracy or long-run stability.

## Planned scope

The first builder profile targets one exact workflow: ff14SB protein + GAFF2 ligand + AM1-BCC charges + TIP3P water + the selected Amber ion parameters, with native Amber topology and optional ParmEd GROMACS export. It will not claim support for ff19SB/OPC, OpenFF hybrids, nonstandard residues, metals, covalent ligands or alternate protein force fields until each has its own configuration and validation evidence.

The Amber-to-GROMACS compatibility profile is registered as disabled. Enablement requires a multi-system benchmark covering varied ligand chemistries and protein residues, consistent term-by-term energy comparison, and an empirically justified tolerance. The native Amber profile is enabled only for OpenMM's AmberPrmtopFile/AmberInpcrdFile route, whose present evidence is a short 1,376-atom smoke run. It must not be treated as broad scientific validation. This follows ADR-0010: a readable topology, matching family labels, and one close total energy do not establish general parameter compatibility.

## Contract boundary discovered during design

An imported CHARMM-GUI bundle contains a source `.mdp` protocol and should preserve it. A generated Amber system does not inherently select minimization/NVT/NPT/production settings; those belong to the configurable MD workflow stage. `SystemBuildResult.protocol` is therefore optional: import adapters populate the source protocol, while builders return `null` until an MD protocol is selected. This avoids fabricating a simulation protocol as a side effect of topology generation.
