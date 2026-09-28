# G-MD-20 — Bounded NPT sanity run for temperature and pressure

**Status:** 125 ps GROMACS run completed without a detected integration failure. Temperature and volume behaved plausibly after an initial volume relaxation; instantaneous pressure remained noisy. This is a single-system numerical/thermodynamic sanity check, not production MD validation or a binding-stability result.

## Purpose and system

This follow-up addresses the limit recorded in G-MD-9: its 50-step, 0.1 ps run only proves that `grompp` and `mdrun` execute. The run used the existing 2M2D_LIG CHARMM-GUI system (49,682 atoms) and started from the user-provided `step4.1_equilibration.gro` state, which contains velocities. The source files under `/home/sridhar/mdsuite_data` were copied to a private staging directory and left unchanged.

The source production MDP specifies v-rescale at 303.15 K and isotropic C-rescale at 1 bar (`tau-p = 5 ps`). C-rescale includes a stochastic term for correct volume fluctuations and is supported for production in the [GROMACS 2026.3 MDP documentation](https://manual.gromacs.org/current/user-guide/mdp-options.html). The source uses a 4 fs timestep, but hydrogen-mass repartitioning was not verified; this check therefore used 2 fs. It ran 62,500 steps (125 ps), set `ld-seed = 20260928`, retained the source coupling and force-field settings, and disabled compressed-coordinate output. Energy/log output remained at the source cadence (every 1,000 steps, or 2 ps at the selected timestep).

This is a direct GROMACS run that complements the adapter execution test in G-MD-9; it does not independently exercise the workflow scheduler/MD adapter.

## Result

`grompp` completed without warnings and without `-maxwarn`. `mdrun` completed all 62,500 steps. The log contains no `LINCS WARNING`, and the energy file contains finite temperature, pressure, volume, density, and energy records.

GROMACS `gmx energy` summaries after excluding the initial 25 ps volume-relaxation interval (descriptive window selected after observing the trajectory):

| Observable | Mean | GROMACS error estimate | RMS fluctuation | Fitted drift over 99 ps |
|---|---:|---:|---:|---:|
| Temperature | 303.169 K | 0.26 K | 1.465 K | −1.163 K |
| Solute temperature | 303.54 K | 0.79 K | 5.775 K | −4.170 K |
| Solvent temperature | 303.15 K | 0.23 K | 1.429 K | −1.015 K |
| Pressure | −4.91 bar | 9.8 bar | 117.09 bar | −18.11 bar |
| Volume | 492.487 nm³ | 0.20 nm³ | 0.873 nm³ | −0.184 nm³ |
| Density | 1,023.38 kg/m³ | 0.41 kg/m³ | 1.812 kg/m³ | +0.386 kg/m³ |

The source equilibration state began at about 531.4 nm³. Volume contracted during the first 25 ps, whose mean pressure was −343 bar, then fluctuated around approximately 492.5 nm³ over the remaining 100 ps. The post-relaxation average pressure is near the 1 bar reference relative to GROMACS’s reported error estimate, but the instantaneous pressure RMS fluctuation is large and block means vary. These short, correlated data do not establish pressure convergence or an equilibrated NPT ensemble. The 25 ps exclusion is descriptive and post hoc, not a pre-registered burn-in rule.

## Interpretation

- **Supported:** the staged system completed a short CPU NPT run; no LINCS warning or non-finite observable was detected; the thermostat-group temperatures were close to their 303.15 K references; box volume showed an initial relaxation followed by smaller fluctuations in this window.
- **Not supported:** general force-field validity, pressure convergence, equilibrium sampling, ligand-binding stability, biological activity, or production-run readiness.
- No arbitrary pass/fail cutoff was introduced. A larger or independent-replicate study would be needed to set acceptance criteria for stability.

## Provenance and retained artifacts

GROMACS 2026.3-conda_forge, Linux x86_64 WSL2, CPU execution with one thread-MPI rank and four OpenMP threads on Intel Core i5-14450HX. Random thermostat seed: 20260928. Exact input and output files are retained outside the repository at `/home/sridhar/.cache/caddsuite-v6-2m2d-npt-125ps/`; source inputs remain in the user data directory.

| Artifact | SHA-256 |
|---|---|
| Source `step4.1_equilibration.gro` | `9e7f3ab35eb4e8c6d7a07f00a099bd3a88b5ea128ed9fc3b23dc41cf8757fd8e` |
| Source `step5_production.mdp` | `feb4f43cca76e71458a47325beecd3ce702b02d78cf2a4ee10749cb5c0fc3dc1` |
| Source `topol.top` | `29dd63c47b3e0380e914e5141f496f89d17e83acb7a0b53ad43fea83cadc8ffc` |
| Source `index.ndx` | `f246ff7d2f33f73f25dfd6506b6a3592f88bebdfce5aba2cbb9f936df46146d8` |
| Derived `v6_npt_125ps.mdp` | `3fc673bb57b7e1b14dfd3290fea441ecdd2996f80ec1f8fe9869528f39eaba5c` |
| Compiled `v6_npt_125ps_final.tpr` | `56989e51dcb5aa148f6588cb2ce30768b2b47c671afd4114b7f915a3ea8bdedf` |
| `v6_npt_125ps.edr` | `16da0cfdf6d52ca9dca4b34ab0252d7837d02d601176481785ea03adeb5661f2` |
| `v6_npt_125ps.log` | `5171d8a79b9791e2345f2cb56bca2e04a3cf02661c5d72a72fb5fc87382994e9` |
| `v6_npt_125ps.gro` | `235c8bf6835b2d61447d69663e20b78f4c8d934d82d382a29d68c75badcbbe9f` |
| `v6_npt_125ps.cpt` | `3cc71a629ba0beea1e5383253dc9784337e28012209f76a2a793b40cb386fadd` |
| `v6_observables.xvg` | `0828937a26524d01e1c8ad210b6c43190b7698f7897ec695f47b6585d29fab0f` |

`gmx grompp` argv: `gmx grompp -f v6_npt_125ps.mdp -c start.gro -p topol.top -n index.ndx -o v6_npt_125ps_final.tpr -po v6_processed_final.mdp`.

`gmx mdrun` argv: `gmx mdrun -s v6_npt_125ps_final.tpr -deffnm v6_npt_125ps -ntmpi 1 -ntomp 4 -pin on`.

`gmx energy` selected Potential, Total-Energy, Temperature, Pressure, Volume, Density, Enthalpy, T-SOLU, and T-SOLV. Raw engine output is retained in the cache directory; it is not copied into the public repository because the source MD system is user data.