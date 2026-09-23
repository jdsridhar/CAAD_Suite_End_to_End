# ADR-0009: API-first; React + Mol* UI later; Electron optional; Streamlit not in the core

- **Status:** Accepted (UI technology to be confirmed at Phase 13)
- **Date:** 2026-09-23
- **Related:** ARCH-10, SEC-04, SEC-05, requirements §27–29, §57

## Context
- Legacy UIs: PyQt5 (DFT) holding workflow state in UI objects; two stdlib HTTP dashboards (docking, MD) shelling out to CLIs and re-implementing status logic; PyQt6 (autopilot) running the CLI through `QProcess` (the best of the four patterns).
- The backend runs in WSL2; the user browses from Windows (ADR-0007).
- PyQt is GPL-3.0, which matters if a GUI is ever distributed (Audit §4.3).
- 3D needs: proteins, poses, complexes, trajectories, and volumetric data (orbitals, MEP).

## Decision
1. **API first:** FastAPI (Pydantic-native, OpenAPI) with REST plus Server-Sent Events for logs and progress; bound to 127.0.0.1; **per-install token + Origin check** (fixes SEC-05); uploads only through a validated ingest path (fixes SEC-04).
2. **CLI (Typer)** is first-class from Phase 3. It is how HPC and scripting will use the platform.
3. **UI in Phase 13, not before:** React + TypeScript (Vite), TanStack Query, TypeScript client generated from OpenAPI; **Mol\*** for 3D (proteins, poses, trajectories, cube volumes); charting via Vega-Lite or Plotly.
4. **Electron:** optional packaging later. The browser + localhost already works against WSL with zero packaging, so Electron adds no scientific value today.
5. **Streamlit:** not used in the core. Any prototype must call the API, never the science directly.
6. The UI contains **no scientific computation and no workflow state**. It renders state from the API.

## Alternatives considered
| Option | Why not (now) |
|---|---|
| PyQt/PySide desktop | GPL/licensing considerations; hard to run against a WSL backend; weaker 3D-in-browser ecosystem than Mol* |
| Streamlit as the main UI | Rerun model couples UI and computation; hard to build a multi-page workflow app; tempts science into the UI |
| Electron from day one | Packaging complexity (spawning a WSL backend from Windows) without benefit |
| Server-rendered HTML (Jinja + htmx) | Viable and simpler; weaker for rich 3D and interactive workflow building. Kept as a fallback |
| NGL / 3Dmol.js instead of Mol* | Lighter, but weaker trajectory and volume support. 3Dmol.js may still be used for small inline views |

## Consequences
- Positive: one backend serves CLI, API, UI and future automation; the UI is replaceable; security is centralized.
- Negative: a TypeScript/React codebase to maintain later; Mol* has a learning curve.

## Revisit when
Phase 13 starts. Re-confirm React + Mol* against the actual UI requirements, or a need for offline desktop distribution appears (then Electron or Tauri).

## Learning notes
**API-first** means the UI is just one client. The same API serves scripts, notebooks and CI. It is the structural fix for "science hidden inside the GUI".
