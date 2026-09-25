# G-MD-16 — GROMACS hydrogen-bond count regression

**Status:** Passed for the archived 2M2D_LIG trajectory; one dataset/version only.

**Engine:** GROMACS 2026.3-conda_forge.
**Inputs:** copied `step5_1.tpr`, `combined_fit.xtc`, and `analysis.ndx`; original MD data remained read-only.

The isolated worker resolved the `Protein` and `LIG` index groups by name and verified their 1,836 and 48 atoms, respectively, as disjoint subsets of the 49,682-atom topology. It used a donor-acceptor distance cutoff of 0.35 nm and donor-acceptor-hydrogen angle of 30 degrees. GROMACS' effective default donor/acceptor elements were read from `gmx hbond -h` and recorded as N/O.

| Comparison | Result |
|---|---:|
| Frames | 1,001 |
| Time interval | 0.1 ns |
| Time range | 0–100 ns |
| Archived mean count | 0.450549 |
| Population standard deviation | 0.833731 |
| Minimum / maximum | 0 / 5 |
| Normalized CSV vs legacy XVG numeric values | Exact match; 0 differing values |

The worker's content-addressed input copies were verified against the source hashes before execution. The opt-in test `tests/integration/test_gromacs_hbond_golden.py` repeats the full run and verifies the original inputs remain unchanged.

## Scope and limitations

- This is an exact implementation regression against one archived trajectory, not evidence that the underlying hydrogen-bond assignments are experimentally validated or universally correct.
- The metric is a frame-wise count. GROMACS' count output does not preserve atom/residue pair identities, so it cannot establish interaction persistence by residue.
- Donor/acceptor element defaults are taken from the installed GROMACS help output. The adapter fails if those defaults cannot be verified.
- No threshold for candidate selection is implied by these values.
