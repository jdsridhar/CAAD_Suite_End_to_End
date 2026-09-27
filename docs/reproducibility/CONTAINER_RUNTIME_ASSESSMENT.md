# Optional container runtime assessment

**Decision:** defer Docker and Apptainer recipes until a concrete deployment target requires them.

The platform already runs engines through process-isolated worker environments and captures
environment provenance. For Psi4, the Linux explicit Conda lock at
environments/psi4-linux-64.explicit.txt was used to create a clean environment, and the real
export/replay/comparison integration gate passed in that recreated environment. The lock is
platform-specific and records exact package URLs and package MD5 hashes.

Neither Docker nor Apptainer is installed in the current WSL host. No remote HPC or container
deployment target is configured. Adding an unbuildable container recipe now would create a
second environment definition without validation, including additional decisions about GPU
libraries, scratch mounts, thread limits, and license or redistribution policy. The platform does
not bundle Psi4; the lock resolves packages from conda-forge and the engine remains an installed
user environment.

Revisit container recipes when an HPC/SLURM or containerized deployment target is selected, or
when a journal or institution requires a container digest. At that point, derive the recipe from
the validated per-engine lock, keep commercial engines externally installed, and verify an actual
container build plus a small engine-backed regression before describing the image as supported.
