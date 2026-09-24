# Binding-site definitions (Phase 4.6)

## Supported definitions

`structure.binding_site` currently supports three explicit choices:

- **Reference ligand:** selects one ligand instance from the preserved source mmCIF using component, label chain, author residue number, and insertion code from the validated structure split.
- **Blind whole-protein:** uses polymer atoms from explicitly selected chains in a prepared receptor mmCIF.
- **Coordinates:** preserves center and size entered by the user (for example from a paper or a visualization review).

Pocket-detection and residue-selection are represented in the domain enum, but do not yet have calculation adapters.

Each generated site keeps the source mmCIF or prepared-receptor artifact reference and stores the method, center, dimensions, padding, and minimum size. mmCIF bytes are checked against the referenced SHA-256 before geometry is calculated. This prevents silently using a different file with an existing structure identity.

## Reference-ligand geometry

The legacy `make_box.py` used the ligand atom centroid for its center and the bounding-box span for its dimensions. For asymmetric ligands those choices are inconsistent and can shift the search region. The migrated function uses the midpoint of each coordinate minimum and maximum:

`center[i] = (min[i] + max[i]) / 2`

`size[i] = max(max[i] - min[i] + 2 * padding, min_size)`

The previous defaults, 5 Å padding on each side and a 22 Å minimum dimension, remain configurable through `BindingSitePolicy`. Ligand alternate locations use a deterministic A-then-first policy; only model 1 contributes. Coordinates are in Å.

This is an intentional, documented geometry correction (audit SCI-16). Existing historical docking jobs keep their recorded boxes; newly generated boxes use the bounding-box midpoint. Regression checks pin the 5NIU 8YZ reference component and ensure the center differs from the old atom centroid.

## Blind searches and comparability

Blind boxes are labelled `blind_whole_protein` and cite the prepared receptor artifact. The existing `DOCK.BLIND_BOX` validation emits `DECISION_REQUIRED`, since blind scores should not be mixed with pocket-directed scores by default. The existing large-search-space rule warns when box volume exceeds 27,000 Å³; the user must still configure sampling appropriately for the selected engine.

The box calculation does not estimate pocket quality, docking accuracy, or binding affinity. A broad whole-protein box is a search definition, not evidence of a binding site.
