# G-MD-46 — Analytic Ewald self and neutralizing-background audit

**Result:** For the 18,169-atom G-MD-44/45 pose-derived system, Amber and GROMACS serialized charges agree within 4.49×10⁻⁹ e per atom, and both net charges are effectively zero. At the matched Ewald coefficient, the analytic self-energy difference from the serialized charge rounding is 4.84×10⁻⁶ kcal/mol; the estimated neutralizing-background correction is below 7.41×10⁻¹⁶ kcal/mol. These terms cannot account for the observed roughly −2.44 kcal/mol residual under the standard analytic Ewald expressions. This is an analytic bound, not a direct extraction of Sander's internal PME energy components.

## Method

ParmEd 4.3.1 read the Amber prmtop and the ParmEd-exported GROMACS topology for the same atom order. Per-atom charges and sum-of-squared-charges were compared. The matched Ewald coefficient was 0.27511 Å⁻¹ (2.7511 nm⁻¹). The analytic Ewald self term was evaluated as `−k_e alpha / sqrt(pi) * sum(q_i^2)` for each serialized charge array, using `k_e = 138.935456 kJ mol⁻¹ nm e⁻²`, then converted to kcal/mol. The neutralizing uniform-background term was bounded with the standard magnitude proportional to `k_e pi Q^2 / (2 alpha^2 V)` across the 15 G-MD-44 snapshot volumes.

GROMACS's published Ewald decomposition includes the analytic charge self correction in its reported Coulomb (SR) term; the energy output combines this with direct-space and exclusion corrections. Amber's standard Sander `EEL` output does not expose an independently validated self-energy component in these runs. Therefore the analytic evaluation checks whether charge, alpha, or net-charge differences could plausibly explain the gap; it does not claim to observe or verify Amber's internal partition. References: [GROMACS long-range electrostatics](https://manual.gromacs.org/2026.3/reference-manual/functions/long-range-electrostatics.html) and the [Amber 2023 Reference Manual](https://ambermd.org/doc12/Amber23.pdf).

## Results

| Quantity | Amber | GROMACS | Difference / bound |
|---|---:|---:|---:|
| Total charge (e) | −9.15×10⁻⁸ | −1.40×10⁻⁷ | 4.85×10⁻⁸ e |
| Sum of squared charges (e²) | 5836.1802795283 | 5836.1802794343 | 9.40×10⁻⁸ e² |
| Analytic Ewald self energy (kcal/mol) | −300802.5781756 | −300802.5781708 | +4.84×10⁻⁶ kcal/mol |
| Maximum neutralizing-background magnitude over sampled boxes | <7.41×10⁻¹⁶ kcal/mol | <7.41×10⁻¹⁶ kcal/mol | Negligible |

The large absolute self term is expected to cancel in a like-for-like total. The difference caused by the tiny serialized charge discrepancies is many orders of magnitude below the observed Amber/GROMACS total-energy residual.

## Interpretation and limits

- This rules out a materially different analytic self term caused by the observed charge serialization or Ewald coefficient for this specific system, assuming the same conventional Ewald expression.
- The net-charge background correction is negligible because both systems are neutral to numerical precision. This is system-specific; do not generalize to charged cells.
- It does not resolve reciprocal-space exclusion corrections, PME mesh influence-function differences, direct-space implementation details, or undocumented Sander energy bookkeeping.
- G-MD-30 found identical structural exclusion and explicit 1–4 pair records, but that topology audit does not prove the two engines compute identical reciprocal exclusion corrections.
- No tolerance or Amber-to-GROMACS compatibility profile is enabled.

## Provenance

The audit script and JSON are retained outside Git under `/home/sridhar/gmd44-cutoff-shift-20260930/`.

| Artifact | SHA-256 |
|---|---|
| Audit script | `8fb44600bb9e16135d8bf2560db06f12d9513ef927a7f07149fe184e74210e5b` |
| Audit result JSON | `52ea5d1906d3c03b27d67de0ebe6d9ab14efa88a7bb6a4463efa33f7f3875e91` |
| Amber prmtop | `1b3293c79da7accb73f1068f6978dab011f274bbcece8ed327f44a18e12166ea` |
| GROMACS topology | `e72cc07f2c6d92eaed3449321934d29f7e2a295f0a3abe9edb2257d0ea93f20e` |
| Starting GROMACS GRO | `02de626cb912f3b1be781f325a79e071edaf0f74130649ef03e11a6b71b0b01a` |

Related records: [G-MD-30](G-MD-30.md), [G-MD-43](G-MD-43.md), [G-MD-44](G-MD-44.md), and [G-MD-45](G-MD-45.md).
