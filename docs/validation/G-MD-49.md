# G-MD-49 — Local AmberTools Sander source-availability audit

**Status:** availability check only; it does not inspect or establish Sander PME exclusion behavior.

## Installed implementation inspected

The validation environment contains Conda package `ambertools 23.6`, build `cuda_None_nompi_py311h9caa010_106`, from conda-forge. It provides `bin/sander`, `lib/libsander.so`, `include/sander.h`, and the Python `sander` package with the compiled `pysander` extension. The package cache also includes partial AmberTools content, but the inspected `AmberTools/src` tree contains selected Quick and cpptraj source directories, not the Sander implementation. No Sander PME Fortran source file is present in the installed package or its cached package directory.

The shared library's exported symbol table includes PME/Ewald-related names such as `do_pmesh_kspace`, `ewald_force_`, and `__ew_recip_MOD_do_pmesh_kspace`. These names establish only that related routines exist in the binary; without source or debug-level evidence they do not establish the equations, exclusions, correction signs, or energy bookkeeping. Binary symbol inspection is therefore not treated as a scientific result.

## Access attempt and limits

A read-only HTTP check of the commonly used AmberTools 23 source archive URL returned 404 in this environment; checks of likely archive-name variants returned 403. This does not establish whether the source is unavailable through another official route. The source-level audit remains incomplete. No package was installed or modified, no source was retrieved, and no force/energy run was performed for this note.

## Next step

Obtain the exact AmberTools 23.6 Sander source and corresponding update level from an official source channel, then trace the PME direct, reciprocal, exclusion-correction, self, and surface terms against GROMACS 2026.3. If exact matching source cannot be obtained, use a controlled minimal system that isolates the excluded-pair contribution and document that it is behavioral evidence rather than code-level proof. Do not infer Amber behavior from the GROMACS manual or from symbol names. The Amber→GROMACS profile remains disabled and no comparison tolerance is set.
