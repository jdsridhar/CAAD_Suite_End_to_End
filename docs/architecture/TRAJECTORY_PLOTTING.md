# Trajectory metric plotting

## Boundary

Plotting is a visualization stage over normalized `MetricSeries` CSV artifacts. It does not open
trajectories, rerun an analysis, calculate summary statistics, or infer scientific meaning from a
filename. The `TrajectoryPlottingEngine` port accepts a versioned request; the optional
`MatplotlibTrajectoryPlotter` is one adapter and can be replaced without changing metric
contracts or the workflow core.

Each metric declares its x-axis (`time_ns` or `residue`) and numeric value column. New normalized
CSV outputs use `time_ns,value` or `residue,value` as their leading columns. Metric contracts can
still read the earlier RMSF (`residue,…,rmsf_A`) and GROMACS SASA (`time_ns,sasa_A2`) layouts and
make those legacy columns explicit while loading.

## Windows and comparisons

By default, one run displays its full recorded metric series. A comparison displays only the
intersection of the runs' time ranges. Each run keeps its actual samples; the renderer does not
interpolate or resample. If an explicit display window is requested, the renderer filters points
to that interval and records the effective range in its render receipt.

An optional highlighted interval creates plain and highlighted PNGs from the same data. The
highlight is visual context only; it does not imply that points were excluded from a calculation
or summary statistic. Residue-axis plots do not accept time windows. Per-residue overlays require
identical residue coordinates and matching selections/fitting definitions. All comparisons record
the caller's stated comparison basis, since a metric match alone cannot prove that two simulations
represent the same target or protocol.

The renderer verifies each CSV against its artifact SHA-256 before parsing, rejects malformed,
non-finite or unordered values, and records input hashes, analysis IDs, adapter version, Matplotlib
version, output hash, plot variant and effective window. The application layer is responsible for
ingesting the returned PNG into the content-addressed artifact store and associating the render
receipt with its workflow task.

## Why Matplotlib is optional

Matplotlib is a practical static-image renderer for the legacy application's PNG outputs. It is
listed in the `visualization` extra, not imported by the domain or scientific analysis core. An
interactive dashboard can later consume the same normalized CSVs with a browser renderer, while
PDF/HTML reports can call this adapter or another implementation through the port.

For developers, this is an example of the difference between a scientific metric adapter and a
visualization adapter: the metric adapter owns coordinate interpretation and scientific
definitions; the plotter only presents the resulting measurements. Keep those responsibilities
separate when adding metrics or plotting libraries.
