# ADR-0044: Project-scoped recent workflow run history

## Status

Accepted

## Context

The runtime persists runs, but the browser monitor only retained the currently
submitted run ID. Users needed a way to reopen persisted runs after switching
projects or refreshing the browser.

## Decision

Expose a project-scoped, newest-first run list with a caller-selectable limit
bounded from 1 to 100 and defaulting to 20. The endpoint includes run identity,
accession, status, configuration/workflow hashes, and timestamps. The UI loads a
bounded history for the selected project and opens a selected run through the
existing project-scoped status route.

## Consequences

- Run selection is based on persisted database identity, not filenames or
  browser-only state.
- The history response is summary metadata; detailed tasks, artifacts, logs, and
  provenance continue to come from their dedicated APIs.
- Pagination beyond the bounded recent list is not implemented yet.
