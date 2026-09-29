# Engine-enabled tests

The regular Quality workflow tests the engine-independent core. The separate PySCF engine integration workflow exercises real external scientific software without adding engine binaries to the platform package:

- It creates the platform core and PySCF worker environments from the checked-in Linux explicit locks.
- It executes one seeded ethanol single-point calculation through the isolated worker and one full application workflow through normalized result/provenance/report handling.
- BLAS/OpenMP thread counts are fixed to one for predictable CI resource use.
- It runs on relevant source/test/lock changes and can also be started manually from GitHub Actions.
- It does not use proprietary software, modify a developer's environment, or represent validation of other quantum engines.

To reproduce locally, create the named environments caddsuite-core and caddsuite-pyscf from environments/caddsuite.lock.txt and environments/caddsuite-pyscf.lock.txt, install the repository into the core environment with python -m pip install --no-deps --no-build-isolation -e ., set CADDSUITE_PYSCF_PYTHON to the worker environment's Python executable, then run the two pytest node IDs listed in .github/workflows/engine-pyscf.yml.

The remaining engine integrations (GROMACS, AmberTools, PSI4, OpenMM, gmx_MMPBSA, and optional visualization stacks) still use opt-in local evidence and are not covered by this hosted job.
