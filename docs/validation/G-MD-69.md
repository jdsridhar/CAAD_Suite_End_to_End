# G-MD-69 — Independent Ewald pair fixture and accumulation scaling

**Finding:** A small PME fixture with explicitly known included and excluded charge pairs agrees with an independent double-precision Ewald short-range calculation to within 0.002 kJ/mol. A deliberately simple, nonphysical 16,000-atom lattice control shows a CPU/GPU Coulomb-SR difference of −3.492 kJ/mol (GPU minus CPU) with PME held on CPU. This demonstrates that backend differences can accumulate to a substantial size in a large artificial charge system. Its sign is opposite the G-MD-44 effect, so it does not explain or qualify the protein–ligand result.

## Method

Built synthetic neutral dimers with charges +1e/−1e, a zero-energy bond to define one excluded pair per dimer, zero Lennard-Jones parameters, and periodic PME. Each system was evaluated on one unchanged coordinate frame with GROMACS 2026.3 `mdrun -rerun`, once with CPU PP and once with GPU PP; PME was explicitly assigned to CPU in both. GPU logs confirm PP short-range interactions ran on GPU. No dynamics were advanced.

The independent reference evaluates every within-cutoff pair in double precision using the Ewald split. With `χij=1` for a non-excluded pair and 0 for an excluded pair, the pair term is `C qi qj [χij(1/r − shift) − erf(βr)/r]`. It also includes the Ewald self term `−C β/√π Σ qi²`, which GROMACS includes in the `Coulomb (SR)` energy. The potential shift is `shift=erfc(βrc)/rc`. The verifier reproduces GROMACS's single-precision `calc_ewaldcoeff_q` search for β, then evaluates pair and self terms independently in double precision. The verified fixture values are β=2.470650673 nm⁻¹ and shift=7.1428468×10⁻⁷ nm⁻¹. The cell-list evaluator checks periodic minimum-image distances and hashes its inputs and outputs.

## Results

All energies are kJ/mol. Each CPU/GPU pair uses the same TPR and coordinates; the reference residual is backend energy minus the double-precision result.

| Atoms | Included / excluded pairs within cutoff | CPU Coulomb (SR) | GPU Coulomb (SR) | GPU − CPU | CPU / GPU reference residual |
|---:|---:|---:|---:|---:|---:|
| 2 | 1 / 0 | −409.734680 | −409.734558 | +0.000122 | −0.000135 / −0.000013 |
| 4 | 4 / 2 | −15.617126 | −15.617371 | −0.000245 | +0.000204 / −0.000041 |
| 16 | 80 / 8 | −37.662048 | −37.663940 | −0.001892 | +0.001777 / −0.000115 |
| 2,000 | 16,000 / 1,000 | −7,861.236328 | −7,861.345215 | −0.108887 | +0.047432 / −0.061455 |
| 16,000 | 128,000 / 8,000 | −62,887.585938 | −62,891.078125 | −3.492187 | +2.684140 / −0.808047 |

In the 16,000-atom case, the GPU−CPU difference is −0.835 kcal/mol; the G-MD-44 GPU-PP/CPU-PME minus CPU-PP/CPU-PME difference was +1.378 kcal/mol. The opposite sign and simple lattice topology prevent transferring this result to 5NIU/RC8. It suggests system size and the accumulation of Ewald pair terms can matter, but does not show whether the dominant contribution is the CPU table approximation, CUDA `erff`, summation order, exclusion handling, or their interaction.

## Limits and next probe

- These are engineered numerical fixtures, not physical molecular systems or stability tests. They contain only neutral charge dimers, no nonzero Lennard-Jones interactions, and no biological interpretation.
- Only one frame was evaluated per fixture. No uncertainty estimate, acceptance tolerance, correction, or Amber/GROMACS compatibility profile follows.
- The direct/exclusion formula is validated on these fixtures to small absolute residuals. This does not validate the same formula or error scale for the G-MD-44 topology.
- Next compare available CPU Ewald evaluation modes on the same 16,000-atom fixture, holding TPR, frame, PME and CPU backend fixed. Then test the winning explanatory path on the actual G-MD-44 coordinates and independent equilibrated systems. If the CPU mode cannot be controlled cleanly in the installed build, record that limitation and leave the full-system cause unresolved.

## Reproduction and provenance

The generated GRO/topology/MDP/TPR, rerun EDR/log/XVG files, pair specifications, independent verifier, JSON results, and exact GROMACS version are under `/home/sridhar/gmd69-minimal-pme-pair-fixture-20261003/`. The 16,000-atom lattice uses 8,000 identical dimers on a 1 nm cubic lattice in a 20 nm periodic box. Commands and all file hashes are in `/home/sridhar/gmd69-probe-audit-20261003/full-manifest.json`.

For each size, reproduce the energy-only comparison with:

```bash
gmx mdrun -s pme.tpr -rerun system.gro -deffnm rerun \
  -nb cpu -pme cpu -ntmpi 1 -ntomp 4 -pin off
# Repeat with -nb gpu -gpu_id 0; leave -pme cpu unchanged.
```

Run `reference/verify_ewald_sr.py` on the accompanying JSON pair specification and extracted CPU/GPU XVG files to regenerate the independent comparison. The control remains diagnostic and is not a physical-model recommendation.
