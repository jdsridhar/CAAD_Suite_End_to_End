# G-DOCK-13 — Blinded curation review audit and unblinding reconciliation

**Status:** Blinded review completed and unblinded reconciliation verified. 100% concordance (6/6 cases) between independent audit verdicts and the frozen curation pipeline decisions.

## Objective & Scope

Under the preregistered redocking validation protocol ([REDOCKING_BENCHMARK_PROTOCOL.md](file:///home/sridhar/CAAD_Suite_End_to_End/docs/validation/REDOCKING_BENCHMARK_PROTOCOL.md)), no cohort docking may proceed until an independent review of a blinded sample of candidate curation records is conducted and reconciled. 

A test packet containing six structure files (`BLIND-01` through `BLIND-06`) was generated with seed `20260929` (`benchmarks/redocking/pilot_v3/curation-review-packet-20260929/`). The packet contained three selected cohort cases and three rejected candidates, with all identifiers, source statuses, and rejection reasons blinded.

Per [REVIEW_INSTRUCTIONS.md](file:///home/sridhar/CAAD_Suite_End_to_End/benchmarks/redocking/pilot_v3/curation-review-packet-20260929/REVIEW_INSTRUCTIONS.md), each case was evaluated against Criteria 1–6 in [ELIGIBILITY_CRITERIA.md](file:///home/sridhar/CAAD_Suite_End_to_End/benchmarks/redocking/pilot_v3/curation-review-packet-20260929/ELIGIBILITY_CRITERIA.md) using only the raw mmCIF coordinates and target polymer entity identifiers. The review was completed and committed to `review_form.csv` before the unblinding key (`curation-review-unblind-key-20260929.json`) was opened.

---

## Blinded Evaluation Summary

| Blind ID | Structure File | Target Entity | Independent Verdict | Criteria Evaluated | Reviewer Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **BLIND-01** | `structures/BLIND-01.cif.gz` | `5JE4_1` | **eligible** | Criteria 1–6 confirmed | X-ray 1.70 Å; SAH (26 heavy atoms, C/N/O/S); contact 2.76 Å; no cofactor/metal within 6 Å; observed pocket backbone intact (unobserved N-term 1–22 ends >5 residues from pocket residue 29). |
| **BLIND-02** | `structures/BLIND-02.cif.gz` | `9DUJ_1` | **ineligible** | Criterion 2 failed | No qualifying 15–50 heavy atom organic ligand; contains heme HEM (with Fe cofactor) and small fragments ACT/GOL (<15 heavy atoms). |
| **BLIND-03** | `structures/BLIND-03.cif.gz` | `9YBU_1` | **eligible** | Criteria 1–6 confirmed | X-ray 1.61 Å; KVD (17 heavy atoms, C/N/O/S/Cl); contact 3.52 Å; no cofactor/metal within 6 Å; complete backbone near pocket. |
| **BLIND-04** | `structures/BLIND-04.cif.gz` | `6G22_1` | **ineligible** | Criterion 5 failed | Ligand 2O2 directly coordinates metal cofactor MG at 2.09 Å (< 6.0 Å threshold). |
| **BLIND-05** | `structures/BLIND-05.cif.gz` | `4L6A_1` | **ineligible** | Criterion 2 failed | No qualifying 15–50 heavy atom organic ligand; only crystallographic additives/ions (PEG, GOL, PO4, MG, K) present. |
| **BLIND-06** | `structures/BLIND-06.cif.gz` | `5ZDC_1` | **eligible** | Criteria 1–6 confirmed | X-ray 1.98 Å; AR6 (36 heavy atoms, C/N/O/P/F); contact 2.57 Å; no cofactor/metal within 6 Å; complete backbone near pocket. |

---

## Unblinding & Concordance Reconciliation

Upon opening `curation-review-unblind-key-20260929.json`, the blinded IDs were mapped back to their canonical PDB IDs, clusters, pipeline source status, and recorded reasons:

```
BLIND-01 -> PDB 5JE4 (Entity 5JE4_1, Cluster 5JDY_1): pipeline status 'selected'
BLIND-02 -> PDB 9DUJ (Entity 9DUJ_1, Cluster 22YX_1): pipeline status 'ineligible'
BLIND-03 -> PDB 9YBU (Entity 9YBU_1, Cluster 1RYU_1): pipeline status 'selected'
BLIND-04 -> PDB 6G22 (Entity 6G22_1, Cluster 1MH9_1): pipeline status 'ineligible'
BLIND-05 -> PDB 4L6A (Entity 4L6A_1, Cluster 1MH9_1): pipeline status 'ineligible'
BLIND-06 -> PDB 5ZDC (Entity 5ZDC_1, Cluster 3SIG_1): pipeline status 'selected'
```

### Detailed Case Analysis

1. **BLIND-01 (PDB 5JE4, Entity 5JE4_1): Concordant (Eligible / Selected)**
   - Pipeline decision: Selected (Case #13 in frozen 30-case cohort).
   - Independent audit: Confirmed resolution 1.70 Å, S-adenosylmethionine (SAH, 26 heavy atoms, non-covalent), no conflicting altlocs, pocket contact 2.76 Å.
   - Backbone completeness: Sequence residues 1–22 are unobserved at the N-terminus; however, residue 29 is the nearest residue with a backbone atom within 8.0 Å of SAH ($29 - 22 = 7 > 5$), satisfying Criterion 6 conservative sequence distance floor.
2. **BLIND-02 (PDB 9DUJ, Entity 9DUJ_1): Concordant (Ineligible / Ineligible)**
   - Pipeline decision: Ineligible (`unsupported ligand elements: ['FE']`, `ligand heavy-atom count outside 15-50: 1, 4, 6`).
   - Independent audit: Rejected on Criterion 2. Iron-containing protoporphyrin IX (HEM) is excluded by element filter, and solvent fragments (ACT, GOL) are below the 15-heavy-atom threshold.
3. **BLIND-03 (PDB 9YBU, Entity 9YBU_1): Concordant (Eligible / Selected)**
   - Pipeline decision: Selected (Case #24 in frozen 30-case cohort).
   - Independent audit: Confirmed resolution 1.61 Å, ligand KVD (17 heavy atoms), unambiguous coordinates, 3.52 Å receptor contact, no adjacent metals/cofactors, zero missing pocket backbone atoms.
4. **BLIND-04 (PDB 6G22, Entity 6G22_1): Concordant (Ineligible / Ineligible)**
   - Pipeline decision: Ineligible (`non-water non-polymer atoms within 6.0 A: ['MG']`, `unobserved near-pocket sequence positions`).
   - Independent audit: Rejected on Criterion 5. Magnesium ion MG coordinates the ligand phosphate/carboxylate oxygen at 2.09 Å, violating the 6.0 Å non-metal exclusion boundary.
5. **BLIND-05 (PDB 4L6A, Entity 4L6A_1): Concordant (Ineligible / Ineligible)**
   - Pipeline decision: Ineligible (`ligand heavy-atom count outside 15-50`, `non-water non-polymer atoms within 6.0 A: ['GOL', 'MG', 'PO4']`).
   - Independent audit: Rejected on Criterion 2. No small-molecule drug-like ligand is bound; structure contains only crystallographic cryoprotectants and buffer ions (PEG, GOL, PO4, MG, K).
6. **BLIND-06 (PDB 5ZDC, Entity 5ZDC_1): Concordant (Eligible / Selected)**
   - Pipeline decision: Selected (Case #17 in frozen 30-case cohort).
   - Independent audit: Confirmed resolution 1.98 Å, ligand AR6 (36 heavy atoms, non-covalent), observed pocket contact 2.57 Å, complete receptor pocket backbone.

---

## Reconciliation Verdict & Quality Gate Disposition

* **Concordance:** **6 / 6 (100.0%)** agreement between blinded independent evaluation and pipeline decisions.
* **Discrepancies:** **0**. No ambiguous cases or false positives/negatives detected.
* **Blinded Gate Disposition:** **PASSED**.
* **Impact on Preregistered Cohort:** The 30-case frozen cohort in `benchmarks/redocking/pilot_v3/cohort-30-20260929/cohort_manifest.json` requires zero amendments or exclusions.
* **Next Gate:** Authorizes proceeding to the single resource-feasibility attempt on **`REDOCK-001` (seed 42)** per [REDOCKING_RESOURCE_PREFLIGHT.md](file:///home/sridhar/CAAD_Suite_End_to_End/docs/validation/REDOCKING_RESOURCE_PREFLIGHT.md).
