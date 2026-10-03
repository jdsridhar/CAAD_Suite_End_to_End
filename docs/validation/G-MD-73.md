# G-MD-73 — Amber/GROMACS residual under fixed PP backends

**Finding:** Re-evaluating the same 15 G-MD-44 coordinates shows that the reported mean GROMACS−Amber total-potential residual depends strongly on the GROMACS nonbonded PP backend. The paired G-MD-44 result (−2.4383 kcal/mol) matches GROMACS GPU PP/GPU PME. Holding PME on CPU, GPU PP gives −2.4346 kcal/mol, while CPU PP gives −3.8121 kcal/mol against the same saved Amber Sander energies. Thus the +1.3775 kcal/mol GPU-PP versus CPU-PP effect materially shifts the apparent Amber/GROMACS residual. Neither backend comparison is a general compatibility qualification.

## Method

Reused the 15 previously validated Amber Sander single-point results and matching G-MD-44 replica coordinate frames (replicas 1–3, 100–500 ps at 100 ps intervals). No new Amber jobs or dynamics were run. Compared those same Amber total energies with GROMACS Potential extracted from the previously captured CPU-PP/CPU-PME, GPU-PP/CPU-PME, and GPU-PP/GPU-PME reruns. Also recomputed the CPU analytical and forced-table rows from the explicit G-MD-71 reruns. Conversion is `kJ/mol ÷ 4.184 = kcal/mol`. G-MD-44 documents atom identity/order, whole-molecule imaging and coordinate matching; G-MD-65/66 and G-MD-71 document the GROMACS execution modes and input hashes.

This is an apples-to-apples backend decomposition of the *reported residual*: each GROMACS value is compared against the same Amber energy at the same coordinates. It does not claim that Amber and GROMACS are physically interchangeable or that one implementation is the reference truth for the other.

## Results

All values are mean GROMACS Potential minus Amber total energy in kcal/mol over the same 15 frames. Ranges are minima and maxima across frames.

| GROMACS PP / PME backend | Mean residual | Min | Max |
|---|---:|---:|---:|
| GPU / GPU (paired G-MD-44 baseline) | −2.4383 | −2.5309 | −2.3620 |
| GPU / CPU | −2.4346 | −2.5347 | −2.3508 |
| CPU / CPU (default CPU analytical exclusion mode) | −3.8121 | −3.9431 | −3.7166 |
| CPU / CPU (forced analytical exclusion mode) | −3.8121 | −3.9431 | −3.7166 |
| CPU / CPU (forced table exclusion mode) | −3.7793 | −3.8983 | −3.6779 |

The paired G-MD-44 baseline agrees with GPU/GPU reruns to within the retained energy extraction precision; the mean difference is below 0.008 kcal/mol. Moving PME from GPU to CPU while keeping GPU PP changes the residual mean by only about +0.0037 kcal/mol. Moving PP from CPU to GPU with PME fixed on CPU changes it by about +1.3775 kcal/mol, consistent with G-MD-66's component decomposition. Forcing the CPU Ewald exclusion correction from analytical to table shifts the residual by +0.0329 kcal/mol, consistent with G-MD-71 and much smaller than the PP backend contrast.

## Interpretation and limits

- The original −2.438 kcal/mol result is not a backend-independent Amber/GROMACS discrepancy; it is tied to the GPU/GPU GROMACS reference path used for the paired comparison.
- A fixed CPU backend produces a more negative residual (−3.812 kcal/mol). This exposes rather than resolves the underlying difference.
- The dominant same-coordinate GROMACS PP backend shift is substantial on this 5NIU/RC8 setup. The CPU Ewald table/analytical toggle is a minor contributor. CUDA versus CPU arithmetic/accumulation and other numerical conventions remain unresolved.
- The 15 points are correlated samples from three short trajectories of one pose-derived system. There is no uncertainty estimate or acceptance tolerance.
- Do not generalize either residual to Amber/GROMACS compatibility. Continue source-backed backend analysis on independently equilibrated, chemically varied systems.

## Provenance

This synthesis uses the validated G-MD-44 paired-energy table, G-MD-65 CPU/GPU and G-MD-66 GPU-PP/CPU-PME frame tables, and explicit G-MD-71 forced CPU-mode reruns. Their raw inputs and manifests remain in the corresponding external capture directories; this report introduces no new executable output. The comparison was independently recomputed with a small read-only script in the WSL session; per-backend means and ranges are recorded above.
