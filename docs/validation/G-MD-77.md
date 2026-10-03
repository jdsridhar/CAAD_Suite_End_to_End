# G-MD-77 — CPU OpenMP thread-count cross-system control

**Finding:** The large G-MD-44 CPU thread-count sensitivity does not generalize to the G-MD-47 system. Across three G-MD-47 replicas and 15 matched frames (100–500 ps), one versus eight OpenMP threads changes mean Coulomb (SR) by only **+0.16823 kJ/mol**; Coulomb reciprocal changes by −0.000143 kJ/mol. In G-MD-44, the same one-versus-eight-thread contrast was −25.9083 kJ/mol. This is a strong system-dependent effect, not a general thread-count correction.

## Method

For each G-MD-47 replica, reran its identical `prod-N.tpr` and `prod-N-whole.trr` at `-ntomp 1`, `4`, and `8`, with `-nb cpu -pme cpu -ntmpi 1 -pin off`. Used GROMACS 2026.3-conda_forge, same AVX2_256 build. Compared 15 matched frames, times 100–500 ps in 100 ps increments. The only deliberate run setting change was OpenMP thread count. No dynamics were advanced.

## Results

Differences are kJ/mol, averaged across all replicas and selected frames, relative to four threads.

| OpenMP threads | Coulomb (SR), Δ vs 4 | Coul. recip., Δ vs 4 | Potential, Δ vs 4 |
|---:|---:|---:|---:|
| 1 | +0.127865 | −0.000106 | +0.127865 |
| 4 | 0 | 0 | 0 |
| 8 | −0.040365 | +0.000037 | −0.040364 |

The one-minus-eight-thread mean is +0.168229 kJ/mol for Coulomb (SR) and +0.168229 kJ/mol for Potential. Across frames, the Coulomb-SR range of the one-minus-eight contrast is +0.115235 to +0.234375 kJ/mol. This is roughly 154 times smaller in absolute magnitude than the corresponding G-MD-44 mean contrast.

## Interpretation and limits

- Together with G-MD-75, this shows that thread-count sensitivity can be large for the G-MD-44 system yet small for G-MD-47. The mechanism likely depends on the system’s pair-energy distribution and accumulation pattern, but that remains a hypothesis.
- This does not identify a source-code defect or establish which thread count is most accurate.
- The frames are correlated and all replicas share a common preparation. The comparison is not a broad validation set.
- Further isolate CPU parallel work partition/reduction and compare against an independent pair-sum reference on representative real-system frames before making numerical claims. Keep OpenMP thread count recorded and fixed for controlled comparisons.

## Provenance

Raw captures, extracted energies, all-frame/selected-frame summaries, input hashes, and the 80-entry verified manifest are retained outside Git at `/home/sridhar/gmd77-gmd47-cpu-thread-sensitivity-20261003/`.
