"""Engine-specific analysis and trajectory-processing adapters."""

from caddsuite.adapters.analysis.gromacs_hbond import (
    GromacsHbondAdapter,
    GromacsHbondParameters,
    GromacsHbondPlanError,
)
from caddsuite.adapters.analysis.gromacs_sasa import (
    GromacsSasaAdapter,
    GromacsSasaParameters,
    GromacsSasaPlanError,
)
from caddsuite.adapters.analysis.gromacs_trajectory import (
    GromacsTrajectoryPlanError,
    GromacsTrajectoryProcessor,
    GromacsTrajectoryProcessorParameters,
)
from caddsuite.adapters.analysis.mdanalysis_metrics import (
    MDAnalysisMetricsAdapter,
    MDAnalysisMetricsParameters,
    MDAnalysisPlanError,
)

__all__ = [
    "GromacsHbondAdapter",
    "GromacsHbondParameters",
    "GromacsHbondPlanError",
    "GromacsSasaAdapter",
    "GromacsSasaParameters",
    "GromacsSasaPlanError",
    "GromacsTrajectoryPlanError",
    "GromacsTrajectoryProcessor",
    "GromacsTrajectoryProcessorParameters",
    "MDAnalysisMetricsAdapter",
    "MDAnalysisMetricsParameters",
    "MDAnalysisPlanError",
]
