# Legacy baseline (read-only reference)

The four legacy applications are **not copied** into this repository. They stay where they are and are treated as read-only behavioural references (ADR-0008).

| App | Location (Windows) | Running copy (WSL) | Data (WSL) |
|---|---|---|---|
| DFT GUI Suite | `C:\Users\sridhar\OneDrive\Documents\Suites\dft-gui-suite` | `~/dft-gui-suite` | `~/dft-gui-suite/outputs` |
| Docking Suite | `…\Suites\dockingsuite_app` | `~/dockingsuite_app` | `~/dockingsuite_data` |
| MD Suite | `…\Suites\mdsuite_app` | `~/mdsuite_app` | `~/mdsuite_data` |
| AutoDock Autopilot | `…\Suites\autodock-autopilot-main` | *(not installed)* | — |

`MANIFEST.sha256` records the SHA-256 of every file under `Suites/` exactly as audited on **2026-09-23**: 143 files, including the small DFT outputs used as golden data. Every `file:line` reference in `docs/ARCHITECTURE_AUDIT.md` refers to this baseline.

Verify that the baseline has not changed (from WSL; the repo lives at `~/CAAD_Suite_End_to_End`):

```bash
cd /mnt/c/Users/sridhar/OneDrive/Documents/Suites && sha256sum -c --quiet ~/CAAD_Suite_End_to_End/legacy/MANIFEST.sha256
```

No output means unchanged. If a legacy file changes, re-audit the affected findings before relying on them.
