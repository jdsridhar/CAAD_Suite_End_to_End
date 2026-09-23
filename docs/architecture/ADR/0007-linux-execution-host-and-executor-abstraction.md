# ADR-0007: Linux execution host (WSL2 now) with an executor abstraction for SSH/SLURM later

- **Status:** Accepted
- **Date:** 2026-09-23
- **Related:** ARCH-08, ARCH-09, SEC-02, SEC-06, Audit §1, requirements §25–26

## Context
- Every engine is installed in WSL2 Ubuntu. GROMACS/CUDA, Psi4, AmberTools and AutoDock4 are Linux-first; AutoDock4 has no practical native Windows build (autopilot README).
- The legacy apps learned that trajectory I/O across `/mnt/c` (the Windows filesystem bridge) is dramatically slower, so their data lives in WSL-native `~/…_data`.
- The user works on Windows. WSL2 forwards `localhost` automatically.
- Future: remote Linux servers, HPC with SLURM, containers.

## Decision
1. The backend (API, CLI, scheduler, storage) runs **on the Linux host** (WSL2 today). The data root is WSL-native (`~/caddsuite_data`), never OneDrive or `/mnt/c`.
2. The UI runs in the Windows browser against `http://localhost:<port>` (ADR-0009).
3. All process launching goes through an **`Executor`** interface (`submit/poll/cancel/reattach`). The Phase 3 `LocalExecutor`:
   - uses argument lists only (no shell) and runs each task in its own process group, so cancelling kills the whole tree;
   - records PID + Linux start-time token so a live process can be reattached after a crash;
   - captures stdout/stderr as content-addressed artifacts. If the child finishes while the application is down, Linux does not retain its exit code; recovery records an unknown outcome and must not infer success from output files;
   - sets resource-derived thread and GPU environment variables.
   `SSHExecutor` and `SlurmExecutor` are added later behind the same interface.
4. A **resource model** (CPUs, memory, GPUs, exclusive GPU) replaces the per-app FIFO queues and `nproc`-based thread counts. The local admission scheduler makes atomic in-process reservations; GPU IDs are exclusive, and an unknown VRAM size cannot satisfy a configured minimum. It does not estimate usable memory or oversubscribe a GPU.

## Alternatives considered
| Option | Why not |
|---|---|
| Native Windows backend calling engines via `wsl.exe` | Path translation, signal handling and process-tree control across the boundary are fragile; double I/O penalty |
| Keep separate per-app queues | Oversubscription (ARCH-09); no global view |
| Containers mandatory for every engine | GPU/WSL complexity; slows iteration; the engines are already installed and working |

## Consequences
- Positive: engines run where they are fastest and supported; the same code runs on a Linux server or cluster; one global view of resources.
- Resolved (2026-09-23, D1): the source repo was moved from OneDrive to WSL-native `~/CAAD_Suite_End_to_End`, so code and data now both avoid `/mnt/c` and OneDrive sync. Windows tools reach it at `\\wsl.localhost\Ubuntu\home\sridhar\CAAD_Suite_End_to_End`.

## Revisit when
The user needs native macOS/Windows execution for some engine, or a cloud batch service becomes the main target.

## Learning notes
The local resource scheduler is intentionally process-local and has no fairness queue yet; workflow recovery must reconcile running tasks before admitting new work. The local executor exposes a serializable process locator; the orchestration store must persist it with the task attempt before relying on crash recovery. Reattachment rejects PID reuse by comparing the Linux process start-time token. Explain the difference between **orchestration** (deciding what runs) and **execution** (running it somewhere), and why process groups matter. Killing only a parent (the legacy `pkill -P`) can orphan `mpirun` workers.
