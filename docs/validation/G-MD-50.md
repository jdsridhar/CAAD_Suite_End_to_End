# G-MD-50 — Charge-isolated PME checks for a water and ligand residue

**Result:** With all non-selected atom charges zeroed in derived topology copies, Amber Sander and GROMACS give closely matching total electrostatic energies for (a) one neutral TIP3P water and (b) the neutral nine-atom ligand, evaluated in the same 1,376-atom periodic box. The ligand comparison agrees within Sander's printed precision. This tests the aggregate PME behavior of isolated neutral charge groups, including their retained intramolecular exclusion patterns and periodic-image interactions. It does not isolate a single mathematical exclusion correction or qualify Amber/GROMACS compatibility.

## Question and controlled intervention

G-MD-47 found a mean total electrostatic residual of about −0.188 kcal/mol for the complete ethanol/two-GLY fixture. G-MD-48 established from the GROMACS manual that its excluded-pair reciprocal corrections are split across the reported short-range and reciprocal terms. G-MD-49 found that the installed AmberTools package does not include Sander PME source. This experiment therefore asks whether an isolated neutral molecule with its internal topology exclusions retained reproduces a discrepancy of that scale.

Using ParmEd 4.3.1, copies of the existing paired Amber and GROMACS topologies were made. For each run, only one residue retained its original partial charges; all other per-atom charges were set to zero. Bonds, exclusions, 1-4 records, atom order, coordinates and box were retained. Amber and GROMACS input charge arrays agreed to a maximum per-atom difference of 3.05×10⁻⁹ e before intervention. The selected groups and whole isolated systems were neutral within 1.1×10⁻⁸ e. The coordinates were read from the same GRO file and written to an Amber restart; round-trip coordinate error was below 1×10⁻¹⁴ Å.

Two charge groups were evaluated independently:

- WAT residue index 3: TIP3P oxygen and two hydrogens, net charge 0 e.
- LIG residue index 2: nine atoms, net charge 1.00×10⁻⁸ e in the source GROMACS representation.

All source files remained read-only. Derived files and preparation manifests are under `/home/sridhar/gmd49-residue-isolation-20260930/`.

## Calculation settings

GROMACS 2026.3-conda_forge used PME, a 36×25×24 grid, interpolation order 4, 1.0 nm electrostatic and LJ cutoffs, `coulomb-modifier=None`, and `ewald-rtol=0.000099979`. Flexible-water topology (`-DFLEXIBLE`) was retained. Each case was a one-frame rerun, with both CPU and GPU PME execution recorded. CPU is the primary comparison below.

AmberTools package 23.6 (Conda build `cuda_None_nompi_py311h9caa010_106`; Sander reports 22.0) used a standard Sander single-point control with a 10 Å cutoff, PME order 4, grid 36×25×24, `ew_coeff=0.27511 Å⁻¹`, and `skinnb=0.0`. The physical cutoff was unchanged. `skinnb=0.0` avoids the small-box default-skin limit already documented in G-MD-47.

For like-for-like energy totals, Amber `EEL + 1-4 EEL` was compared with GROMACS `Coulomb-14 + Coulomb (SR) + Coul. recip.`. GROMACS kJ/mol were converted to kcal/mol by division by 4.184. The separate real/reciprocal terms were not compared individually against Amber `EEL`.

## Results

| Isolated charge group | Amber EEL + 1-4 EEL (kcal/mol) | GROMACS CPU Coulomb-14 + SR + reciprocal (kcal/mol) | GROMACS − Amber (kcal/mol) |
|---|---:|---:|---:|
| One WAT | −0.0095 | −0.0103623 | −0.0008623 |
| LIG | −2.6189 | −2.6189696 | −0.0000696 |

For LIG, Amber printed EEL = +6.3092 and 1-4 EEL = −8.9281 kcal/mol. GROMACS CPU terms were Coulomb-14 = −37.356419, Coulomb (SR) = +24.395569, and Coul. recip. = +2.003081 kJ/mol. The −0.0000696 kcal/mol difference is smaller than the 0.0001 kcal/mol display increment in each printed Amber component and is treated as agreement at reported precision, not a measured error bound.

For WAT, Amber printed EEL = −0.0095 and 1-4 EEL = 0 kcal/mol. GROMACS CPU terms were Coulomb-14 = 0, Coulomb (SR) = −2.672897, and Coul. recip. = +2.629541 kJ/mol. The small −0.0008623 kcal/mol difference is retained without a tolerance; low-energy subtraction, output precision and engine numerical details limit interpretation.

GPU PME checks gave −0.0103786 kcal/mol for WAT and −2.6189622 kcal/mol for LIG. Relative to CPU, the component changes were at most 6.9×10⁻⁵ kJ/mol in these two single-frame calculations.

### Term-accounting correction

The first ligand comparison omitted GROMACS Coulomb-14 and Amber 1-4 EEL, producing a spurious large mismatch. That comparison is invalid and excluded. Re-extraction included all three GROMACS Coulomb terms and both Amber electrostatic terms; all values above use this complete accounting. This correction is recorded to make the analysis auditable.

## Interpretation and limits

- Neither isolated neutral group reproduces the roughly −0.188 kcal/mol mean total-system electrostatic residual from G-MD-47. For this one static geometry, internal exclusions and periodic-image interactions of the isolated WAT and ligand do not appear to be its main source.
- This is consistent with the unresolved difference arising from interactions among distinct charged groups or collective periodic electrostatics. That is an inference, not an identified cause.
- The next useful intervention is a matched pair/group charge-isolation calculation and inclusion-exclusion energy difference, which can measure intermolecular contributions while retaining each group’s internal topology.
- The source topology was round-tripped by ParmEd and compiled by GROMACS; this does not replace direct inspection of Amber source. The Amber implementation remains unverified at source level.
- One static pose/start structure, one box, one neutral ligand, and one water were examined. These are diagnostics, not sampling, MD stability evidence, an uncertainty estimate, a general tolerance, or a compatibility qualification.

## Reproducibility

The preparation command is implemented in [`scripts/validation/isolate_residue_charges.py`](../../scripts/validation/isolate_residue_charges.py). Example:

```bash
python scripts/validation/isolate_residue_charges.py \
  --source /path/to/paired-fixture \
  --output /path/to/derived-case \
  --residue-index 2
```

The isolated runs, stdout/stderr, topology/restart inputs, CPU/GPU EDR/XVG results, manifests, and hashes are retained outside the repository under `/home/sridhar/gmd49-residue-isolation-20260930/`. The preparation script SHA-256 is `5ecdf461b85c46229874d53cb98766840580b9af5801cd2c60986bc8bdf6e52f`.
