"""Engine-neutral stage adapter port contracts."""

from caddsuite.ports.adapters import (
    AdapterContext,
    CommandStep,
    ExecutionPlan,
    StageAdapter,
)
from caddsuite.ports.binding_energy import BindingEnergyCapabilities, BindingEnergyEngine
from caddsuite.ports.qm_engine import (
    QMEngineAvailability,
    QMEngineCapabilities,
    QMTaskPlan,
    QuantumChemistryEngine,
)
from caddsuite.ports.trajectory_analysis import (
    TrajectoryAnalysisCapabilities,
    TrajectoryAnalysisEngine,
)
from caddsuite.ports.trajectory_plotting import (
    RenderedTrajectoryPlot,
    TrajectoryPlottingCapabilities,
    TrajectoryPlottingEngine,
)
from caddsuite.ports.trajectory_processing import (
    TrajectoryProcessingCapabilities,
    TrajectoryProcessingEngine,
)

__all__ = [
    "AdapterContext",
    "BindingEnergyCapabilities",
    "BindingEnergyEngine",
    "CommandStep",
    "ExecutionPlan",
    "QMEngineAvailability",
    "QMEngineCapabilities",
    "QMTaskPlan",
    "QuantumChemistryEngine",
    "RenderedTrajectoryPlot",
    "StageAdapter",
    "TrajectoryAnalysisCapabilities",
    "TrajectoryAnalysisEngine",
    "TrajectoryPlottingCapabilities",
    "TrajectoryPlottingEngine",
    "TrajectoryProcessingCapabilities",
    "TrajectoryProcessingEngine",
]
