import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createApiClient, uploadArtifact } from "./api/client.js";
import WorkflowBuilder from "./WorkflowBuilder.js";
import ScientificEvidenceView from "./ScientificEvidenceView.js";
import type { StructureFormat } from "./MolecularViewer.js";
import type { CoordinatesFormat, TopologyFormat } from "./TrajectoryViewer.js";
import "./dashboard.css";

const MolecularViewer = lazy(() => import("./MolecularViewer.js"));
const TrajectoryViewer = lazy(() => import("./TrajectoryViewer.js"));
const VolumeViewer = lazy(() => import("./VolumeViewer.js"));
import TrajectoryPlots, { type TrajectoryAnalyticsResult } from "./TrajectoryPlots.js";
import type { components } from "./api/schema.js";

export type EnginePaths = components["schemas"]["EnginePaths"];
export type EngineReadiness = components["schemas"]["EngineReadiness"];
export type EngineDiscoveryReport = components["schemas"]["EngineDiscoveryReport"];

export const DEFAULT_ENGINE_PATHS: EnginePaths = {
  vina_executable: "vina",
  cadd_python: "python",
  pdbfixer_worker: "pdbfixer_worker.py",
  mk_prepare_receptor: "mk_prepare_receptor.py",
  mk_prepare_ligand: "mk_prepare_ligand.py",
  mk_export: "mk_export.py",
  gmx_executable: "gmx",
  psi4_python: "python",
  worker_source_dir: "src",
  gmx_mmpbsa_executable: "gmx_MMPBSA",
  ambertools_bin: "bin",
  gmx_mmpbsa_python: "python",
  gmx_mmpbsa_worker: "gmx_mmpbsa_worker.py",
  caddsuite_python: "python",
};

type Project = { id: string; slug: string; name: string };
type Compound = { id: string; accession: string; name: string; inchikey: string; payload: Record<string, unknown> & { parent?: { canonical_smiles?: string } } };
type Snapshot = {
  project_id: string;
  run_id: string;
  status: string;
  submission?: { error?: string | null };
  tasks?: Array<{ task_id: string; stage_id: string; state: string }>;
};
type ArtifactItem = { id: string; sha256: string; media_type: string; kind: string; size_bytes: number; original_name?: string | null };
type Lineage = { artifacts?: ArtifactItem[] };
type ProjectArtifact = ArtifactItem;
type PreparedConformer = {
  conformer_id: string;
  form_id: string;
  compound_id?: string | null;
  generator?: string;
  energy_kcal_per_mol?: number | null;
  structure_artifact_id?: string;
  created_at?: string;
  conformer_payload?: Record<string, unknown>;
  form_payload?: Record<string, unknown>;
};
type Dashboard = {
  project: Project;
  target: unknown;
  target_note: string;
  counts: { compounds: number; workflow_runs: number; tasks_in_recent_runs: number; artifacts: number; artifact_bytes: number };
  workflow_statuses: Record<string, number>;
  artifact_kinds: Record<string, { count: number; size_bytes: number }>;
  prepared_conformers?: PreparedConformer[];
  recent_runs: Array<{ run_id: string; accession: string; status: string; created_at: string; tasks: Array<{ stage_id: string; state: string; updated_at: string | null }> }>;
  scientific_results: Array<{
    schema_version: string;
    task_id: string;
    source_task_id: string;
    stage_id: string;
    task_state: string;
    subject_id: string | null;
    created_at: string;
    category: string;
    result_id: string;
    identity: string;
    method: string;
    values: unknown;
    warnings: string[];
  }>;
};

function formatBytes(value: number) {
  if (value < 1024) return value + " B";
  const units = ["KiB", "MiB", "GiB", "TiB"];
  let n = value / 1024, i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return n.toFixed(1) + " " + units[i];
}

function topologyFormat(a: ArtifactItem): TopologyFormat | null {
  const n = (a.original_name || a.kind).toLowerCase();
  if (n.endsWith(".gro")) return "gro";
  if (n.endsWith(".pdb")) return "pdb";
  if (n.endsWith(".cif") || n.endsWith(".mmcif")) return "mmcif";
  if (n.endsWith(".psf")) return "psf";
  if (n.endsWith(".prmtop")) return "prmtop";
  if (n.endsWith(".top")) return "top";
  return null;
}

function cubeFile(a: ArtifactItem): boolean {
  return (a.original_name || a.kind).toLowerCase().endsWith(".cube") || (a.original_name || a.kind).toLowerCase().endsWith(".cub");
}

function coordinatesFormat(a: ArtifactItem): CoordinatesFormat | null {
  const n = (a.original_name || a.kind).toLowerCase();
  if (n.endsWith(".xtc")) return "xtc";
  if (n.endsWith(".trr")) return "trr";
  if (n.endsWith(".dcd")) return "dcd";
  if (n.endsWith(".nc") || n.endsWith(".netcdf")) return "nctraj";
  if (n.endsWith(".lammpstrj") || n.endsWith(".dump")) return "lammpstrj";
  return null;
}

function structureFormat(a: ArtifactItem): StructureFormat | null {
  const type = a.media_type.toLowerCase(), name = (a.original_name || a.kind).toLowerCase();
  if (type === "chemical/x-pdb" || type === "chemical/pdb" || name.endsWith(".pdb")) return "pdb";
  if (type === "chemical/x-mmcif" || type === "chemical/mmcif" || name.endsWith(".cif") || name.endsWith(".mmcif")) return "mmcif";
  if (type === "chemical/x-mdl-sdfile" || type === "chemical/x-sdf" || name.endsWith(".sdf") || name.endsWith(".sd")) return "sdf";
  if (type === "chemical/x-mol2" || name.endsWith(".mol2")) return "mol2";
  if (type === "chemical/x-gromacs-gro" || name.endsWith(".gro")) return "gro";
  return null;
}

type HistoryRun = { run_id: string; accession: string; status: string; created_at: string; started_at: string | null; finished_at: string | null };
type RecordedMdCandidate = {
  run_id: string;
  accession: string;
  submitted_at: string;
  system_id: string;
  atoms: number;
  engine: string;
  length_ns: number;
  timestep_fs: number;
  temperature_K: number;
  label: string;
};
type RecordedMmpbsaCandidate = {
  run_id: string;
  accession: string;
  submitted_at: string;
  request_id: string;
  method: string;
  label: string;
};
type PendingDecision = {
  issue_id: string;
  task_id: string;
  stage_id: string;
  subject_id: string | null;
  task_version: number;
  request: { issue_code: string; question: string; options: Array<{ key: string; label: string; consequence: string }> };
};

function ulid() {
  const a = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  let random = 0n;
  for (const b of crypto.getRandomValues(new Uint8Array(10))) random = (random << 8n) | BigInt(b);
  let v = (BigInt(Date.now()) << 80n) | random;
  let s = "";
  for (let i = 0; i < 26; i++) {
    s = a[Number(v & 31n)] + s;
    v >>= 5n;
  }
  return s;
}

async function get<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const r = await p;
  if (!r.response.ok) {
    const error = r.error;
    if (error && typeof error === "object" && "detail" in error) {
      const detail = (error as { detail: unknown }).detail;
      throw Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    if (error !== undefined) throw Error(typeof error === "string" ? error : JSON.stringify(error));
    throw Error((await r.response.text()) || "Request failed");
  }
  if (r.data === undefined) throw Error("API returned no body");
  return r.data;
}

const PRESET_ADMET = {
  schema: "caddsuite.workflow/1",
  name: "ADMET property prediction",
  inputs: {
    compounds: {
      contract: "compound/1.0",
      description: "Registered parent compounds"
    }
  },
  stages: [
    {
      id: "admet",
      kind: "property_prediction",
      engine: "rdkit_rules",
      for_each: "compound",
      input_contracts: { compound: "compound/1.0" },
      input_bindings: { compound: "$compounds" },
      output_contract: "property_prediction_set/1.0",
      params: {
        endpoints: ["drug_likeness", "structural_alerts", "physicochemistry"]
      }
    },
    {
      id: "report",
      kind: "report",
      needs: ["admet"],
      input_contracts: {
        compounds: "compound/1.0",
        property_results: "property_prediction_set/1.0"
      },
      input_bindings: {
        compounds: "$compounds",
        property_results: "admet"
      },
      output_contract: "report_bundle/1.0",
      params: {
        formats: ["html", "json", "csv"]
      }
    }
  ],
  outputs: { report: "report" }
};

const PRESET_LIGAND_3D = {
  schema: "caddsuite.workflow/1",
  name: "Ligand 3D Conformation and Protonation",
  inputs: {
    compounds: {
      contract: "compound/1.0",
      description: "Registered parent compounds"
    }
  },
  stages: [
    {
      id: "admet",
      kind: "property_prediction",
      engine: "rdkit_rules",
      for_each: "compound",
      input_contracts: { compound: "compound/1.0" },
      input_bindings: { compound: "$compounds" },
      output_contract: "property_prediction_set/1.0",
      params: {}
    },
    {
      id: "protonate",
      kind: "chemistry.protonate",
      engine: "dimorphite_dl",
      for_each: "compound",
      input_contracts: { compound: "compound/1.0" },
      input_bindings: { compound: "$compounds" },
      output_contract: "compound_form/1.0",
      params: {
        target_ph: 7.4,
        ambiguous_microstates: "require_decision"
      }
    },
    {
      id: "embed",
      kind: "chemistry.embed",
      engine: "rdkit_etkdg",
      for_each: "compound",
      needs: ["protonate"],
      input_contracts: { form: "compound_form/1.0" },
      input_bindings: { form: "protonate" },
      output_contract: "conformer/1.1",
      params: {
        policy: {
          seed: 42,
          optimizer: "MMFF94"
        }
      }
    },
    {
      id: "report",
      kind: "report",
      needs: ["admet"],
      input_contracts: {
        compounds: "compound/1.0",
        property_results: "property_prediction_set/1.0"
      },
      input_bindings: {
        compounds: "$compounds",
        property_results: "admet"
      },
      output_contract: "report_bundle/1.0",
      params: {
        formats: ["html", "json", "csv"]
      }
    }
  ],
  outputs: { report: "report" }
};

function makeDftWorkflow(paths: EnginePaths = DEFAULT_ENGINE_PATHS, hasPreparedConformer = false) {
  if (hasPreparedConformer) {
    return {
      schema: "caddsuite.workflow/1",
      name: "Ligand Quantum Chemistry / DFT (Psi4)",
      inputs: {
        compounds: {
          contract: "compound/1.0",
          description: "Registered parent compounds"
        },
        form: {
          contract: "compound_form/1.0",
          description: "Prepared ligand form / microstate"
        },
        conformer: {
          contract: "conformer/1.1",
          description: "Prepared ligand 3D conformer / geometry"
        },
        calculation: {
          contract: "qm_calculation/1.2",
          description: "DFT calculation spec (method, basis, protocol)"
        }
      },
      stages: [
        {
          id: "qm",
          kind: "quantum_chemistry",
          engine: "caddsuite.qm.psi4",
          for_each: "compound_form",
          input_contracts: {
            calculation: "qm_calculation/1.2",
            form: "compound_form/1.0",
            conformer: "conformer/1.1"
          },
          input_bindings: {
            calculation: "$calculation",
            form: "$form",
            conformer: "$conformer"
          },
          output_contract: "qm_result/2.1",
          params: {
            engine_parameters: {
              python_executable: paths.psi4_python || "python",
              worker_source_directory: paths.worker_source_dir || "src",
              memory_gb: 2,
              n_threads: 2
            }
          }
        },
        {
          id: "report",
          kind: "report",
          needs: ["qm"],
          input_contracts: {
            compounds: "compound/1.0",
            compound_forms: "compound_form/1.0",
            conformers: "conformer/1.1",
            qm_calculations: "qm_calculation/1.2",
            qm_results: "qm_result/2.1"
          },
          input_bindings: {
            compounds: "$compounds",
            compound_forms: "$form",
            conformers: "$conformer",
            qm_calculations: "$calculation",
            qm_results: "qm"
          },
          output_contract: "report_bundle/1.0",
          params: {
            formats: ["html", "json", "csv"]
          }
        }
      ],
      outputs: {
        report: "report",
        qm: "qm"
      }
    };
  }

  return {
    schema: "caddsuite.workflow/1",
    name: "Ligand Quantum Chemistry / DFT (Psi4)",
    inputs: {
      compounds: {
        contract: "compound/1.0",
        description: "Registered parent compounds"
      },
      calculation: {
        contract: "qm_calculation/1.2",
        description: "DFT calculation spec (method, basis, protocol)"
      }
    },
    stages: [
      {
        id: "admet",
        kind: "property_prediction",
        engine: "rdkit_rules",
        for_each: "compound",
        input_contracts: { compound: "compound/1.0" },
        input_bindings: { compound: "$compounds" },
        output_contract: "property_prediction_set/1.0",
        params: {}
      },
      {
        id: "protonate",
        kind: "chemistry.protonate",
        engine: "dimorphite_dl",
        for_each: "compound",
        input_contracts: { compound: "compound/1.0" },
        input_bindings: { compound: "$compounds" },
        output_contract: "compound_form/1.0",
        params: {
          target_ph: 7.4,
          ambiguous_microstates: "require_decision"
        }
      },
      {
        id: "embed",
        kind: "chemistry.embed",
        engine: "rdkit_etkdg",
        for_each: "compound",
        needs: ["protonate"],
        input_contracts: { form: "compound_form/1.0" },
        input_bindings: { form: "protonate" },
        output_contract: "conformer/1.1",
        params: {
          policy: {
            seed: 42,
            optimizer: "MMFF94"
          }
        }
      },
      {
        id: "qm",
        kind: "quantum_chemistry",
        engine: "caddsuite.qm.psi4",
        for_each: "compound_form",
        needs: ["protonate", "embed"],
        input_contracts: {
          calculation: "qm_calculation/1.2",
          form: "compound_form/1.0",
          conformer: "conformer/1.1"
        },
        input_bindings: {
          calculation: "$calculation",
          form: "protonate",
          conformer: "embed"
        },
        output_contract: "qm_result/2.1",
        params: {
          engine_parameters: {
            python_executable: paths.psi4_python || "python",
            worker_source_directory: paths.worker_source_dir || "src",
            memory_gb: 2,
            n_threads: 2
          }
        }
      },
      {
        id: "report",
        kind: "report",
        needs: ["admet", "protonate", "qm"],
        input_contracts: {
          compounds: "compound/1.0",
          compound_forms: "compound_form/1.0",
          property_results: "property_prediction_set/1.0",
          qm_calculations: "qm_calculation/1.2",
          qm_results: "qm_result/2.1"
        },
        input_bindings: {
          compounds: "$compounds",
          compound_forms: "protonate",
          property_results: "admet",
          qm_calculations: "$calculation",
          qm_results: "qm"
        },
        output_contract: "report_bundle/1.0",
        params: {
          formats: ["html", "json", "csv"]
        }
      }
    ],
    outputs: {
      report: "report",
      qm: "qm"
    }
  };
}

function makeMdWorkflow(paths: EnginePaths = DEFAULT_ENGINE_PATHS) {
  return {
    schema: "caddsuite.workflow/1",
    name: "Protein-Ligand Molecular Dynamics (GROMACS)",
    inputs: {
      compounds: {
        contract: "compound/1.0",
        description: "Registered parent compounds"
      },
      system_build: {
        contract: "system_build_result/1.0",
        description: "Solvated parameterized MD system with topology, coordinates, and index groups"
      },
      stage_input: {
        contract: "md_stage_plan/1.0",
        description: "MD stage execution plan (engine, stage index, topology, coordinates)"
      }
    },
    stages: [
      {
        id: "md",
        kind: "molecular_dynamics",
        engine: "gromacs",
        input_contracts: {
          system_build: "system_build_result/1.0",
          stage_input: "md_stage_plan/1.0"
        },
        input_bindings: {
          system_build: "$system_build",
          stage_input: "$stage_input"
        },
        output_contract: "md_stage_result/1.1",
        params: {
          engine_parameters: {
            memory_MiB: 4096,
            timeout_seconds: 7200,
            gromacs: {
              executable: paths.gmx_executable || "gmx",
              stage_index: 2,
              topology_path: "topol.top",
              coordinates_path: "step4.1_equilibration.gro",
              mdp_path: "step5_production.mdp",
              index_path: "index.ndx",
              output_prefix: "production",
              resource_mode: "gpu",
              cpu_threads: 4,
              gpu_ids: [0]
            }
          }
        }
      },
      {
        id: "report",
        kind: "report",
        needs: ["md"],
        input_contracts: {
          compounds: "compound/1.0",
          md_results: "md_stage_result/1.1"
        },
        input_bindings: {
          compounds: "$compounds",
          md_results: "md"
        },
        output_contract: "report_bundle/1.0",
        params: {
          formats: ["html", "json", "csv"]
        }
      }
    ],
    outputs: {
      md: "md",
      report: "report"
    }
  };
}

function makeMmpbsaWorkflow(paths: EnginePaths = DEFAULT_ENGINE_PATHS) {
  return {
    schema: "caddsuite.workflow/1",
    name: "MM-PBSA End-State Free Energy (gmx_MMPBSA)",
    inputs: {
      compounds: {
        contract: "compound/1.0",
        description: "Registered parent compounds"
      },
      request: {
        contract: "trajectory_processing_request/1.1",
        description: "Periodic boundary condition centered trajectory and index group request"
      },
      energy_plan: {
        contract: "binding_energy_plan/1.0",
        description: "GB/PB solvation parameters, dielectric constants, and entropy options"
      }
    },
    stages: [
      {
        id: "process",
        kind: "trajectory.process",
        engine: "gromacs",
        input_contracts: {
          request: "trajectory_processing_request/1.1"
        },
        input_bindings: {
          request: "$request"
        },
        output_contract: "trajectory_processing_result/1.2",
        params: {
          engine_parameters: {
            gmx_executable: paths.gmx_executable || "gmx",
            python_executable: paths.caddsuite_python || "python",
            output_group_atom_count: 49682,
            timeout_seconds: 3600
          }
        }
      },
      {
        id: "mmgbsa",
        kind: "binding_energy.analyze_processed",
        engine: "gmx_mmpbsa",
        needs: ["process"],
        input_contracts: {
          plan: "binding_energy_plan/1.0",
          preprocessing: "trajectory_processing_result/1.2"
        },
        input_bindings: {
          plan: "$energy_plan",
          preprocessing: "process"
        },
        output_contract: "binding_energy/1.3",
        params: {
          engine_parameters: {
            gmx_mmpbsa_executable: paths.gmx_mmpbsa_executable || "gmx_MMPBSA",
            gmx_executable: paths.gmx_executable || "gmx",
            ambertools_bin: paths.ambertools_bin || "bin",
            python_executable: paths.gmx_mmpbsa_python || "python",
            worker_script: paths.gmx_mmpbsa_worker || "gmx_mmpbsa_worker.py",
            timeout_seconds: 3600,
            mpi_launch_retries: 0
          }
        }
      },
      {
        id: "report",
        kind: "report",
        needs: ["mmgbsa"],
        input_contracts: {
          compounds: "compound/1.0",
          binding_energy_results: "binding_energy/1.3"
        },
        input_bindings: {
          compounds: "$compounds",
          binding_energy_results: "mmgbsa"
        },
        output_contract: "report_bundle/1.0",
        params: {
          formats: ["html", "json", "csv"]
        }
      }
    ],
    outputs: {
      energy: "mmgbsa",
      report: "report"
    }
  };
}

function makeDockingWorkflow(
  chainId = "A",
  exhaustiveness = 16,
  paths: EnginePaths = DEFAULT_ENGINE_PATHS,
  ph = 7.4,
  occupancyPolicy = "highest_occupancy_single_model"
) {
  return {
    schema: "caddsuite.workflow/1",
    name: "ADMET, docking and report",
    inputs: {
      compounds: {
        contract: "compound/1.0"
      },
      target_structure: {
        contract: "structure/1.0"
      }
    },
    stages: [
      {
        id: "admet",
        kind: "property_prediction",
        engine: "rdkit_rules",
        for_each: "compound",
        input_contracts: {
          compound: "compound/1.0"
        },
        input_bindings: {
          compound: "$compounds"
        },
        output_contract: "property_prediction_set/1.0",
        params: {
          endpoints: ["drug_likeness", "structural_alerts", "physicochemistry"]
        }
      },
      {
        id: "protonate",
        kind: "chemistry.protonate",
        engine: "dimorphite_dl",
        for_each: "compound",
        input_contracts: {
          compound: "compound/1.0"
        },
        input_bindings: {
          compound: "$compounds"
        },
        output_contract: "compound_form/1.0",
        params: {
          target_ph: 7.4,
          ambiguous_microstates: "require_decision"
        }
      },
      {
        id: "configured_filter",
        kind: "gate",
        for_each: "compound",
        needs: ["admet", "protonate"],
        input_contracts: {
          predictions: "property_prediction_set/1.0",
          ligand: "compound_form/1.0"
        },
        input_bindings: {
          predictions: "admet",
          ligand: "protonate"
        },
        output_contract: "compound_form/1.0",
        gate: "admet.qed >= 0.4",
        on_fail: "exclude",
        params: {
          field_bindings: {
            "admet.qed": "predictions.qed"
          }
        }
      },
      {
        id: "embed",
        kind: "chemistry.embed",
        engine: "rdkit_etkdg",
        for_each: "compound",
        needs: ["configured_filter"],
        input_contracts: {
          form: "compound_form/1.0"
        },
        input_bindings: {
          form: "configured_filter"
        },
        output_contract: "conformer/1.1",
        params: {
          policy: {
            seed: 42,
            optimizer: "MMFF94"
          }
        }
      },
      {
        id: "prepare_protein",
        kind: "structure.prepare_protein",
        engine: "pdbfixer",
        for_each: "target",
        input_contracts: {
          structure: "structure/1.0"
        },
        input_bindings: {
          structure: "$target_structure"
        },
        output_contract: "prepared_receptor/1.3",
        params: {
          selected_chain_ids: [chainId],
          ph: ph,
          occupancy_policy: occupancyPolicy,
          engine_parameters: {
            python_executable: paths.cadd_python || "python",
            worker_script: paths.pdbfixer_worker || "pdbfixer_worker.py"
          }
        }
      },
      {
        id: "binding_site",
        kind: "structure.binding_site",
        engine: "blind_protein_box",
        for_each: "target",
        needs: ["prepare_protein"],
        input_contracts: {
          structure: "structure/1.0",
          receptor: "prepared_receptor/1.3"
        },
        input_bindings: {
          structure: "$target_structure",
          receptor: "prepare_protein"
        },
        output_contract: "binding_site/1.0",
        params: {
          selected_chain_ids: [chainId]
        }
      },
      {
        id: "dock",
        kind: "docking",
        engine: "vina",
        for_each: "compound",
        needs: ["configured_filter", "embed", "prepare_protein", "binding_site"],
        input_contracts: {
          compound: "compound/1.0",
          form: "compound_form/1.0",
          conformer: "conformer/1.1",
          receptor: "prepared_receptor/1.3",
          target_structure: "structure/1.0",
          site: "binding_site/1.0"
        },
        input_bindings: {
          compound: "$compounds",
          form: "configured_filter",
          conformer: "embed",
          receptor: "prepare_protein",
          target_structure: "$target_structure",
          site: "binding_site"
        },
        output_contract: "docking_result/1.0",
        params: {
          engine_parameters: {
            vina_executable: paths.vina_executable || "vina",
            meeko_python: paths.cadd_python || "python",
            mk_prepare_receptor: paths.mk_prepare_receptor || "mk_prepare_receptor.py",
            mk_prepare_ligand: paths.mk_prepare_ligand || "mk_prepare_ligand.py",
            mk_export: paths.mk_export || "mk_export.py"
          },
          docking_parameters: {
            exhaustiveness: exhaustiveness,
            num_modes: 9,
            energy_range_kcal_mol: 3.0,
            cpu_cores: 2,
            seed: 42
          }
        }
      },
      {
        id: "report",
        kind: "report",
        needs: ["admet", "dock"],
        input_contracts: {
          compounds: "compound/1.0",
          property_results: "property_prediction_set/1.0",
          docking_results: "docking_result/1.0"
        },
        input_bindings: {
          compounds: "$compounds",
          property_results: "admet",
          docking_results: "dock"
        },
        output_contract: "report_bundle/1.0",
        params: {
          formats: ["html", "json", "csv"]
        }
      }
    ],
    outputs: {
      report: "report"
    }
  };
}

function buildTargetStructurePayload(artifact: ProjectArtifact) {
  return {
    schema_version: "structure/1.0",
    id: artifact.id,
    target_id: artifact.id,
    source: "local",
    source_id: artifact.original_name || artifact.kind || "TARGET_RECEPTOR",
    model_index: 1,
    altloc_policy: "first_model_altloc_A",
    entity_sequences: {},
    raw: {
      artifact_id: artifact.id,
      role: "raw_structure",
      sha256: artifact.sha256
    }
  };
}

function buildDefaultCalculationPayload(
  compound?: Compound,
  formId?: string,
  conformerId?: string,
  method = "b3lyp",
  basis = "def2-svp",
  protocol = "single_point",
  solvation: "gas" | "water" = "gas",
  charge = 0,
  multiplicity = 1
) {
  const calcId = ulid();
  const effFormId = (formId && formId.trim()) || (compound?.payload?.form_id as string) || "";
  const effConformerId = (conformerId && conformerId.trim()) || (compound?.payload?.conformer_id as string) || "";
  const accession = compound?.accession ? `${compound.accession}_QM_001` : "CMP0001_QM_001";
  return {
    schema_version: "qm_calculation/1.2",
    id: calcId,
    accession: accession,
    form_id: effFormId,
    compound_id: compound?.id || null,
    geometry_source: {
      kind: "conformer",
      id: effConformerId
    },
    engine: {
      name: "Psi4",
      version: "1.11",
      kind: "engine",
      license_class: "open_source_permissive"
    },
    adapter: {
      name: "caddsuite.qm.psi4",
      version: "0.1.0",
      kind: "adapter",
      license_class: "open_source_permissive"
    },
    model: {
      method: method.toLowerCase(),
      basis: basis.toLowerCase()
    },
    protocol: protocol,
    charge: charge,
    multiplicity: multiplicity,
    solvation: solvation === "water" ? { model: "ddx_pcm", solvent: "water" } : null,
    requested_properties: ["total_energy_Eh", "dipole_D", "orbitals"]
  };
}

type PresetKey = "admet" | "docking" | "ligand_3d" | "dft" | "md" | "mmpbsa" | "custom";
type TabKey = "pipeline" | "evidence" | "compounds" | "monitor" | "structures" | "settings";

export default function App() {
  const [url, setUrl] = useState("http://127.0.0.1:8000");
  const [token, setToken] = useState(() => {
    try {
      return localStorage.getItem("caddsuite_api_token") || "";
    } catch {
      return "";
    }
  });
  const [ok, setOk] = useState(false);
  const [activeTab, setActiveTab] = useState<TabKey>("pipeline");
  const [projects, setProjects] = useState<Project[]>([]);
  const [pid, setPid] = useState("");
  const [compounds, setCompounds] = useState<Compound[]>([]);
  const [caps, setCaps] = useState<Record<string, unknown>[]>([]);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [smi, setSmi] = useState("");
  const [cname, setCname] = useState("");
  const [selectedPreset, setSelectedPreset] = useState<PresetKey>("docking");
  const [selectedTargetId, setSelectedTargetId] = useState<string>("");
  const [targetChain, setTargetChain] = useState<string>("A");
  const [exhaustiveness, setExhaustiveness] = useState<number>(16);
  const [mdLengthNs, setMdLengthNs] = useState<number>(1.0);
  const [mdTimestepFs, setMdTimestepFs] = useState<number>(2.0);
  const [mdTempK, setMdTempK] = useState<number>(300.0);
  const [receptorPh, setReceptorPh] = useState<number>(7.4);
  const [altlocPolicy, setAltlocPolicy] = useState<string>("highest_occupancy_single_model");
  const [qmCompoundId, setQmCompoundId] = useState<string>("");
  const [qmMethod, setQmMethod] = useState<string>("b3lyp");
  const [qmBasis, setQmBasis] = useState<string>("def2-svp");
  const [qmProtocol, setQmProtocol] = useState<string>("single_point");
  const [qmSolvation, setQmSolvation] = useState<"gas" | "water">("gas");
  const [qmCharge, setQmCharge] = useState<number>(0);
  const [qmMultiplicity, setQmMultiplicity] = useState<number>(1);
  const [qmFormId, setQmFormId] = useState<string>("");
  const [qmConformerId, setQmConformerId] = useState<string>("");
  const [engineConfig, setEngineConfig] = useState<EngineDiscoveryReport | null>(null);
  const [enginePaths, setEnginePaths] = useState<EnginePaths>(() => {
    try {
      const saved = localStorage.getItem("caddsuite_engine_paths");
      if (saved) return { ...DEFAULT_ENGINE_PATHS, ...JSON.parse(saved) };
    } catch {
      // fallback
    }
    return DEFAULT_ENGINE_PATHS;
  });
  const [wf, setWf] = useState(() => JSON.stringify(makeDockingWorkflow("A", 16, enginePaths), null, 2));
  const [inputs, setInputs] = useState(JSON.stringify({ compounds: [] }, null, 2));
  const [plan, setPlan] = useState<unknown>(null);
  const [history, setHistory] = useState<HistoryRun[]>([]);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [run, setRun] = useState<Snapshot | null>(null);
  const [rid, setRid] = useState("");
  const [lineData, setLineData] = useState<Lineage | null>(null);
  const [projectArtifacts, setProjectArtifacts] = useState<ProjectArtifact[]>([]);
  const [viewingArtifact, setViewingArtifact] = useState<ArtifactItem | null>(null);
  const [topologyId, setTopologyId] = useState("");
  const [trajectoryId, setTrajectoryId] = useState("");
  const [volumeArtifact, setVolumeArtifact] = useState<ArtifactItem | null>(null);
  const [logText, setLogText] = useState("");
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState<PendingDecision[]>([]);
  const [decidedBy, setDecidedBy] = useState("");
  const [rationale, setRationale] = useState("");
  const [selectedRunIds, setSelectedRunIds] = useState<Set<string>>(new Set());
  const [isDeletingRuns, setIsDeletingRuns] = useState(false);
  const [mdDemoInfo, setMdDemoInfo] = useState<Record<string, unknown> | null>(null);
  const [isProvisioningMd, setIsProvisioningMd] = useState(false);
  const [mdCandidates, setMdCandidates] = useState<RecordedMdCandidate[]>([]);
  const [selectedMdRunId, setSelectedMdRunId] = useState("");
  const [mmpbsaDemoInfo, setMmpbsaDemoInfo] = useState<Record<string, unknown> | null>(null);
  const [isProvisioningMmpbsa, setIsProvisioningMmpbsa] = useState(false);
  const [mmpbsaCandidates, setMmpbsaCandidates] = useState<RecordedMmpbsaCandidate[]>([]);
  const [selectedMmpbsaRunId, setSelectedMmpbsaRunId] = useState("");
  const [analyzingTrajectory, setAnalyzingTrajectory] = useState(false);
  const [trajectoryAnalytics, setTrajectoryAnalytics] = useState<TrajectoryAnalyticsResult | null>(null);
  const analyticsGeneration = useRef(0);
  useEffect(() => {
    analyticsGeneration.current += 1;
    setTrajectoryAnalytics(null);
  }, [pid, topologyId, trajectoryId]);


  const api = useMemo(() => createApiClient(url, token), [url, token]);
  const currentProjectId = useRef(pid);
  const lastRunStatus = useRef("");
  currentProjectId.current = pid;
  const project = projects.find((x) => x.id === pid);

  const structureArtifacts = useMemo(() => {
    return projectArtifacts.filter((a) => structureFormat(a) === "mmcif" || structureFormat(a) === "pdb");
  }, [projectArtifacts]);

  const activeTargetArtifact = useMemo(() => {
    if (selectedTargetId) {
      const found = structureArtifacts.find((a) => a.id === selectedTargetId);
      if (found) return found;
    }
    return null;
  }, [selectedTargetId, structureArtifacts]);

  useEffect(() => {
    if (!selectedTargetId && structureArtifacts.length === 1) {
      setSelectedTargetId(structureArtifacts[0].id);
    }
  }, [selectedTargetId, structureArtifacts]);

  const preparedConformers = useMemo(() => {
    const list: Array<{
      conformer_id: string;
      form_id: string;
      compound_id?: string | null;
      generator?: string;
      energy_kcal_per_mol?: number | null;
      structure_artifact_id?: string;
      label: string;
      conformer_payload?: Record<string, unknown>;
      form_payload?: Record<string, unknown>;
    }> = [];
    const seen = new Set<string>();

    if (dashboard?.prepared_conformers) {
      for (const pc of dashboard.prepared_conformers) {
        if (!seen.has(pc.conformer_id)) {
          seen.add(pc.conformer_id);
          const comp = compounds.find((c) => c.id === pc.compound_id);
          const compName = comp ? (comp.name || comp.accession) : (pc.compound_id ? `Compound ${pc.compound_id.slice(0, 8)}` : "");
          const energyStr = pc.energy_kcal_per_mol != null ? ` (${pc.energy_kcal_per_mol.toFixed(1)} kcal/mol)` : "";
          const genStr = pc.generator ? ` [${pc.generator}]` : "";
          list.push({
            conformer_id: pc.conformer_id,
            form_id: pc.form_id,
            compound_id: pc.compound_id,
            generator: pc.generator,
            energy_kcal_per_mol: pc.energy_kcal_per_mol,
            structure_artifact_id: pc.structure_artifact_id,
            label: `Conformer ${pc.conformer_id.slice(0, 8)}... (Form: ${pc.form_id.slice(0, 8)}...)${compName ? ` - ${compName}` : ""}${genStr}${energyStr}`,
            conformer_payload: pc.conformer_payload,
            form_payload: pc.form_payload,
          });
        }
      }
    }

    for (const comp of compounds) {
      const p = comp.payload;
      if (p && typeof p.conformer_id === "string" && typeof p.form_id === "string") {
        if (!seen.has(p.conformer_id)) {
          seen.add(p.conformer_id);
          list.push({
            conformer_id: p.conformer_id,
            form_id: p.form_id,
            compound_id: comp.id,
            generator: typeof p.generator === "string" ? p.generator : undefined,
            energy_kcal_per_mol: typeof p.energy_kcal_per_mol === "number" ? p.energy_kcal_per_mol : undefined,
            label: `Conformer ${p.conformer_id.slice(0, 8)}... (Form: ${p.form_id.slice(0, 8)}...) - ${comp.name || comp.accession}`,
          });
        }
      }
    }

    return list;
  }, [dashboard?.prepared_conformers, compounds]);

  const compatibleConformers = useMemo(() => {
    if (!qmCompoundId) return preparedConformers;
    return preparedConformers.filter((c) => !c.compound_id || c.compound_id === qmCompoundId);
  }, [preparedConformers, qmCompoundId]);

  const hasSystemBuild = useMemo(() => {
    try {
      const obj = JSON.parse(inputs) as Record<string, unknown>;
      return Boolean(obj && typeof obj === "object" && obj.system_build);
    } catch {
      return false;
    }
  }, [inputs]);

  const hasEnergyPlan = useMemo(() => {
    try {
      const obj = JSON.parse(inputs) as Record<string, unknown>;
      return Boolean(obj && typeof obj === "object" && obj.energy_plan);
    } catch {
      return false;
    }
  }, [inputs]);

  const refresh = useCallback(
    async (id: string) => {
      const r = await api.GET("/v1/projects/{project_id}/compounds", { params: { path: { project_id: id } } });
      if (!r.response.ok) throw Error("Unable to load compound registry");
      if (currentProjectId.current !== id) return;
      setCompounds((r.data || []) as Compound[]);
    },
    [api]
  );

  const refreshArtifacts = useCallback(
    async (id: string) => {
      const r = await api.GET("/v1/projects/{project_id}/artifacts", { params: { path: { project_id: id } } });
      if (!r.response.ok) throw Error("Unable to load project artifacts");
      if (currentProjectId.current !== id) return;
      setProjectArtifacts((r.data || []) as ProjectArtifact[]);
    },
    [api]
  );

  const refreshDashboard = useCallback(
    async (id: string) => {
      const r = await api.GET("/v1/projects/{project_id}/dashboard", { params: { path: { project_id: id } } });
      if (!r.response.ok) throw Error("Unable to load project dashboard");
      if (currentProjectId.current !== id) return;
      setDashboard(r.data as Dashboard);
    },
    [api]
  );

  const refreshHistory = useCallback(
    async (id: string) => {
      const r = await api.GET("/v1/projects/{project_id}/runs", { params: { path: { project_id: id }, query: { limit: 20 } } });
      if (!r.response.ok) throw Error("Unable to load project run history");
      if (currentProjectId.current !== id) return;
      setHistory((r.data || []) as HistoryRun[]);
    },
    [api]
  );

  const refreshMdCandidates = useCallback(
    async (id: string) => {
      try {
        const resp = await fetch(`${url}/v1/projects/${id}/recorded-md-candidates`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!resp.ok) return;
        const list = (await resp.json()) as RecordedMdCandidate[];
        if (currentProjectId.current !== id) return;
        setMdCandidates(list);
        if (list.length > 0) {
          setSelectedMdRunId((prev) => (list.some((c) => c.run_id === prev) ? prev : list[0].run_id));
        } else {
          setSelectedMdRunId("");
        }
      } catch {
        // ignore background fetch failures
      }
    },
    [url, token]
  );

  const refreshMmpbsaCandidates = useCallback(
    async (id: string) => {
      try {
        const resp = await fetch(`${url}/v1/projects/${id}/recorded-mmpbsa-candidates`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!resp.ok) return;
        const list = (await resp.json()) as RecordedMmpbsaCandidate[];
        if (currentProjectId.current !== id) return;
        setMmpbsaCandidates(list);
        if (list.length > 0) {
          setSelectedMmpbsaRunId((prev) => (list.some((c) => c.run_id === prev) ? prev : list[0].run_id));
        } else {
          setSelectedMmpbsaRunId("");
        }
      } catch {
        // ignore background fetch failures
      }
    },
    [url, token]
  );

  async function connect(tokenOverride?: string) {
    const effectiveToken = tokenOverride !== undefined ? tokenOverride : token;
    try {
      setErr("");
      if (!effectiveToken.trim()) {
        setOk(false);
        setErr("API access token is required. For local development, enter your configured token (default: caddsuite-local-2026).");
        return;
      }
      if (tokenOverride !== undefined) {
        setToken(tokenOverride);
      }
      const client = tokenOverride !== undefined ? createApiClient(url, tokenOverride) : api;
      const [p, c, eng] = await Promise.all([
        get(client.GET("/v1/projects")),
        get(client.GET("/v1/workflows/capabilities")),
        get(client.GET("/v1/system/engine-config")).catch(() => null),
      ]);
      setProjects(p as Project[]);
      setCaps(((c as { capabilities?: Record<string, unknown>[] }).capabilities) || []);
      if (eng) {
        const report = eng as EngineDiscoveryReport;
        setEngineConfig(report);
        const saved = localStorage.getItem("caddsuite_engine_paths");
        let mergedPaths = { ...DEFAULT_ENGINE_PATHS, ...report.paths };
        if (saved) {
          try {
            mergedPaths = { ...mergedPaths, ...JSON.parse(saved) };
          } catch {
            // keep mergedPaths
          }
        }
        setEnginePaths(mergedPaths);
        if (selectedPreset === "docking") {
          setWf(JSON.stringify(makeDockingWorkflow(targetChain, exhaustiveness, mergedPaths, receptorPh, altlocPolicy), null, 2));
        } else if (selectedPreset === "dft") {
          const matchedConf = dashboard?.prepared_conformers?.find((c) => c.conformer_id === qmConformerId) || preparedConformers.find((c) => c.conformer_id === qmConformerId);
          const hasPrep = Boolean(matchedConf?.conformer_payload && matchedConf?.form_payload);
          setWf(JSON.stringify(makeDftWorkflow(mergedPaths, hasPrep), null, 2));
        } else if (selectedPreset === "md") {
          setWf(JSON.stringify(makeMdWorkflow(mergedPaths), null, 2));
        } else if (selectedPreset === "mmpbsa") {
          setWf(JSON.stringify(makeMmpbsaWorkflow(mergedPaths), null, 2));
        }
      }
      setOk(true);
      try {
        localStorage.setItem("caddsuite_api_token", effectiveToken);
      } catch {
        // ignore
      }
      if (!pid && (p as Project[]).length) setPid((p as Project[])[0].id);
      setMsg("Connected to CADD Suite API");
    } catch (e) {
      setOk(false);
      const errStr = String(e);
      if (errStr.includes("Unauthorized")) {
        setErr("Unauthorized: Invalid or missing API access token. Please verify your token matches CADDSUITE_API_TOKEN on your server (local default: caddsuite-local-2026).");
      } else {
        setErr(errStr);
      }
    }
  }

  function saveEnginePaths(newPaths: EnginePaths) {
    setEnginePaths(newPaths);
    localStorage.setItem("caddsuite_engine_paths", JSON.stringify(newPaths));
    setMsg("Engine configuration saved to local storage.");
    if (selectedPreset === "docking") {
      setWf(JSON.stringify(makeDockingWorkflow(targetChain, exhaustiveness, newPaths, receptorPh, altlocPolicy), null, 2));
    } else if (selectedPreset === "dft") {
      const matchedConf = dashboard?.prepared_conformers?.find((c) => c.conformer_id === qmConformerId) || preparedConformers.find((c) => c.conformer_id === qmConformerId);
      const hasPrep = Boolean(matchedConf?.conformer_payload && matchedConf?.form_payload);
      setWf(JSON.stringify(makeDftWorkflow(newPaths, hasPrep), null, 2));
    } else if (selectedPreset === "md") {
      setWf(JSON.stringify(makeMdWorkflow(newPaths), null, 2));
    } else if (selectedPreset === "mmpbsa") {
      setWf(JSON.stringify(makeMmpbsaWorkflow(newPaths), null, 2));
    }
  }

  function resetEnginePaths() {
    localStorage.removeItem("caddsuite_engine_paths");
    const fresh = engineConfig?.paths ? { ...DEFAULT_ENGINE_PATHS, ...engineConfig.paths } : DEFAULT_ENGINE_PATHS;
    setEnginePaths(fresh);
    setMsg("Engine configuration reset to auto-discovered defaults.");
    if (selectedPreset === "docking") {
      setWf(JSON.stringify(makeDockingWorkflow(targetChain, exhaustiveness, fresh, receptorPh, altlocPolicy), null, 2));
    } else if (selectedPreset === "dft") {
      const matchedConf = dashboard?.prepared_conformers?.find((c) => c.conformer_id === qmConformerId) || preparedConformers.find((c) => c.conformer_id === qmConformerId);
      const hasPrep = Boolean(matchedConf?.conformer_payload && matchedConf?.form_payload);
      setWf(JSON.stringify(makeDftWorkflow(fresh, hasPrep), null, 2));
    } else if (selectedPreset === "md") {
      setWf(JSON.stringify(makeMdWorkflow(fresh), null, 2));
    } else if (selectedPreset === "mmpbsa") {
      setWf(JSON.stringify(makeMmpbsaWorkflow(fresh), null, 2));
    }
  }

  useEffect(() => {
    setOk(false);
  }, [url, token]);

  useEffect(() => {
    setMdDemoInfo(null);
    setMmpbsaDemoInfo(null);
    setMdCandidates([]);
    setSelectedMdRunId("");
    setMmpbsaCandidates([]);
    setSelectedMmpbsaRunId("");
    setRun(null);
    setRid("");
    setPending([]);
    setLineData(null);
    setLogText("");
    setSelectedTargetId("");
    setInputs(JSON.stringify({ compounds: [] }, null, 2));
  }, [pid]);

  useEffect(() => {
    if (ok && pid) {
      void Promise.all([
        refresh(pid),
        refreshHistory(pid),
        refreshArtifacts(pid),
        refreshDashboard(pid),
        refreshMdCandidates(pid),
        refreshMmpbsaCandidates(pid),
      ]).catch((e) => setErr(String(e)));
    } else {
      setCompounds([]);
      setHistory([]);
      setProjectArtifacts([]);
      setDashboard(null);
      setViewingArtifact(null);
      setMdCandidates([]);
      setSelectedMdRunId("");
      setMmpbsaCandidates([]);
      setSelectedMmpbsaRunId("");
    }
  }, [ok, pid, refresh, refreshHistory, refreshArtifacts, refreshDashboard, refreshMdCandidates, refreshMmpbsaCandidates]);

  useEffect(() => {
    if (!ok || !pid) return;
    const t = setInterval(() => void refreshDashboard(pid).catch((e) => setErr(String(e))), 10000);
    return () => clearInterval(t);
  }, [ok, pid, refreshDashboard]);

  const applyPreset = useCallback(
    (
      key: PresetKey,
      targetArt = activeTargetArtifact,
      comps = compounds,
      chain = targetChain,
      exh = exhaustiveness,
      recPh = receptorPh,
      altloc = altlocPolicy,
      simLengthNs = mdLengthNs,
      simTimestepFs = mdTimestepFs,
      simTempK = mdTempK,
      method = qmMethod,
      basis = qmBasis,
      protocol = qmProtocol,
      solvation = qmSolvation,
      charge = qmCharge,
      multiplicity = qmMultiplicity,
      targetQmCompId = qmCompoundId,
      formId = qmFormId,
      conformerId = qmConformerId
    ) => {
      setSelectedPreset(key);
      setPlan(null);
      setErr("");
      if (key === "admet") {
        setWf(JSON.stringify(PRESET_ADMET, null, 2));
        setInputs(JSON.stringify({ compounds: comps.map((c) => c.payload) }, null, 2));
      } else if (key === "docking") {
        setWf(JSON.stringify(makeDockingWorkflow(chain, exh, enginePaths, recPh, altloc), null, 2));
        const inputObj: Record<string, unknown> = {
          compounds: comps.map((c) => c.payload),
        };
        if (targetArt) {
          inputObj.target_structure = buildTargetStructurePayload(targetArt);
        }
        setInputs(JSON.stringify(inputObj, null, 2));
      } else if (key === "ligand_3d") {
        setWf(JSON.stringify(PRESET_LIGAND_3D, null, 2));
        setInputs(JSON.stringify({ compounds: comps.map((c) => c.payload) }, null, 2));
      } else if (key === "dft") {
        const selectedComp = comps.find((c) => c.id === targetQmCompId) || comps[0];
        const matchedConf = dashboard?.prepared_conformers?.find((c) => c.conformer_id === conformerId) || preparedConformers.find((c) => c.conformer_id === conformerId);
        const hasPrep = Boolean(matchedConf?.conformer_payload && matchedConf?.form_payload);
        setWf(JSON.stringify(makeDftWorkflow(enginePaths, hasPrep), null, 2));
        const calcPayload = buildDefaultCalculationPayload(
          selectedComp,
          formId,
          conformerId,
          method,
          basis,
          protocol,
          solvation,
          charge,
          multiplicity
        );
        const dftInputs: Record<string, unknown> = {
          compounds: comps.map((c) => c.payload),
          calculation: calcPayload,
        };
        if (hasPrep && matchedConf?.conformer_payload && matchedConf?.form_payload) {
          dftInputs.form = matchedConf.form_payload;
          dftInputs.conformer = matchedConf.conformer_payload;
        }
        setInputs(JSON.stringify(dftInputs, null, 2));
      } else if (key === "md") {
        setWf(JSON.stringify(makeMdWorkflow(enginePaths), null, 2));
        if (pid) void refreshMdCandidates(pid);
        if (mdDemoInfo) {
          void loadDemoMdSystem();
        } else {
          setInputs(
            JSON.stringify(
              {
                compounds: comps.map((c) => c.payload),
              },
              null,
              2
            )
          );
        }
      } else if (key === "mmpbsa") {
        setWf(JSON.stringify(makeMmpbsaWorkflow(enginePaths), null, 2));
        if (pid) void refreshMmpbsaCandidates(pid);
        if (mmpbsaDemoInfo) {
          void loadDemoMmpbsaSystem();
        } else {
          setInputs(
            JSON.stringify(
              {
                compounds: comps.map((c) => c.payload),
              },
              null,
              2
            )
          );
        }
      }
    },
    [activeTargetArtifact, compounds, targetChain, exhaustiveness, receptorPh, altlocPolicy, mdLengthNs, mdTimestepFs, mdTempK, enginePaths, qmMethod, qmBasis, qmProtocol, qmSolvation, qmCharge, qmMultiplicity, qmCompoundId, qmFormId, qmConformerId, dashboard?.prepared_conformers, preparedConformers, pid, refreshMdCandidates, refreshMmpbsaCandidates, mdDemoInfo, mmpbsaDemoInfo]
  );

  useEffect(() => {
    if (selectedPreset === "custom") return;
    if (selectedPreset === "docking") {
      const inputObj: Record<string, unknown> = {
        compounds: compounds.map((c) => c.payload),
      };
      if (activeTargetArtifact) {
        inputObj.target_structure = buildTargetStructurePayload(activeTargetArtifact);
      }
      setInputs(JSON.stringify(inputObj, null, 2));
    } else if (selectedPreset === "dft") {
      const selectedComp = compounds.find((c) => c.id === qmCompoundId) || compounds[0];
      const matchedConf = dashboard?.prepared_conformers?.find((c) => c.conformer_id === qmConformerId) || preparedConformers.find((c) => c.conformer_id === qmConformerId);
      const hasPrep = Boolean(matchedConf?.conformer_payload && matchedConf?.form_payload);
      setWf(JSON.stringify(makeDftWorkflow(enginePaths, hasPrep), null, 2));
      const calcPayload = buildDefaultCalculationPayload(
        selectedComp,
        qmFormId,
        qmConformerId,
        qmMethod,
        qmBasis,
        qmProtocol,
        qmSolvation,
        qmCharge,
        qmMultiplicity
      );
      const dftInputs: Record<string, unknown> = {
        compounds: compounds.map((c) => c.payload),
        calculation: calcPayload,
      };
      if (hasPrep && matchedConf?.conformer_payload && matchedConf?.form_payload) {
        dftInputs.form = matchedConf.form_payload;
        dftInputs.conformer = matchedConf.conformer_payload;
      }
      setInputs(JSON.stringify(dftInputs, null, 2));
    } else if (selectedPreset === "md") {
      if (!mdDemoInfo) {

        setInputs(
          JSON.stringify(
            {
              compounds: compounds.map((c) => c.payload),
            },
            null,
            2
          )
        );
      }
    } else if (selectedPreset === "mmpbsa") {
      if (!mmpbsaDemoInfo) {
        setInputs(
          JSON.stringify(
            {
              compounds: compounds.map((c) => c.payload),
            },
            null,
            2
          )
        );
      }
    } else if (selectedPreset === "admet" || selectedPreset === "ligand_3d") {
      setInputs(JSON.stringify({ compounds: compounds.map((c) => c.payload) }, null, 2));
    }
  }, [compounds, activeTargetArtifact, selectedPreset, mdLengthNs, mdTimestepFs, mdTempK, mmpbsaDemoInfo, qmCompoundId, qmFormId, qmConformerId, qmMethod, qmBasis, qmProtocol, qmSolvation, qmCharge, qmMultiplicity, enginePaths, dashboard?.prepared_conformers, preparedConformers]);

  async function loadDemoMdSystem(targetRunId?: string) {
    if (!pid) return;
    setIsProvisioningMd(true);
    setErr("");
    try {
      const effectiveRunId = targetRunId || selectedMdRunId;
      const runParam = effectiveRunId ? `?run_id=${encodeURIComponent(effectiveRunId)}` : "";
      const resp = await fetch(
        `${url}/v1/projects/${pid}/provision-demo-md-system${runParam}`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
        }
      );
      if (!resp.ok) {
        let errorDetail = "";
        try {
          const errJson = (await resp.json()) as { detail?: unknown };
          errorDetail = typeof errJson?.detail === "string" ? errJson.detail : JSON.stringify(errJson?.detail || errJson);
        } catch {
          errorDetail = await resp.text();
        }
        throw new Error(`Prepared MD inputs could not be loaded: ${errorDetail}`);
      }
      const data = (await resp.json()) as {
        status: string;
        system_build: Record<string, unknown>;
        stage_input: Record<string, unknown>;
        info: Record<string, unknown>;
      };
      setMdDemoInfo(data.info);
      setInputs(
        JSON.stringify(
          {
            compounds: compounds.map((c) => c.payload),
            system_build: data.system_build,
            stage_input: data.stage_input,
          },
          null,
          2
        )
      );
      setMsg("✓ Recorded MD inputs loaded. Original system identity and parameter artifacts are retained.");
      await refreshArtifacts(pid);
    } catch (e) {
      setErr(String(e));
    } finally {
      setIsProvisioningMd(false);
    }
  }

  async function loadDemoMmpbsaSystem(targetRunId?: string) {
    if (!pid) return;
    setIsProvisioningMmpbsa(true);
    setErr("");
    try {
      const effectiveRunId = targetRunId || selectedMmpbsaRunId;
      const runParam = effectiveRunId ? `?run_id=${encodeURIComponent(effectiveRunId)}` : "";
      const resp = await fetch(`${url}/v1/projects/${pid}/provision-demo-mmpbsa${runParam}`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      });
      if (!resp.ok) {
        let errorDetail = "";
        try {
          const errJson = (await resp.json()) as { detail?: unknown };
          errorDetail = typeof errJson?.detail === "string" ? errJson.detail : JSON.stringify(errJson?.detail || errJson);
        } catch {
          errorDetail = await resp.text();
        }
        throw new Error(`Recorded binding-energy inputs could not be loaded: ${errorDetail}`);
      }
      const data = (await resp.json()) as {
        status: string;
        request: Record<string, unknown>;
        energy_plan: Record<string, unknown>;
        info: Record<string, unknown>;
      };
      setMmpbsaDemoInfo(data.info);
      setInputs(
        JSON.stringify(
          {
            compounds: compounds.map((c) => c.payload),
            request: data.request,
            energy_plan: data.energy_plan,
          },
          null,
          2
        )
      );
      setMsg("✓ Recorded binding-energy inputs loaded with their original identity and method.");
      await refreshArtifacts(pid);
    } catch (e) {
      setErr(String(e));
    } finally {
      setIsProvisioningMmpbsa(false);
    }
  }

  async function runTrajectoryAnalysis(targetTopId?: string, targetTrajId?: string) {
    if (!pid) return;
    const generation = analyticsGeneration.current;
    setAnalyzingTrajectory(true);
    setErr("");
    try {
      const effectiveTrajId = targetTrajId || trajectoryId;
      const effectiveTopId = targetTopId || topologyId;
      if (!effectiveTopId || !effectiveTrajId) {
        throw new Error("Select the matching topology and trajectory before loading recorded metrics.");
      }
      const topParam = effectiveTopId ? `&topology_artifact_id=${effectiveTopId}` : "";
      const trajParam = effectiveTrajId ? `&trajectory_artifact_id=${effectiveTrajId}` : "";
      const resp = await fetch(`${url}/v1/projects/${pid}/trajectories/analyze?${topParam}${trajParam}`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
      if (!resp.ok) {
        const body = await resp.text();
        throw new Error(`Trajectory analysis failed: ${body}`);
      }
      const data = (await resp.json()) as TrajectoryAnalyticsResult;
      if (generation !== analyticsGeneration.current) return;
      setTrajectoryAnalytics(data);
      setMsg("✓ Recorded trajectory metrics loaded from the completed workflow.");
      await refreshArtifacts(pid);
    } catch (e) {
      setErr(String(e));
    } finally {
      setAnalyzingTrajectory(false);
    }
  }

  async function createProject(e: React.FormEvent) {
    e.preventDefault();
    try {
      const p = (await get(api.POST("/v1/projects", { body: { slug, name } }))) as Project;
      setProjects((x) => [...x, p]);
      setPid(p.id);
      setName("");
      setSlug("");
      setMsg("Project created: " + p.slug);
    } catch (x) {
      setErr(String(x));
    }
  }

  async function deleteProject(id: string, projectName: string) {
    if (!window.confirm(`Are you sure you want to delete project "${projectName}"? This removes project records and run history. Export first to retain provenance; shared files stay in storage.`)) return;
    try {
      const res = await api.DELETE("/v1/projects/{project_id}", { params: { path: { project_id: id } } });
      if (!res.response.ok) throw Error("Failed to delete project: " + (await res.response.text()));
      setProjects((list) => list.filter((p) => p.id !== id));
      if (pid === id) {
        setPid("");
        setRid("");
        setRun(null);
        setLineData(null);
        setCompounds([]);
        setProjectArtifacts([]);
        setDashboard(null);
        setViewingArtifact(null);
      }
      setMsg("Project deleted: " + projectName);
    } catch (x) {
      setErr(String(x));
    }
  }

  async function addCompound(e: React.FormEvent) {
    e.preventDefault();
    try {
      const r = (await get(
        api.POST("/v1/projects/{project_id}/compounds", {
          params: { path: { project_id: pid } },
          body: { smiles: smi, name: cname },
        })
      )) as unknown as { compound: { accession: string }; created: boolean };
      await refresh(pid);
      await refreshDashboard(pid);
      setMsg((r.created ? "Registered " : "Matched existing identity ") + r.compound.accession + "; raw input retained");
      setSmi("");
      setCname("");
    } catch (x) {
      setErr(String(x));
    }
  }

  async function planWorkflow() {
    try {
      setErr("");
      const parsed = JSON.parse(wf) as { stages?: unknown[]; inputs?: Record<string, unknown> };
      if (!parsed.stages || !Array.isArray(parsed.stages) || parsed.stages.length === 0) {
        setPlan(null);
        setErr("Workflow must have at least 1 stage. Select a preset above or add stages.");
        return;
      }
      const res = await get(api.POST("/v1/workflows/plan", { body: parsed as never }));
      setPlan(res);
      setErr("");
      setMsg("✓ Workflow compiled successfully against installed capabilities!");
    } catch (x) {
      setPlan(null);
      setErr(String(x));
    }
  }

  async function submit() {
    try {
      setErr("");
      if (compounds.length === 0) {
        setErr("Please register at least one compound in the Ligand Registry before executing a workflow.");
        setActiveTab("compounds");
        return;
      }
      const parsed = JSON.parse(wf) as { stages?: unknown[]; inputs?: Record<string, unknown> };
      if (!parsed.stages || !Array.isArray(parsed.stages) || parsed.stages.length === 0) {
        setErr("Workflow must have at least 1 stage before submitting. Please select a preset.");
        return;
      }

      if (parsed.inputs && "target_structure" in parsed.inputs && !activeTargetArtifact) {
        setErr("Docking requires a target macromolecular structure. Please upload or select a .cif/.pdb target receptor file.");
        return;
      }

      const inputObj = JSON.parse(inputs) as Record<string, unknown>;

      if (parsed.inputs && "calculation" in parsed.inputs) {
        const calc = inputObj.calculation as Record<string, unknown> | undefined;
        const geomSource = calc?.geometry_source as Record<string, unknown> | undefined;
        const fId = typeof calc?.form_id === "string" ? calc.form_id.trim() : "";
        const cId = typeof geomSource?.id === "string" ? geomSource.id.trim() : "";

        if (!fId) {
          setErr("Quantum chemistry (DFT) requires an explicit target form/microstate identity linked to a prepared structure. Please select or enter a valid Target Form ID.");
          return;
        }

        if (!cId) {
          setErr("Quantum chemistry (DFT) requires an explicit target conformer/geometry identity linked to a 3D structure. Please select an available prepared conformer or enter a valid Target Conformer ID.");
          return;
        }

        if (fId === "00000000000000000000000000" || cId === "00000000000000000000000000") {
          setErr("Quantum chemistry (DFT) rejects zero-filled placeholder identities. Please link actual prepared structure identities.");
          return;
        }

        const isFileArtifactId = projectArtifacts.some((a) => a.id === cId);
        if (isFileArtifactId) {
          setErr(
            `Quantum chemistry geometry_source.id ('${cId}') is a file artifact ID, not a Conformer entity ID. Please select a prepared Conformer entity or enter its entity ULID.`
          );
          return;
        }

        const matchedConf = preparedConformers.find((c) => c.conformer_id === cId);
        if (matchedConf && matchedConf.form_id !== fId) {
          setErr(
            `Quantum chemistry lineage mismatch: selected conformer '${cId}' belongs to form '${matchedConf.form_id}', but target form is '${fId}'.`
          );
          return;
        }

        if (matchedConf && matchedConf.compound_id && calc?.compound_id && matchedConf.compound_id !== calc.compound_id) {
          setErr(
            `Quantum chemistry lineage mismatch: selected conformer '${cId}' belongs to compound '${matchedConf.compound_id}', but target compound is '${calc.compound_id}'.`
          );
          return;
        }
      }

      if (parsed.inputs && "system_build" in parsed.inputs && !inputObj.system_build) {
        setErr("Molecular Dynamics (MD) requires a prepared, solvated system (system_build). In an existing project with a recorded MD run, click 'Load recorded MD inputs', or supply a valid system_build contract in the inputs editor.");
        return;
      }

      if (parsed.inputs && "energy_plan" in parsed.inputs && !inputObj.energy_plan) {
        setErr("MM-PBSA binding energy requires an explicit energy_plan and trajectory request. In an existing project with a completed binding-energy run, click 'Load recorded binding-energy inputs', or supply valid contracts in the inputs editor.");
        return;
      }

      for (const key of Object.keys(parsed.inputs || {})) {
        if (!(key in inputObj) || inputObj[key] == null) {
          throw new Error("Missing input: " + key + ". Upload or prepare the required input before queueing this workflow.");
        }
      }

      for (const [k, v] of Object.entries(inputObj)) {
        if (Array.isArray(v) && v.length === 0) {
          setErr(`Workflow input '${k}' cannot be an empty list. Register compounds.`);
          return;
        }
      }

      const id = ulid();
      const r = await get(
        api.POST("/v1/projects/{project_id}/runs/{run_id}/execute", {
          params: { path: { project_id: pid, run_id: id } },
          body: { workflow: parsed as never, inputs: inputObj },
        })
      );
      setRid(id);
      setRun(r as Snapshot);
      setMsg("✓ Pipeline queued! Monitoring execution progress...");
      setActiveTab("monitor"); // Auto-switch to monitor tab so user watches execution
      void refreshHistory(pid);
      void refreshDashboard(pid);
    } catch (x) {
      setErr(String(x));
    }
  }

  const poll = useCallback(async () => {
    if (!pid || !rid) return;
    try {
      const snapshot = (await get(api.GET("/v1/projects/{project_id}/runs/{run_id}/status", { params: { path: { project_id: pid, run_id: rid } } }))) as Snapshot;
      setRun(snapshot);
      setHistory((rows) => rows.map((row) => (row.run_id === rid ? { ...row, status: snapshot.status } : row)));
      if (snapshot.status === "awaiting_decision") {
        const d = await get(api.GET("/v1/projects/{project_id}/runs/{run_id}/decisions", { params: { path: { project_id: pid, run_id: rid } } }));
        setPending(d as PendingDecision[]);
      } else {
      setPending([]);
      }
      const statusKey = pid + ":" + rid + ":" + snapshot.status;
      if (lastRunStatus.current !== statusKey) {
        lastRunStatus.current = statusKey;
        await Promise.all([refreshDashboard(pid), refreshHistory(pid)]);
      }
    } catch (e) {
      setErr(String(e));
    }
  }, [api, pid, rid, refreshDashboard, refreshHistory]);

  useEffect(() => {
    if (!ok || !rid) return;
    void poll();
    const t = setInterval(() => void poll(), 2500);
    return () => clearInterval(t);
  }, [ok, rid, poll]);

  async function openHistoryRun(id: string) {
    try {
      const snapshot = (await get(api.GET("/v1/projects/{project_id}/runs/{run_id}/status", { params: { path: { project_id: pid, run_id: id } } }))) as Snapshot;
      setRid(id);
      setRun(snapshot);
      setLineData(null);
      setLogText("");
      setErr("");
      setActiveTab("monitor");
    } catch (e) {
      setErr(String(e));
    }
  }

  async function submitDecision(d: PendingDecision, key: string) {
    try {
      await get(
        api.POST("/v1/projects/{project_id}/runs/{run_id}/decisions", {
          params: { path: { project_id: pid, run_id: rid } },
          body: {
            issue_id: d.issue_id,
            chosen_key: key,
            decided_by: decidedBy.trim(),
            expected_version: d.task_version,
            scope: "task",
            rationale: rationale.trim() || null,
          },
        })
      );
      setPending((rows) => rows.filter((row) => row.issue_id !== d.issue_id));
      setMsg("Decision recorded; workflow requeued");
      setRationale("");
      void refreshHistory(pid);
      void refreshDashboard(pid);
    } catch (e) {
      setErr(String(e));
    }
  }

  async function cancel() {
    try {
      await get(api.POST("/v1/projects/{project_id}/runs/{run_id}/cancel", { params: { path: { project_id: pid, run_id: rid } } }));
      setMsg("Cancellation requested");
    } catch (e) {
      setErr(String(e));
    }
  }

  const deleteSingleRun = useCallback(
    async (runId: string, accession: string) => {
      if (!window.confirm(`Are you sure you want to permanently delete run ${accession}? This removes its task and provenance records. Shared artifact files stay in storage.`)) return;
      setIsDeletingRuns(true);
      try {
        const res = await fetch(`${url.replace(/\/$/, "")}/v1/projects/${encodeURIComponent(pid)}/runs/${encodeURIComponent(runId)}`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error((await res.text()) || "Failed to delete run");
        if (rid === runId) {
          setRid("");
          setRun(null);
          setLineData(null);
          setLogText("");
        }
        setSelectedRunIds((prev) => {
          const next = new Set(prev);
          next.delete(runId);
          return next;
        });
        setMsg(`Run ${accession} deleted.`);
        await refreshHistory(pid);
        await refreshDashboard(pid);
      } catch (err) {
        setErr(String(err));
      } finally {
        setIsDeletingRuns(false);
      }
    },
    [url, token, pid, rid, refreshHistory, refreshDashboard]
  );

  const deleteSelectedRuns = useCallback(async () => {
    if (selectedRunIds.size === 0) return;
    if (!window.confirm(`Are you sure you want to permanently delete the ${selectedRunIds.size} selected run(s)?`)) return;
    setIsDeletingRuns(true);
    try {
      const idsToDelete = Array.from(selectedRunIds);
      let count = 0;
      for (const runId of idsToDelete) {
        const res = await fetch(`${url.replace(/\/$/, "")}/v1/projects/${encodeURIComponent(pid)}/runs/${encodeURIComponent(runId)}`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          count++;
          if (rid === runId) {
            setRid("");
            setRun(null);
            setLineData(null);
            setLogText("");
          }
        }
      }
      setSelectedRunIds(new Set());
      setMsg(`Deleted ${count} run(s).`);
      await refreshHistory(pid);
      await refreshDashboard(pid);
    } catch (err) {
      setErr(String(err));
    } finally {
      setIsDeletingRuns(false);
    }
  }, [selectedRunIds, url, token, pid, rid, refreshHistory, refreshDashboard]);

  const toggleSelectRun = useCallback((runId: string) => {
    setSelectedRunIds((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) next.delete(runId);
      else next.add(runId);
      return next;
    });
  }, []);

  const selectAllRuns = useCallback(() => {
    setSelectedRunIds((prev) => {
      if (prev.size === history.length) return new Set();
      return new Set(history.map((r) => r.run_id));
    });
  }, [history]);

  const selectFailedRuns = useCallback(() => {
    const failedIds = history.filter((r) => r.status === "failed").map((r) => r.run_id);
    setSelectedRunIds(new Set(failedIds));
  }, [history]);

  function insertCompounds() {
    try {
      const x = JSON.parse(inputs);
      const key = Object.keys(x).find((k) => k.toLowerCase().includes("compound"));
      if (!key) throw Error("Workflow needs a compound input declaration");
      if (!compounds.length) throw Error("Register compounds first");
      x[key] = compounds.map((c) => c.payload);
      setInputs(JSON.stringify(x, null, 2));
      setMsg("Inserted compounds into " + key);
    } catch (e) {
      setErr(String(e));
    }
  }

  async function upload() {
    if (!file) return;
    try {
      const r = await uploadArtifact(url, token, pid, file, "input");
      const d = (await r.json()) as { artifact: { artifact_id: string; role: string; sha256: string } };
      setMsg("Uploaded to project CAS: " + file.name + " (" + d.artifact.artifact_id + ")");
      setFile(null);
      await refreshArtifacts(pid);
      await refreshDashboard(pid);
    } catch (e) {
      setErr(String(e));
    }
  }

  async function readLog(id: string) {
    try {
      const r = await fetch(url.replace(/\/$/, "") + "/v1/projects/" + pid + "/artifacts/" + id + "/text?tail_bytes=65536", {
        headers: { Authorization: "Bearer " + token },
      });
      if (!r.ok) throw Error(await r.text());
      setLogText(await r.text());
    } catch (e) {
      setErr(String(e));
    }
  }

  async function lineage() {
    try {
      const r = await fetch(url.replace(/\/$/, "") + "/v1/provenance/runs/" + rid, { headers: { Authorization: "Bearer " + token } });
      if (!r.ok) throw Error(await r.text());
      setLineData((await r.json()) as Lineage);
      setLogText("");
      setMsg("Run provenance loaded");
    } catch (e) {
      setErr(String(e));
    }
  }

  async function downloadArtifact(artifactId: string, originalName?: string | null, kind?: string, mediaType?: string) {
    try {
      setErr("");
      const r = await fetch(url.replace(/\/$/, "") + "/v1/projects/" + pid + "/artifacts/" + artifactId + "/content", {
        headers: { Authorization: "Bearer " + token },
      });
      if (!r.ok) throw Error(`Download failed (${r.status}): ${await r.text()}`);
      const blob = await r.blob();
      const blobUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = blobUrl;
      const ext = mediaType === "application/json" ? ".json" : mediaType === "text/csv" ? ".csv" : mediaType === "text/plain" ? ".txt" : "";
      link.download = originalName || `${kind || "artifact"}_${artifactId.slice(-6)}${ext}`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
      setMsg(`Downloaded artifact: ${link.download}`);
    } catch (e) {
      setErr(String(e));
    }
  }

  const currentStagesCount = useMemo(() => {
    try {
      const parsed = JSON.parse(wf);
      return Array.isArray(parsed.stages) ? parsed.stages.length : 0;
    } catch {
      return 0;
    }
  }, [wf]);

  return (
    <div className="shell">
      {/* GLOBAL HEADER */}
      <header>
        <div className="brand">
          <b className="mark">C</b>
          <span>
            CADD <strong>SUITE</strong>
            <small>COMPUTATIONAL DISCOVERY WORKSPACE</small>
          </span>
        </div>

        {/* PERSISTENT PROJECT SELECTOR IN HEADER */}
        <div className="head-project-bar">
          <label>
            Project
            <select
              disabled={!ok}
              value={pid}
              onChange={(e) => {
                setPid(e.target.value);
                setRid("");
                setRun(null);
                setLineData(null);
                setViewingArtifact(null);
              }}
            >
              <option value="">Select active project...</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.slug})
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="ghost-btn" onClick={() => setActiveTab("settings")}>
            Manage
          </button>
        </div>

        <div className="headright">
          <span className={ok ? "online" : ""}>API {ok ? "CONNECTED" : "OFFLINE"}</span>
          <button className="dark" onClick={() => void connect()}>
            {ok ? "Refresh" : "Connect"}
          </button>
        </div>
      </header>

      {/* FEEDBACK BANNERS */}
      {err && (
        <div role="alert" className="alert global-alert" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
          <span>{err}</span>
          {err.includes("caddsuite-local-2026") && (
            <button
              type="button"
              className="outline small"
              onClick={() => void connect("caddsuite-local-2026")}
            >
              Fill default token &amp; connect
            </button>
          )}
        </div>
      )}
      {msg && !msg.startsWith("{") && <div role="status" aria-live="polite" className="success global-alert">{msg}</div>}

      {(!ok || !pid || compounds.length === 0) && (
        <aside className="panel" aria-label="Getting started">
          <h2>Get started</h2>
          <ol>
            <li>{ok ? "Connected to the local API." : "Connect to the local API using your installation token."}
              {!ok && <button type="button" className="outline small" onClick={() => setActiveTab("settings")}>Open connection settings</button>}
            </li>
            <li>{pid ? "Project selected." : "Create or select a project in connection settings."}</li>
            <li>Add your compounds, then choose a workflow and provide its required inputs.
              {ok && pid && compounds.length === 0 && <button type="button" className="outline small" onClick={() => setActiveTab("compounds")}>Add compounds</button>}
            </li>
          </ol>
        </aside>
      )}
      {/* TAB NAVIGATION BAR */}
      <nav className="workspace-tabs" aria-label="Workspace sections">
        <button
          className={"workspace-tab-btn " + (activeTab === "pipeline" ? "active" : "")}
          onClick={() => setActiveTab("pipeline")}
        >
          <span className="tab-icon">🚀</span>
          <span>Pipeline Studio</span>
        </button>

        <button
          className={"workspace-tab-btn " + (activeTab === "evidence" ? "active" : "")}
          onClick={() => setActiveTab("evidence")}
        >
          <span className="tab-icon">📊</span>
          <span>Overview & Evidence</span>
          {dashboard?.scientific_results && dashboard.scientific_results.length > 0 ? (
            <span className="tab-count-badge">{dashboard.scientific_results.length}</span>
          ) : null}
        </button>

        <button
          className={"workspace-tab-btn " + (activeTab === "compounds" ? "active" : "")}
          onClick={() => setActiveTab("compounds")}
        >
          <span className="tab-icon">🧪</span>
          <span>Ligand Registry</span>
          <span className="tab-count-badge">{compounds.length}</span>
        </button>

        <button
          className={"workspace-tab-btn " + (activeTab === "monitor" ? "active" : "")}
          onClick={() => setActiveTab("monitor")}
        >
          <span className="tab-icon">📈</span>
          <span>Run Monitor</span>
          {run && <span className={"tab-dot-status " + run.status} />}
        </button>

        <button
          className={"workspace-tab-btn " + (activeTab === "structures" ? "active" : "")}
          onClick={() => setActiveTab("structures")}
        >
          <span className="tab-icon">🔬</span>
          <span>3D Molecular Studio</span>
          {structureArtifacts.length > 0 && <span className="tab-count-badge">{structureArtifacts.length}</span>}
        </button>

        <button
          className={"workspace-tab-btn " + (activeTab === "settings" ? "active" : "")}
          onClick={() => setActiveTab("settings")}
        >
          <span className="tab-icon">⚙️</span>
          <span>Projects & API</span>
        </button>
      </nav>

      {/* TAB CONTENT AREA */}
      <main className="tab-content-main">
        {/* ========================================================= */}
        {/* TAB 1: PIPELINE STUDIO */}
        {/* ========================================================= */}
        {activeTab === "pipeline" && (
          <section className="panel workflow-section">
            <div className="between">
              <div>
                <h2>04 / Computational pipeline</h2>
                <p className="panel-subtext">Choose a workflow, review its inputs and methods, then validate it before running.</p>
              </div>
              <span className="form-badge">PRESET DISCOVERY ENGINE</span>
            </div>

            {/* 1-CLICK PIPELINE PRESETS */}
            <div className="preset-grid">
              <div
                className={"preset-card" + (selectedPreset === "docking" ? " active" : "")}
                role="button"
                tabIndex={0}
                aria-pressed={selectedPreset === "docking"}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); applyPreset("docking"); } }}
                onClick={() => applyPreset("docking")}
              >
                <div className="preset-head">
                  <span className="preset-icon">🎯</span>
                  <span className="preset-tag recommended">RECOMMENDED • 8 STAGES</span>
                </div>
                <h3>ADMET + AutoDock Vina</h3>
                <p>End-to-end structure screening: ADMET filters, 3D conformers, receptor preparation (PDBFixer), whole-receptor blind search box, and Vina pose docking.</p>
                <div className="preset-meta">
                  <span>Receptor + Ligand</span>
                  <span className="preset-speed">Runtime depends on inputs and resources</span>
                </div>
              </div>

              <div
                className={"preset-card" + (selectedPreset === "admet" ? " active" : "")}
                role="button"
                tabIndex={0}
                aria-pressed={selectedPreset === "admet"}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); applyPreset("admet"); } }}
                onClick={() => applyPreset("admet")}
              >
                <div className="preset-head">
                  <span className="preset-icon">💊</span>
                  <span className="preset-tag fast">FAST • 2 STAGES</span>
                </div>
                <h3>ADMET Screening</h3>
                <p>Ligand-only property profiling: Lipinski Rule of 5, QED, physicochemical descriptors, and toxicophore structural alerts (RDKit).</p>
                <div className="preset-meta">
                  <span>Ligand only</span>
                  <span className="preset-speed">&lt; 3s runtime</span>
                </div>
              </div>

              <div
                className={"preset-card" + (selectedPreset === "ligand_3d" ? " active" : "")}
                role="button"
                tabIndex={0}
                aria-pressed={selectedPreset === "ligand_3d"}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); applyPreset("ligand_3d"); } }}
                onClick={() => applyPreset("ligand_3d")}
              >
                <div className="preset-head">
                  <span className="preset-icon">🧬</span>
                  <span className="preset-tag">3D CONFORMATION • 4 STAGES</span>
                </div>
                <h3>Ligand 3D & Protonation</h3>
                <p>Physiological protonation (Dimorphite-DL at pH 7.4) and distance-geometry 3D conformer embedding (ETKDG / MMFF94 force field).</p>
                <div className="preset-meta">
                  <span>Ligand only</span>
                  <span className="preset-speed">~5s runtime</span>
                </div>
              </div>

              <div
                className={"preset-card" + (selectedPreset === "dft" ? " active" : "")}
                role="button"
                tabIndex={0}
                aria-pressed={selectedPreset === "dft"}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); applyPreset("dft"); } }}
                onClick={() => applyPreset("dft")}
              >
                <div className="preset-head">
                  <span className="preset-icon">⚛️</span>
                  <span className="preset-tag qm">DFT / PSI4 • 5 STAGES</span>
                </div>
                <h3>Ligand DFT (Psi4)</h3>
                <p>Quantum-chemical profiling: B3LYP/6-31G* electronic energy, HOMO/LUMO frontier orbitals, dipole moments, and electrostatic potential (ESP).</p>
                <div className="preset-meta">
                  <span>Ligand only (Psi4)</span>
                  <span className="preset-speed">Runtime depends on molecule and method</span>
                </div>
              </div>

              <div
                className={"preset-card" + (selectedPreset === "md" ? " active" : "")}
                role="button"
                tabIndex={0}
                aria-pressed={selectedPreset === "md"}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); applyPreset("md"); } }}
                onClick={() => applyPreset("md")}
              >
                <div className="preset-head">
                  <span className="preset-icon">🌊</span>
                  <span className="preset-tag md">MD / GROMACS • CUDA ACCELERATED</span>
                </div>
                <h3>Protein-Ligand MD (GROMACS)</h3>
                <p>All-atom molecular dynamics with GROMACS: solvent box, counter-ions, energy minimization, NVT/NPT equilibration, and production run with GPU acceleration.</p>
                <div className="preset-meta">
                  <span>Receptor + Ligand (GPU)</span>
                  <span className="preset-speed">~2m - 1h runtime</span>
                </div>
              </div>

              <div
                className={"preset-card" + (selectedPreset === "mmpbsa" ? " active" : "")}
                role="button"
                tabIndex={0}
                aria-pressed={selectedPreset === "mmpbsa"}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); applyPreset("mmpbsa"); } }}
                onClick={() => applyPreset("mmpbsa")}
              >
                <div className="preset-head">
                  <span className="preset-icon">🧪</span>
                  <span className="preset-tag mmpbsa">FREE ENERGY • GMX_MMPBSA</span>
                </div>
                <h3>MM-PBSA Free Energy</h3>
                <p>Post-simulation continuum solvation free energy: MM-PBSA / MM-GBSA binding free energy (ΔG_bind) calculation and per-residue energy decomposition.</p>
                <div className="preset-meta">
                  <span>Trajectory + Topology</span>
                  <span className="preset-speed">~1m runtime</span>
                </div>
              </div>
            </div>

            {/* TARGET RECEPTOR SELECTOR (FOR DOCKING PIPELINE) */}
            {selectedPreset === "docking" && (
              <div className="target-selector-card">
                <div className="between">
                  <div>
                    <span className="subhead-label">RECEPTOR SPECIFICATION</span>
                    <h4>Target Protein Structure</h4>
                  </div>
                  {activeTargetArtifact && (
                    <span className={"format-badge " + (structureFormat(activeTargetArtifact) === "mmcif" ? "cif" : "pdb")}>
                      {structureFormat(activeTargetArtifact) === "mmcif" ? "mmCIF (Recommended for PDBFixer)" : "PDB format"}
                    </span>
                  )}
                </div>

                {structureArtifacts.length > 0 ? (
                  <div className="target-select-row">
                    <label className="target-input-label">
                      <span>Select Target Receptor in Project CAS</span>
                      <select
                        value={activeTargetArtifact?.id || ""}
                        onChange={(e) => {
                          setSelectedTargetId(e.target.value);
                          const art = structureArtifacts.find((a) => a.id === e.target.value);
                          if (art) applyPreset("docking", art);
                        }}
                      >
                        {structureArtifacts.map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.original_name || a.kind} ({structureFormat(a)?.toUpperCase()} • {formatBytes(a.size_bytes)})
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className="target-actions">
                      {activeTargetArtifact && (
                        <button
                          type="button"
                          className="outline"
                          onClick={() => {
                            setViewingArtifact(activeTargetArtifact);
                            setActiveTab("structures");
                          }}
                        >
                          Preview in Mol*
                        </button>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="target-empty-alert">
                    <p>⚠️ No macromolecular structure (.cif or .pdb) found in this project. Upload one below to run docking.</p>
                  </div>
                )}

                <div className="docking-options-row">
                  <label>
                    Protein Chain
                    <input
                      value={targetChain}
                      maxLength={4}
                      placeholder="A"
                      onChange={(e) => {
                        const val = e.target.value.toUpperCase();
                        setTargetChain(val);
                        applyPreset("docking", activeTargetArtifact, compounds, val, exhaustiveness);
                      }}
                    />
                  </label>
                  <label>
                    Docking Exhaustiveness
                    <select
                      value={exhaustiveness}
                      onChange={(e) => {
                        const val = Number(e.target.value);
                        setExhaustiveness(val);
                        applyPreset("docking", activeTargetArtifact, compounds, targetChain, val);
                      }}
                    >
                      <option value={8}>8 (Fast preview)</option>
                      <option value={16}>16 (Standard thorough)</option>
                      <option value={32}>32 (More sampling)</option>
                    </select>
                  </label>
                  <label style={{ maxWidth: 110 }}>
                    Receptor pH
                    <input
                      type="number"
                      step="0.1"
                      min={0}
                      max={14}
                      value={receptorPh}
                      onChange={(e) => {
                        const ph = Number(e.target.value);
                        setReceptorPh(ph);
                        applyPreset("docking", activeTargetArtifact, compounds, targetChain, exhaustiveness, ph, altlocPolicy);
                      }}
                    />
                  </label>
                  <label>
                    Altloc / Model Policy
                    <select
                      value={altlocPolicy}
                      onChange={(e) => {
                        const pol = e.target.value;
                        setAltlocPolicy(pol);
                        applyPreset("docking", activeTargetArtifact, compounds, targetChain, exhaustiveness, receptorPh, pol);
                      }}
                    >
                      <option value="highest_occupancy_single_model">Highest occupancy single model (Default)</option>
                      <option value="require_full_occupancy">Require full occupancy (Strict)</option>
                    </select>
                  </label>
                  <label className="upload-inline-label">
                    Upload Receptor File (.cif / .pdb)
                    <div className="upload-inline">
                      <input
                        type="file"
                        accept=".cif,.mmcif,.pdb"
                        onChange={(e) => setFile(e.target.files?.[0] || null)}
                      />
                      <button
                        type="button"
                        className="light"
                        disabled={!ok || !pid || !file}
                        onClick={() => void upload()}
                      >
                        Upload
                      </button>
                    </div>
                  </label>
                </div>
              </div>
            )}

            {/* QUANTUM CHEMISTRY / DFT SPECIFICATION CARD */}
            {selectedPreset === "dft" && (
              <div className="target-selector-card qm-config-card">
                <div className="between">
                  <div>
                    <span className="subhead-label">EXPLICIT QM CALCULATION PLAN</span>
                    <h4>Electronic Structure &amp; DFT Specification</h4>
                  </div>
                  <span className="format-badge cif">Psi4 QM Engine</span>
                </div>

                <p className="dim" style={{ marginBottom: 12 }}>
                  Configure explicit quantum chemistry parameters. All calculations are bound to verified compound microstates and emit authoritative dipole, HOMO/LUMO, and SCF energy contracts.
                </p>

                <div className="docking-options-row" style={{ flexWrap: "wrap", gap: 12 }}>
                  <label>
                    Target Compound
                    <select
                      value={qmCompoundId || (compounds[0]?.id ?? "")}
                      onChange={(e) => {
                        const targetId = e.target.value;
                        setQmCompoundId(targetId);
                        let nextConfId = qmConformerId;
                        let nextFormId = qmFormId;
                        const currentConf = preparedConformers.find((c) => c.conformer_id === qmConformerId);
                        if (currentConf && currentConf.compound_id && currentConf.compound_id !== targetId) {
                          const compat = preparedConformers.find((c) => c.compound_id === targetId);
                          if (compat) {
                            nextConfId = compat.conformer_id;
                            nextFormId = compat.form_id;
                            setQmConformerId(nextConfId);
                            setQmFormId(nextFormId);
                          } else {
                            nextConfId = "";
                            nextFormId = "";
                            setQmConformerId("");
                            setQmFormId("");
                          }
                        }
                        applyPreset("dft", activeTargetArtifact, compounds, targetChain, exhaustiveness, receptorPh, altlocPolicy, mdLengthNs, mdTimestepFs, mdTempK, qmMethod, qmBasis, qmProtocol, qmSolvation, qmCharge, qmMultiplicity, targetId, nextFormId, nextConfId);
                      }}
                    >
                      {compounds.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.accession}: {c.name || c.payload?.parent?.canonical_smiles || c.inchikey || c.id}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label>
                    DFT Functional / Method
                    <select
                      value={qmMethod}
                      onChange={(e) => {
                        const m = e.target.value;
                        setQmMethod(m);
                        applyPreset("dft", activeTargetArtifact, compounds, targetChain, exhaustiveness, receptorPh, altlocPolicy, mdLengthNs, mdTimestepFs, mdTempK, m, qmBasis, qmProtocol, qmSolvation, qmCharge, qmMultiplicity, qmCompoundId, qmFormId, qmConformerId);
                      }}
                    >
                      <option value="b3lyp">B3LYP (Hybrid GGA - Default)</option>
                      <option value="wb97x-d">ωB97X-D (Range-separated with dispersion)</option>
                      <option value="m06-2x">M06-2X (Meta-GGA for noncovalent)</option>
                      <option value="pbe0">PBE0 (Parameter-free hybrid)</option>
                      <option value="hf">Hartree-Fock (Ab initio baseline)</option>
                    </select>
                  </label>

                  <label>
                    Basis Set
                    <select
                      value={qmBasis}
                      onChange={(e) => {
                        const b = e.target.value;
                        setQmBasis(b);
                        applyPreset("dft", activeTargetArtifact, compounds, targetChain, exhaustiveness, receptorPh, altlocPolicy, mdLengthNs, mdTimestepFs, mdTempK, qmMethod, b, qmProtocol, qmSolvation, qmCharge, qmMultiplicity, qmCompoundId, qmFormId, qmConformerId);
                      }}
                    >
                      <option value="def2-svp">def2-SVP (Ahlrichs split-valence - fast)</option>
                      <option value="6-31g*">6-31G* (Pople polarized double-zeta)</option>
                      <option value="def2-tzvp">def2-TZVP (Triple-zeta quality)</option>
                      <option value="cc-pvdz">cc-pVDZ (Dunning correlation-consistent)</option>
                    </select>
                  </label>

                  <label>
                    Calculation Protocol
                    <select
                      value={qmProtocol}
                      onChange={(e) => {
                        const p = e.target.value;
                        setQmProtocol(p);
                        applyPreset("dft", activeTargetArtifact, compounds, targetChain, exhaustiveness, receptorPh, altlocPolicy, mdLengthNs, mdTimestepFs, mdTempK, qmMethod, qmBasis, p, qmSolvation, qmCharge, qmMultiplicity, qmCompoundId, qmFormId, qmConformerId);
                      }}
                    >
                      <option value="single_point">Single Point Energy</option>
                      <option value="optimization">Geometry Optimization</option>
                      <option value="frequency">Harmonic Vibrational Frequencies</option>
                      <option value="opt_freq">Optimization + Frequencies</option>
                      <option value="tddft">Time-Dependent DFT (TDDFT)</option>
                    </select>
                  </label>

                  <label>
                    Solvation Model
                    <select
                      value={qmSolvation}
                      onChange={(e) => {
                        const s = e.target.value as "gas" | "water";
                        setQmSolvation(s);
                        applyPreset("dft", activeTargetArtifact, compounds, targetChain, exhaustiveness, receptorPh, altlocPolicy, mdLengthNs, mdTimestepFs, mdTempK, qmMethod, qmBasis, qmProtocol, s, qmCharge, qmMultiplicity, qmCompoundId, qmFormId, qmConformerId);
                      }}
                    >
                      <option value="gas">Gas Phase (Explicit / Vacuum)</option>
                      <option value="water">DDX-PCM Aqueous Solvation (Water)</option>
                    </select>
                  </label>

                  <label style={{ maxWidth: 90 }}>
                    Net Charge
                    <input
                      type="number"
                      value={qmCharge}
                      onChange={(e) => {
                        const ch = Number(e.target.value);
                        setQmCharge(ch);
                        applyPreset("dft", activeTargetArtifact, compounds, targetChain, exhaustiveness, receptorPh, altlocPolicy, mdLengthNs, mdTimestepFs, mdTempK, qmMethod, qmBasis, qmProtocol, qmSolvation, ch, qmMultiplicity, qmCompoundId, qmFormId, qmConformerId);
                      }}
                    />
                  </label>

                  <label style={{ maxWidth: 100 }}>
                    Multiplicity
                    <input
                      type="number"
                      min={1}
                      value={qmMultiplicity}
                      onChange={(e) => {
                        const mult = Number(e.target.value);
                        setQmMultiplicity(mult);
                        applyPreset("dft", activeTargetArtifact, compounds, targetChain, exhaustiveness, receptorPh, altlocPolicy, mdLengthNs, mdTimestepFs, mdTempK, qmMethod, qmBasis, qmProtocol, qmSolvation, qmCharge, mult, qmCompoundId, qmFormId, qmConformerId);
                      }}
                    />
                  </label>

                  <label style={{ minWidth: 260 }}>
                    Target Form / Microstate ID (ULID)
                    <input
                      type="text"
                      value={qmFormId}
                      placeholder="Explicit form ULID"
                      onChange={(e) => {
                        const fid = e.target.value.trim();
                        setQmFormId(fid);
                        applyPreset("dft", activeTargetArtifact, compounds, targetChain, exhaustiveness, receptorPh, altlocPolicy, mdLengthNs, mdTimestepFs, mdTempK, qmMethod, qmBasis, qmProtocol, qmSolvation, qmCharge, qmMultiplicity, qmCompoundId, fid, qmConformerId);
                      }}
                    />
                  </label>

                  <label style={{ minWidth: 260 }}>
                    Select Prepared Conformer Entity
                    <select
                      aria-label="Select Prepared 3D Conformer / Structure"
                      value={qmConformerId}
                      onChange={(e) => {
                        const cid = e.target.value.trim();
                        setQmConformerId(cid);
                        const conf = preparedConformers.find((c) => c.conformer_id === cid);
                        let nextFormId = qmFormId;
                        let nextCompId = qmCompoundId;
                        if (conf) {
                          nextFormId = conf.form_id;
                          setQmFormId(conf.form_id);
                          if (conf.compound_id) {
                            nextCompId = conf.compound_id;
                            setQmCompoundId(conf.compound_id);
                          }
                        }
                        applyPreset(
                          "dft",
                          activeTargetArtifact,
                          compounds,
                          targetChain,
                          exhaustiveness,
                          receptorPh,
                          altlocPolicy,
                          mdLengthNs,
                          mdTimestepFs,
                          mdTempK,
                          qmMethod,
                          qmBasis,
                          qmProtocol,
                          qmSolvation,
                          qmCharge,
                          qmMultiplicity,
                          nextCompId,
                          nextFormId,
                          cid
                        );
                      }}
                    >
                      <option value="">
                        {compatibleConformers.length === 0
                          ? "-- No prepared conformer entities available (enter ULIDs below) --"
                          : "-- Choose prepared conformer entity or enter below --"}
                      </option>
                      {compatibleConformers.map((c) => (
                        <option key={c.conformer_id} value={c.conformer_id}>
                          {c.label}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label style={{ minWidth: 260 }}>
                    Target Conformer / Geometry ID (ULID)
                    <input
                      type="text"
                      value={qmConformerId}
                      placeholder="Explicit conformer ULID"
                      onChange={(e) => {
                        const cid = e.target.value.trim();
                        setQmConformerId(cid);
                        applyPreset("dft", activeTargetArtifact, compounds, targetChain, exhaustiveness, receptorPh, altlocPolicy, mdLengthNs, mdTimestepFs, mdTempK, qmMethod, qmBasis, qmProtocol, qmSolvation, qmCharge, qmMultiplicity, qmCompoundId, qmFormId, cid);
                      }}
                    />
                  </label>

                  {(!qmFormId || !qmConformerId) && (
                    <div style={{ width: "100%", marginTop: 8, padding: "8px 12px", background: "rgba(237, 137, 54, 0.15)", border: "1px solid rgba(237, 137, 54, 0.4)", borderRadius: 6, color: "#fbd38d", fontSize: "0.85rem" }}>
                      ⚠️ <strong>Prepared Structure Identity Required:</strong> Quantum chemistry requires an explicit target form and conformer identity linked to a prepared 3D structure. Select an available conformer entity from prepared structures above, or provide explicit ULIDs before submission.
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* MOLECULAR DYNAMICS SIMULATION CONTROLS */}
            {selectedPreset === "md" && (
              <div className="target-selector-card md-config-card">
                <div className="between">
                  <div>
                    <span className="subhead-label">SIMULATION PROTOCOL</span>
                    <h4>Prepared MD system and protocol</h4>
                  </div>
                  <span className="format-badge cif">Engine and resources configured in workflow</span>
                </div>

                {/* 1-CLICK DEMO CAS PROVISIONING BANNER */}
                {!mdDemoInfo ? (
                  <div className="demo-md-cta-box">
                    <div className="between">
                      <div style={{ flex: 1, marginRight: 16 }}>
                        <h4>Use a recorded prepared system</h4>
                        <p>Reuse verified system inputs from a successful run in this project, or provide a prepared system and explicit stage plan in the advanced inputs below.</p>
                        {mdCandidates.length > 1 && (
                          <div style={{ marginTop: 8 }}>
                            <label htmlFor="md-candidate-selector" style={{ fontSize: "0.85rem", fontWeight: 600, display: "block", marginBottom: 4 }}>
                              Select recorded MD run to reuse:
                            </label>
                            <select
                              id="md-candidate-selector"
                              aria-label="Select recorded MD run"
                              value={selectedMdRunId}
                              onChange={(e) => setSelectedMdRunId(e.target.value)}
                              style={{ padding: "6px 10px", borderRadius: 4, width: "100%", maxWidth: 480, fontSize: "0.85rem" }}
                            >
                              {mdCandidates.map((c) => (
                                <option key={c.run_id} value={c.run_id}>
                                  {c.label}
                                </option>
                              ))}
                            </select>
                          </div>
                        )}
                        {mdCandidates.length === 0 && (
                          <p className="dim" style={{ fontSize: "0.85rem", marginTop: 6, color: "#e2a03f" }}>
                            ⚠️ No completed MD runs recorded in this project yet. Provide a prepared system and explicit stage plan in the inputs below.
                          </p>
                        )}
                      </div>
                      <button
                        type="button"
                        className="dark provision-button"
                        disabled={isProvisioningMd || !pid || mdCandidates.length === 0}
                        onClick={() => void loadDemoMdSystem()}
                      >
                        {isProvisioningMd ? "⏳ Provisioning CAS Artifacts..." : "📥 Load recorded MD inputs"}
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="demo-md-loaded-box">
                    <div className="between">
                      <div style={{ flex: 1, marginRight: 16 }}>
                        <span className="badge-tag green">HASH-VERIFIED PREPARED INPUTS</span>
                        <h4>Recorded system ({String(mdDemoInfo.atoms)} atoms)</h4>
                        <p className="dim">Original topology, coordinate, and parameter artifacts are verified by hash. The saved protocol determines the run settings.</p>
                        {mdCandidates.length > 1 && (
                          <div style={{ marginTop: 8 }}>
                            <label htmlFor="md-candidate-selector-loaded" style={{ fontSize: "0.85rem", fontWeight: 600, display: "block", marginBottom: 4 }}>
                              Switch to different recorded MD run:
                            </label>
                            <select
                              id="md-candidate-selector-loaded"
                              aria-label="Switch recorded MD run"
                              value={selectedMdRunId}
                              onChange={(e) => {
                                const newRunId = e.target.value;
                                setSelectedMdRunId(newRunId);
                                void loadDemoMdSystem(newRunId);
                              }}
                              style={{ padding: "6px 10px", borderRadius: 4, width: "100%", maxWidth: 480, fontSize: "0.85rem" }}
                            >
                              {mdCandidates.map((c) => (
                                <option key={c.run_id} value={c.run_id}>
                                  {c.label}
                                </option>
                              ))}
                            </select>
                          </div>
                        )}
                      </div>
                      <button
                        type="button"
                        className="outline small"
                        disabled={isProvisioningMd || !pid}
                        onClick={() => void loadDemoMdSystem()}
                        title="Re-sync MDP parameters and CAS artifact references"
                      >
                        {isProvisioningMd ? "⏳ Syncing..." : "🔄 Re-sync Parameters"}
                      </button>
                    </div>
                  </div>
                )}

                <p className="dashboard-note">Simulation settings are read from the prepared protocol and parameter files. A change in duration, timestep, or temperature requires new validated parameter artifacts.</p>
                {mdDemoInfo && (
                  <dl>
                    <dt>Duration</dt><dd>{String(mdDemoInfo.length_ns ?? "Unavailable")} ns</dd>
                    <dt>Timestep</dt><dd>{String(mdDemoInfo.timestep_fs ?? "Unavailable")} fs</dd>
                    <dt>Temperature</dt><dd>{String(mdDemoInfo.temperature_K ?? "Unavailable")} K</dd>
                  </dl>
                )}
              </div>
            )}

            {selectedPreset === "mmpbsa" && (
              <section className="target-selector-card" aria-label="Binding energy inputs">
                <h3>Binding-energy analysis inputs</h3>
                <p>Use a validated trajectory request and an explicit MM/PBSA or MM/GBSA plan. The method, sampled frames, temperature, and uncertainty settings come from that plan.</p>
                {mmpbsaCandidates.length > 1 && (
                  <div style={{ marginTop: 8, marginBottom: 8 }}>
                    <label htmlFor="mmpbsa-candidate-selector" style={{ fontSize: "0.85rem", fontWeight: 600, display: "block", marginBottom: 4 }}>
                      Select recorded MM-PBSA run to reuse:
                    </label>
                    <select
                      id="mmpbsa-candidate-selector"
                      aria-label="Select recorded MM-PBSA run"
                      value={selectedMmpbsaRunId}
                      onChange={(e) => {
                        const newRunId = e.target.value;
                        setSelectedMmpbsaRunId(newRunId);
                        if (mmpbsaDemoInfo) {
                          void loadDemoMmpbsaSystem(newRunId);
                        }
                      }}
                      style={{ padding: "6px 10px", borderRadius: 4, width: "100%", maxWidth: 480, fontSize: "0.85rem" }}
                    >
                      {mmpbsaCandidates.map((c) => (
                        <option key={c.run_id} value={c.run_id}>
                          {c.label}
                        </option>
                      ))}
                    </select>
                  </div>
                )}
                {mmpbsaCandidates.length === 0 && (
                  <p className="dim" style={{ fontSize: "0.85rem", marginBottom: 8, color: "#e2a03f" }}>
                    ⚠️ No completed MM-PBSA runs recorded in this project yet. Provide a validated request and plan in the inputs below.
                  </p>
                )}
                <button type="button" className="outline"
                  disabled={!pid || isProvisioningMmpbsa || mmpbsaCandidates.length === 0}
                  onClick={() => void loadDemoMmpbsaSystem()}>
                  {isProvisioningMmpbsa ? "Loading…" : "Load recorded binding-energy inputs"}
                </button>
                {mmpbsaDemoInfo && <p role="status">Recorded input identity retained.</p>}
                <p className="dim">If this is your first analysis, supply the validated request and plan using the workflow input editor. Approximate endpoint energies require interpretation alongside sampling and method limitations.</p>
              </section>
            )}

            {/* READINESS AND LAUNCH BAR */}
            <div className="readiness-banner">
              <div className="readiness-items">
                <div className={"readiness-pill " + (compounds.length > 0 ? "ready" : "warn")}>
                  <span className="dot-indicator" />
                  <span>
                    Ligands: <strong>{compounds.length > 0 ? `${compounds.length} ready` : "0 ready"}</strong>
                  </span>
                  {compounds.length === 0 && (
                    <button type="button" className="link-inline" onClick={() => setActiveTab("compounds")}>
                      + Add
                    </button>
                  )}
                </div>
                {selectedPreset === "docking" && (
                  <div className={"readiness-pill " + (activeTargetArtifact ? "ready" : "warn")}>
                    <span className="dot-indicator" />
                    <span>
                      Target: <strong>{activeTargetArtifact ? (activeTargetArtifact.original_name || activeTargetArtifact.id.slice(0, 10)) : "Receptor missing"}</strong>
                    </span>
                  </div>
                )}
                {selectedPreset === "md" && (
                  <div className={"readiness-pill " + (hasSystemBuild ? "ready" : "warn")}>
                    <span className="dot-indicator" />
                    <span>
                      Prepared system: <strong>{hasSystemBuild ? "Recorded inputs loaded" : "Provide system_build"}</strong>
                    </span>
                  </div>
                )}
                {selectedPreset === "mmpbsa" && (
                  <div className={"readiness-pill " + (hasEnergyPlan ? "ready" : "warn")}>
                    <span className="dot-indicator" />
                    <span>
                      Energy plan: <strong>{hasEnergyPlan ? "Recorded inputs loaded" : "Provide energy_plan"}</strong>
                    </span>
                  </div>
                )}
                <div className="readiness-pill info">
                  <span className="dot-indicator" />
                  <span>
                    Pipeline: <strong>{currentStagesCount} stage{currentStagesCount === 1 ? "" : "s"}</strong>
                  </span>
                </div>
              </div>

              <div className="pipeline-actions">
                <button type="button" className="outline" disabled={!ok} onClick={() => void planWorkflow()}>
                  Validate & Plan
                </button>
                <button
                  type="button"
                  className="dark run-button"
                  disabled={
                    !ok ||
                    !pid ||
                    compounds.length === 0 ||
                    (selectedPreset === "docking" && !activeTargetArtifact) ||
                    (selectedPreset === "md" && !hasSystemBuild) ||
                    (selectedPreset === "mmpbsa" && !hasEnergyPlan)
                  }
                  title={
                    selectedPreset === "md" && !hasSystemBuild
                      ? "Molecular Dynamics requires a prepared, solvated system (system_build). Load recorded MD inputs or supply an explicit system_build contract."
                      : selectedPreset === "mmpbsa" && !hasEnergyPlan
                      ? "MM-PBSA requires an explicit energy plan and trajectory request. Load recorded binding-energy inputs or supply explicit contracts."
                      : undefined
                  }
                  onClick={() => void submit()}
                >
                  🚀 Queue Pipeline
                </button>
              </div>
            </div>

            {/* COMPILED DAG ROADMAP */}
            {plan !== null && (
              <div className="plan-summary-card">
                <div className="between">
                  <div>
                    <span className="plan-badge">COMPILED EXECUTION DAG</span>
                    <strong>{String((plan as Record<string, unknown>).name || "Workflow Pipeline")}</strong>
                  </div>
                  <button type="button" className="close-plan-btn" onClick={() => setPlan(null)}>
                    ✕
                  </button>
                </div>
                <div className="plan-timeline">
                  {(((plan as Record<string, unknown>).task_order as string[]) || []).map((stageId: string, idx: number, arr: string[]) => {
                    const tasks = ((plan as Record<string, unknown>).tasks as Array<Record<string, unknown>>) || [];
                    const t = tasks.find((x) => x.stage_id === stageId);
                    return (
                      <div key={stageId} className="plan-stage-node">
                        <span className="node-idx">{idx + 1}</span>
                        <div className="node-body">
                          <b>{stageId}</b>
                          <small>{String(t?.kind || "")}{t?.engine ? ` • ${String(t.engine)}` : ""}</small>
                        </div>
                        {idx < arr.length - 1 && <span className="node-arrow">→</span>}
                      </div>
                    );
                  })}
                </div>
                <details className="advanced-workflow">
                  <summary>View raw compiler plan JSON</summary>
                  <pre className="result">{JSON.stringify(plan, null, 2)}</pre>
                </details>
              </div>
            )}

            {/* ADVANCED CUSTOM BUILDER (COLLAPSIBLE) */}
            <details className="advanced-builder">
              <summary>🛠️ Advanced: Custom Stage Builder & Installed Engine Discovery ({caps.length} capabilities)</summary>
              <div className="chips">
                {caps.map((c, i) => (
                  <span key={i}>
                    {String(c.kind || c.stage_kind || "stage")} / {String(c.engine || "generic")}
                  </span>
                ))}
              </div>
              <WorkflowBuilder
                capabilities={caps}
                onChange={(json) => {
                  setWf(json);
                  setSelectedPreset("custom");
                }}
              />
            </details>

            {/* ADVANCED WORKFLOW JSON (COLLAPSIBLE) */}
            <details className="advanced-workflow">
              <summary>📝 Advanced: Raw Workflow JSON (caddsuite.workflow/1)</summary>
              <textarea
                className="editor"
                value={wf}
                onChange={(e) => {
                  setWf(e.target.value);
                  setSelectedPreset("custom");
                }}
                spellCheck={false}
              />
            </details>
          </section>
        )}

        {/* ========================================================= */}
        {/* TAB 2: OVERVIEW & EVIDENCE */}
        {/* ========================================================= */}
        {activeTab === "evidence" && (
          <div className="tab-vertical-stack">
            <section className="panel dashboard">
              <div className="between">
                <div>
                  <h2>Project dashboard</h2>
                  <p>{dashboard ? dashboard.project.name + " / " + dashboard.project.slug : "Select a project to load its overview."}</p>
                </div>
                {dashboard && <span className="form-badge">PROJECT-SCOPED SUMMARY</span>}
              </div>
              {dashboard && (
                <>
                  <div className="dashboard-metrics">
                    {[
                      ["Compounds", dashboard.counts.compounds],
                      ["Workflow runs", dashboard.counts.workflow_runs],
                      ["Recent tasks", dashboard.counts.tasks_in_recent_runs],
                      ["Artifacts", dashboard.counts.artifacts],
                      ["Artifact storage", formatBytes(dashboard.counts.artifact_bytes)],
                    ].map(([lbl, val]) => (
                      <article className="metric" key={String(lbl)}>
                        <small>{lbl}</small>
                        <b>{val}</b>
                      </article>
                    ))}
                  </div>
                  <div className="dashboard-note">
                    <b>Target</b>
                    <span>{dashboard.target ? "Linked target" : "Not assigned"}</span>
                    <small>{dashboard.target_note}</small>
                  </div>
                  <div className="dashboard-columns">
                    <section>
                      <h3>Workflow status</h3>
                      {Object.keys(dashboard.workflow_statuses).length ? (
                        Object.entries(dashboard.workflow_statuses).map(([state, count]) => (
                          <div className="dashboard-row" key={state}>
                            <span className={"history-status " + state}>{state}</span>
                            <b>{count}</b>
                          </div>
                        ))
                      ) : (
                        <p className="empty">No workflow runs recorded.</p>
                      )}
                    </section>
                    <section>
                      <h3>Recent workflow activity</h3>
                      {dashboard.recent_runs.length ? (
                        dashboard.recent_runs.map((item) => (
                          <article className="dashboard-run" key={item.run_id}>
                            <div>
                              <b>{item.accession}</b>
                              <span className={"history-status " + item.status}>{item.status}</span>
                            </div>
                            <small>{item.created_at.slice(0, 16).replace("T", " ")}</small>
                            {item.tasks.length ? (
                              <div className="dashboard-stages">
                                {item.tasks.map((task, i) => (
                                  <span key={task.stage_id + "-" + i}>
                                    {task.stage_id} / {task.state}
                                  </span>
                                ))}
                              </div>
                            ) : (
                              <small>No task records</small>
                            )}
                          </article>
                        ))
                      ) : (
                        <p className="empty">No workflow runs recorded.</p>
                      )}
                    </section>
                    <section>
                      <h3>Artifact categories</h3>
                      {Object.keys(dashboard.artifact_kinds).length ? (
                        Object.entries(dashboard.artifact_kinds)
                          .sort(([a], [b]) => a.localeCompare(b))
                          .map(([kind, data]) => (
                            <div className="dashboard-row" key={kind}>
                              <span>
                                {kind}
                                <small>{formatBytes(data.size_bytes)}</small>
                              </span>
                              <b>{data.count}</b>
                            </div>
                          ))
                      ) : (
                        <p className="empty">No artifacts recorded.</p>
                      )}
                    </section>
                  </div>
                </>
              )}
            </section>

            <section className="panel">
              <div className="between">
                <h2>Scientific evidence & results</h2>
                <small>Normalized contract values and units; no combined candidate score</small>
              </div>
              {dashboard?.scientific_results.length ? (
                dashboard.scientific_results.map((item) => (
                  <article className="evidence-card" key={item.task_id + "-" + item.result_id}>
                    <div className="between">
                      <div>
                        <b>{item.category.replaceAll("_", " ")}</b>
                        <span>
                          {item.identity} / {item.stage_id}
                        </span>
                      </div>
                      <span className={"history-status " + item.task_state}>{item.task_state}</span>
                    </div>
                    <small>
                      {item.method} - {item.schema_version} - {item.subject_id || "No subject ID"}
                    </small>
                    <ScientificEvidenceView values={item.values} />
                    {item.warnings.length > 0 && (
                      <ul className="evidence-warnings">
                        {item.warnings.map((warning, j) => (
                          <li key={j}>{warning}</li>
                        ))}
                      </ul>
                    )}
                  </article>
                ))
              ) : (
                <p className="empty">No normalized scientific result contracts are cached for this project yet. Run a pipeline in the Pipeline Studio to generate results.</p>
              )}
            </section>
          </div>
        )}

        {/* ========================================================= */}
        {/* TAB 3: LIGAND REGISTRY */}
        {/* ========================================================= */}
        {activeTab === "compounds" && (
          <div className="tab-two-column">
            <section className="panel">
              <h2>Register new chemical entity</h2>
              <p>SMILES are standardized into parent identities with RDKit; submissions remain linked for provenance.</p>
              <form onSubmit={(e) => void addCompound(e)}>
                <label>
                  Compound name / identifier
                  <input required value={cname} onChange={(e) => setCname(e.target.value)} placeholder="e.g. Aspirin, CMP-01" />
                </label>
                <label>
                  SMILES string
                  <input required value={smi} onChange={(e) => setSmi(e.target.value)} placeholder="e.g. CCO or CC(=O)Oc1ccccc1C(=O)O" />
                </label>
                <button className="light" disabled={!ok || !pid}>
                  Standardize & register compound
                </button>
              </form>
            </section>

            <section className="panel">
              <div className="between">
                <h2>Registered compound library <span className="pill">{compounds.length}</span></h2>
                {compounds.length > 0 && (
                  <button className="link" onClick={() => setActiveTab("pipeline")}>
                    Run pipeline on compounds →
                  </button>
                )}
              </div>
              <div className="list">
                {compounds.map((c) => (
                  <div className="compound" key={c.id}>
                    <b>{c.accession}</b>
                    <span>
                      <strong>{c.name}</strong>
                      <small>SMILES: {c.payload.parent?.canonical_smiles || "N/A"}</small>
                      <small>InChIKey: {c.inchikey}</small>
                    </span>
                  </div>
                ))}
                {!compounds.length && <p className="empty">No registered compounds yet. Use the form on the left to add one.</p>}
              </div>
            </section>
          </div>
        )}

        {/* ========================================================= */}
        {/* TAB 4: RUN MONITOR & PROVENANCE */}
        {/* ========================================================= */}
        {activeTab === "monitor" && (
          <div className="tab-two-column">
            {/* LEFT: RECENT RUNS */}
            <section className="panel">
              <div className="between">
                <h2>
                  Recent project runs <span className="pill">{history.length}</span>
                </h2>
                {history.length > 0 && selectedRunIds.size > 0 && (
                  <button
                    type="button"
                    className="danger-btn-compact"
                    disabled={isDeletingRuns}
                    onClick={() => void deleteSelectedRuns()}
                  >
                    🗑️ Delete ({selectedRunIds.size})
                  </button>
                )}
              </div>

              {history.length > 0 ? (
                <>
                  <div className="run-list-controls">
                    <label className="select-all-label">
                      <input
                        type="checkbox"
                        checked={history.length > 0 && selectedRunIds.size === history.length}
                        onChange={selectAllRuns}
                      />
                      <span>Select all</span>
                    </label>
                    <div className="run-quick-filters">
                      {history.some((r) => r.status === "failed") && (
                        <button type="button" className="filter-pill" onClick={selectFailedRuns}>
                          Select failed ({history.filter((r) => r.status === "failed").length})
                        </button>
                      )}
                      {selectedRunIds.size > 0 && (
                        <button type="button" className="filter-pill text-only" onClick={() => setSelectedRunIds(new Set())}>
                          Clear
                        </button>
                      )}
                    </div>
                  </div>

                  <div className="history">
                    {history.map((item) => {
                      const isChecked = selectedRunIds.has(item.run_id);
                      const isCurrent = item.run_id === rid;
                      return (
                        <div
                          className={"history-item-row " + (isCurrent ? "selected " : "") + (isChecked ? "checked" : "")}
                          key={item.run_id}
                          onClick={() => void openHistoryRun(item.run_id)}
                        >
                          <input
                            type="checkbox"
                            className="run-checkbox"
                            checked={isChecked}
                            onClick={(e) => e.stopPropagation()}
                            onChange={() => toggleSelectRun(item.run_id)}
                          />
                          <div className="history-item-body">
                            <span>
                              <b>{item.accession}</b>
                              <small>{item.created_at.slice(0, 16).replace("T", " ")}</small>
                            </span>
                            <em className={"history-status " + item.status}>{item.status}</em>
                          </div>
                          <button
                            type="button"
                            className="delete-run-icon"
                            title={`Delete run ${item.accession}`}
                            disabled={isDeletingRuns}
                            onClick={(e) => {
                              e.stopPropagation();
                              void deleteSingleRun(item.run_id, item.accession);
                            }}
                          >
                            ✕
                          </button>
                        </div>
                      );
                    })}
                  </div>
                </>
              ) : (
                <p className="empty">No previous runs recorded.</p>
              )}
            </section>

            {/* RIGHT: RUN DETAIL & PROVENANCE */}
            <section className="panel">
              <div className="between">
                <h2>Execution progress</h2>
                {run && <span className={"pill " + run.status}>{run.status}</span>}
              </div>

              {!run && <p className="empty">Select a run from the history on the left or launch a new pipeline in Pipeline Studio.</p>}

              {run && (
                <>
                  <div className="runmeta">
                    <span>
                      RUN ID <code>{rid}</code>
                    </span>
                    <div className="runmeta-actions">
                      <button
                        className="outline"
                        onClick={() => void cancel()}
                        disabled={["succeeded", "failed", "stopped", "cancelled"].includes(run.status)}
                      >
                        Cancel run
                      </button>
                      <button
                        className="danger-btn-compact"
                        disabled={isDeletingRuns}
                        onClick={() => {
                          const item = history.find((h) => h.run_id === rid);
                          void deleteSingleRun(rid, item?.accession || rid);
                        }}
                      >
                        🗑️ Delete run
                      </button>
                    </div>
                  </div>

                  <div className="task-list">
                    {(run.tasks || []).map((t) => (
                      <div className="task" key={t.task_id}>
                        <i className={"dot " + t.state} />
                        <b>{t.stage_id}</b>
                        <span>{t.state}</span>
                        <code>{t.task_id.slice(0, 10)}</code>
                      </div>
                    ))}
                  </div>

                  {pending.map((d) => (
                    <article className="decision-card" key={d.issue_id}>
                      <span className="form-badge">
                        {d.request.issue_code} / {d.stage_id}
                      </span>
                      <h3>{d.request.question}</h3>
                      {d.subject_id && <code>{d.subject_id}</code>}
                      <label>
                        Decision recorded by
                        <input value={decidedBy} onChange={(e) => setDecidedBy(e.target.value)} placeholder="Your name or identifier" />
                      </label>
                      <label>
                        Rationale (optional)
                        <textarea value={rationale} onChange={(e) => setRationale(e.target.value)} />
                      </label>
                      <div className="decision-options">
                        {d.request.options.map((option) => (
                          <button
                            className="light"
                            key={option.key}
                            disabled={!decidedBy.trim()}
                            onClick={() => void submitDecision(d, option.key)}
                          >
                            <b>{option.label}</b>
                            <span>{option.consequence}</span>
                          </button>
                        ))}
                      </div>
                    </article>
                  ))}

                  {run.submission?.error && <div className="alert">{run.submission.error}</div>}

                  <div className="end">
                    <button className="link" onClick={() => void lineage()}>
                      Inspect run provenance artifacts
                    </button>
                  </div>

                  {lineData && (
                    <div className="lineage">
                      <h3>Run artifacts ({lineData.artifacts?.length || 0})</h3>
                      {(lineData.artifacts || []).map((a) => (
                        <div className="artifact" key={a.id}>
                          <span>
                            {a.kind + " / " + a.media_type + " / " + formatBytes(a.size_bytes)}
                          </span>
                          <code>{a.id}</code>
                          <button
                            className="link"
                            onClick={() => void downloadArtifact(a.id, a.original_name, a.kind, a.media_type)}
                          >
                            Download
                          </button>
                          {a.media_type === "text/plain" && (
                            <button className="link" onClick={() => void readLog(a.id)}>
                              Read log tail
                            </button>
                          )}
                          {structureFormat(a) && (
                            <button
                              className="link"
                              onClick={() => {
                                setViewingArtifact(a);
                                setActiveTab("structures");
                              }}
                            >
                              View in Mol*
                            </button>
                          )}
                        </div>
                      ))}
                      {logText && <pre className="logtext">{logText}</pre>}
                    </div>
                  )}
                </>
              )}
            </section>
          </div>
        )}

        {/* ========================================================= */}
        {/* TAB 5: 3D MOLECULAR STUDIO */}
        {/* ========================================================= */}
        {activeTab === "structures" && (
          <div className="tab-vertical-stack">
            <section className="panel">
              <div className="between">
                <h2>3D Molecular structures & trajectories</h2>
                <div className="upload">
                  <input type="file" onChange={(e) => setFile(e.target.files?.[0] || null)} />
                  <button className="light" disabled={!ok || !pid || !file} onClick={() => void upload()}>
                    Upload structure file
                  </button>
                </div>
              </div>

              {viewingArtifact && (
                <div className="viewer-active-box">
                  <div className="between">
                    <b>Currently inspecting: {viewingArtifact.original_name || viewingArtifact.kind}</b>
                    <button className="outline" onClick={() => setViewingArtifact(null)}>
                      Close 3D viewer
                    </button>
                  </div>
                  <Suspense fallback={<p className="viewer-status">Loading Mol* 3D viewer...</p>}>
                    <MolecularViewer
                      key={viewingArtifact.id}
                      apiUrl={url}
                      token={token}
                      projectId={pid}
                      artifactId={viewingArtifact.id}
                      label={viewingArtifact.original_name || viewingArtifact.kind}
                      format={structureFormat(viewingArtifact)!}
                      sizeBytes={viewingArtifact.size_bytes}
                      onClose={() => setViewingArtifact(null)}
                    />
                  </Suspense>
                </div>
              )}

              {projectArtifacts.some((a) => structureFormat(a) !== null) && (
                <div className="structure-list">
                  <h3>Available structures in project CAS</h3>
                  {projectArtifacts
                    .filter((a) => structureFormat(a) !== null)
                    .map((a) => (
                      <div className="artifact" key={a.id}>
                        <span>
                          {a.original_name || a.kind} / {a.media_type} / {formatBytes(a.size_bytes)}
                        </span>
                        <button className="link" onClick={() => setViewingArtifact(a)}>
                          View in Mol*
                        </button>
                        <button
                          className="link"
                          onClick={() => void downloadArtifact(a.id, a.original_name, a.kind, a.media_type)}
                        >
                          Download
                        </button>
                      </div>
                    ))}
                </div>
              )}

              {projectArtifacts.some(cubeFile) && (
                <div className="structure-list">
                  <h3>Volumetric data / molecular orbitals</h3>
                  {projectArtifacts.filter(cubeFile).map((a) => (
                    <div className="artifact" key={a.id}>
                      <span>
                        {a.original_name || a.kind} / {formatBytes(a.size_bytes)}
                      </span>
                      <button className="link" onClick={() => setVolumeArtifact(a)}>
                        View cube
                      </button>
                    </div>
                  ))}
                  {volumeArtifact && (
                    <Suspense fallback={<p className="viewer-status">Loading Mol* viewer...</p>}>
                      <VolumeViewer
                        key={volumeArtifact.id}
                        apiUrl={url}
                        token={token}
                        projectId={pid}
                        artifactId={volumeArtifact.id}
                        name={volumeArtifact.original_name || volumeArtifact.kind}
                        sizeBytes={volumeArtifact.size_bytes}
                        onClose={() => setVolumeArtifact(null)}
                      />
                    </Suspense>
                  )}
                </div>
              )}

              {projectArtifacts.some((a) => topologyFormat(a)) && projectArtifacts.some((a) => coordinatesFormat(a)) && (
                <div className="structure-list">
                  <div className="between">
                    <div>
                      <h3>Trajectory 3D Preview (Mol*)</h3>
                      <p>View multi-frame simulation coordinate playback.</p>
                    </div>
                  </div>
                  <p className="dim" style={{ fontSize: "11px", margin: "2px 0 10px" }}>
                    💡 <strong>Tip:</strong> Select topology and coordinates from the same system. File size and filenames do not establish scientific compatibility.
                  </p>
                  <label>
                    Topology
                    <select value={topologyId} onChange={(e) => setTopologyId(e.target.value)}>
                      <option value="">Choose topology</option>
                      {projectArtifacts
                        .filter((a) => topologyFormat(a))
                        .sort((a, b) => b.size_bytes - a.size_bytes)
                        .map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.original_name || a.kind} ({formatBytes(a.size_bytes)})
                          </option>
                        ))}
                    </select>
                  </label>
                  <label>
                    Coordinates
                    <select
                      value={trajectoryId}
                      onChange={(e) => setTrajectoryId(e.target.value)}
                    >
                      <option value="">Choose trajectory</option>
                      {projectArtifacts
                        .filter((a) => coordinatesFormat(a))
                        .map((a) => (
                          <option key={a.id} value={a.id}>
                            {a.original_name || a.kind} / {formatBytes(a.size_bytes)}
                          </option>
                        ))}
                    </select>
                  </label>
                  {topologyId &&
                    trajectoryId &&
                    (() => {
                      const t = projectArtifacts.find((a) => a.id === topologyId)!;
                      const c = projectArtifacts.find((a) => a.id === trajectoryId)!;
                      return (
                        <Suspense fallback={<p className="viewer-status">Loading Mol* viewer...</p>}>
                          <TrajectoryViewer
                            key={topologyId + trajectoryId}
                            apiUrl={url}
                            token={token}
                            projectId={pid}
                            topologyId={t.id}
                            topologyName={t.original_name || t.kind}
                            topologyFormat={topologyFormat(t)!}
                            topologySize={t.size_bytes}
                            trajectoryId={c.id}
                            trajectoryName={c.original_name || c.kind}
                            trajectoryFormat={coordinatesFormat(c)!}
                            trajectorySize={c.size_bytes}
                            onClose={() => {
                              setTopologyId("");
                              setTrajectoryId("");
                            }}
                          />
                        </Suspense>
                      );
                    })()}
                </div>
              )}

              {/* TRAJECTORY ANALYTICS DASHBOARD */}
              {projectArtifacts.some((a) => coordinatesFormat(a)) && (
                <div className="structure-list" style={{ marginTop: "16px" }}>
                  <div className="between">
                    <div>
                      <h3>Trajectory Analytics (RMSD, RMSF, SASA, Rg, H-Bond)</h3>
                      <p>Select an exact topology and trajectory pair to view measurements recorded by a completed analysis workflow.</p>
                    </div>
                    <button
                      type="button"
                      className="dark"
                      disabled={analyzingTrajectory || !pid || !topologyId || !trajectoryId}
                      onClick={() => void runTrajectoryAnalysis()}
                    >
                      {analyzingTrajectory ? "⏳ Loading recorded metrics..." : "📊 Load recorded analysis"}
                    </button>
                  </div>
                  {trajectoryAnalytics && (
                    <TrajectoryPlots
                      data={trajectoryAnalytics}
                      apiUrl={url}
                      token={token}
                      projectId={pid}
                    />
                  )}
                </div>
              )}

              <details className="advanced-workflow">
                <summary>📝 Advanced: Raw Input Contracts JSON</summary>
                <div className="between">
                  <span />
                  <button className="link" disabled={!compounds.length} onClick={insertCompounds}>
                    Re-insert registered compounds
                  </button>
                </div>
                <textarea
                  aria-label="Workflow inputs JSON"
                  className="editor inputs"
                  value={inputs}
                  onChange={(e) => setInputs(e.target.value)}
                  spellCheck={false}
                />
              </details>
            </section>
          </div>
        )}

        {/* ========================================================= */}
        {/* TAB 6: SETTINGS & API CONNECTION */}
        {/* ========================================================= */}
        {activeTab === "settings" && (
          <div className="tab-two-column">
            <section className="panel">
              <h2>API connection settings</h2>
              <div className="row">
                <label>
                  API base URL
                  <input value={url} onChange={(e) => setUrl(e.target.value)} />
                </label>
                <label>
                  Access token
                  <input
                    type="password"
                    value={token}
                    onChange={(e) => {
                      const val = e.target.value;
                      setToken(val);
                      try {
                        if (val) localStorage.setItem("caddsuite_api_token", val);
                        else localStorage.removeItem("caddsuite_api_token");
                      } catch {
                        // ignore
                      }
                    }}
                    placeholder="Local API bearer token (default: caddsuite-local-2026)"
                  />
                </label>
              </div>
              <div className="between" style={{ marginTop: 8, flexWrap: "wrap", gap: 8 }}>
                <small className="dim">
                  Local development default: <code>caddsuite-local-2026</code> (configured via <code>CADDSUITE_API_TOKEN</code>)
                </small>
                <button
                  type="button"
                  className="outline small"
                  onClick={() => void connect("caddsuite-local-2026")}
                >
                  Fill default token &amp; connect
                </button>
              </div>
              <div className="actions" style={{ marginTop: 14 }}>
                <button className="dark" onClick={() => void connect()}>
                  {ok ? "Re-verify connection" : "Connect to API"}
                </button>
              </div>
            </section>

            <section className="panel">
              <h2>Project management</h2>
              {project && (
                <div className="project-manage">
                  <div>
                    <strong>{project.name}</strong>
                    <code className="id">{project.id}</code>
                  </div>
                  <button type="button" className="danger-link" onClick={() => void deleteProject(project.id, project.name)}>
                    Delete project
                  </button>
                </div>
              )}
              <form onSubmit={(e) => void createProject(e)}>
                <h3>Create new project</h3>
                <input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Project name (e.g. Kinase Screening)" />
                <input required pattern="[a-z0-9][a-z0-9-]{0,62}" value={slug} onChange={(e) => setSlug(e.target.value)} placeholder="slug (e.g. kinase-screen)" />
                <button className="light" disabled={!ok}>
                  Create project
                </button>
              </form>
            </section>
            <section className="panel" style={{ gridColumn: "1 / -1" }}>
              <div className="between">
                <div>
                  <h2>Scientific Engine Configuration & Readiness</h2>
                  <p>
                    Inspect discovered scientific toolchain paths and configure local executables.
                    Auto-discovered paths adapt to your environment; overrides are saved locally.
                  </p>
                </div>
                <div style={{ display: "flex", gap: "8px" }}>
                  <button
                    type="button"
                    className="light"
                    onClick={() => resetEnginePaths()}
                  >
                    Reset to auto-discovered
                  </button>
                  <button
                    type="button"
                    className="dark"
                    onClick={() => saveEnginePaths(enginePaths)}
                  >
                    Save & Apply paths
                  </button>
                </div>
              </div>

              {/* Readiness Badges */}
              <div style={{ display: "flex", gap: "12px", margin: "16px 0", flexWrap: "wrap" }}>
                <div style={{ padding: "8px 12px", borderRadius: "6px", background: engineConfig?.readiness?.docking_ready ? "var(--c-ready-bg, #e6f4ea)" : "var(--c-missing-bg, #fef7e0)", border: "1px solid var(--c-border, #ddd)" }}>
                  <span style={{ fontWeight: 600 }}>Docking (Vina / Meeko): </span>
                  <span style={{ color: engineConfig?.readiness?.docking_ready ? "#137333" : "#b06000" }}>
                    {engineConfig?.readiness?.docking_ready ? "✓ Ready" : "⚠ Prerequisites missing"}
                  </span>
                </div>
                <div style={{ padding: "8px 12px", borderRadius: "6px", background: engineConfig?.readiness?.gromacs_ready ? "var(--c-ready-bg, #e6f4ea)" : "var(--c-missing-bg, #fef7e0)", border: "1px solid var(--c-border, #ddd)" }}>
                  <span style={{ fontWeight: 600 }}>Molecular Dynamics (GROMACS): </span>
                  <span style={{ color: engineConfig?.readiness?.gromacs_ready ? "#137333" : "#b06000" }}>
                    {engineConfig?.readiness?.gromacs_ready ? "✓ Ready" : "⚠ Prerequisites missing"}
                  </span>
                </div>
                <div style={{ padding: "8px 12px", borderRadius: "6px", background: engineConfig?.readiness?.psi4_ready ? "var(--c-ready-bg, #e6f4ea)" : "var(--c-missing-bg, #fef7e0)", border: "1px solid var(--c-border, #ddd)" }}>
                  <span style={{ fontWeight: 600 }}>Quantum Chemistry (Psi4): </span>
                  <span style={{ color: engineConfig?.readiness?.psi4_ready ? "#137333" : "#b06000" }}>
                    {engineConfig?.readiness?.psi4_ready ? "✓ Ready" : "⚠ Prerequisites missing"}
                  </span>
                </div>
                <div style={{ padding: "8px 12px", borderRadius: "6px", background: engineConfig?.readiness?.mmpbsa_ready ? "var(--c-ready-bg, #e6f4ea)" : "var(--c-missing-bg, #fef7e0)", border: "1px solid var(--c-border, #ddd)" }}>
                  <span style={{ fontWeight: 600 }}>MM-PBSA (gmx_MMPBSA): </span>
                  <span style={{ color: engineConfig?.readiness?.mmpbsa_ready ? "#137333" : "#b06000" }}>
                    {engineConfig?.readiness?.mmpbsa_ready ? "✓ Ready" : "⚠ Prerequisites missing"}
                  </span>
                </div>
              </div>

              {/* Missing Prerequisites Warning */}
              {engineConfig && engineConfig.missing_prerequisites && engineConfig.missing_prerequisites.length > 0 && (
                <div className="alert" style={{ marginBottom: "16px" }}>
                  <strong>Missing system prerequisites:</strong>
                  <ul style={{ margin: "6px 0 0 16px", padding: 0 }}>
                    {engineConfig.missing_prerequisites.map((req, i) => (
                      <li key={i}>{req}</li>
                    ))}
                  </ul>
                  <p style={{ margin: "6px 0 0", fontSize: "12px" }}>
                    Set the corresponding environment variable (e.g. <code>CADDSUITE_GROMACS_BIN</code>, <code>CADDSUITE_VINA_BIN</code>, <code>CADDSUITE_PSI4_PYTHON</code>) or configure paths below.
                  </p>
                </div>
              )}

              {/* Editable Path Grid */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: "12px" }}>
                <label>
                  <span>AutoDock Vina executable</span>
                  <input
                    value={enginePaths.vina_executable || ""}
                    onChange={(e) => setEnginePaths((p) => ({ ...p, vina_executable: e.target.value }))}
                    placeholder="vina or /path/to/vina"
                  />
                </label>
                <label>
                  <span>CADD Python (Meeko / PDBFixer)</span>
                  <input
                    value={enginePaths.cadd_python || ""}
                    onChange={(e) => setEnginePaths((p) => ({ ...p, cadd_python: e.target.value }))}
                    placeholder="python or /path/to/cadd/bin/python"
                  />
                </label>
                <label>
                  <span>PDBFixer worker script</span>
                  <input
                    value={enginePaths.pdbfixer_worker || ""}
                    onChange={(e) => setEnginePaths((p) => ({ ...p, pdbfixer_worker: e.target.value }))}
                    placeholder="/path/to/pdbfixer_worker.py"
                  />
                </label>
                <label>
                  <span>GROMACS executable (gmx)</span>
                  <input
                    value={enginePaths.gmx_executable || ""}
                    onChange={(e) => setEnginePaths((p) => ({ ...p, gmx_executable: e.target.value }))}
                    placeholder="gmx or /path/to/gmx"
                  />
                </label>
                <label>
                  <span>Psi4 Python interpreter</span>
                  <input
                    value={enginePaths.psi4_python || ""}
                    onChange={(e) => setEnginePaths((p) => ({ ...p, psi4_python: e.target.value }))}
                    placeholder="python or /path/to/psi4/bin/python"
                  />
                </label>
                <label>
                  <span>CADD Suite worker source directory</span>
                  <input
                    value={enginePaths.worker_source_dir || ""}
                    onChange={(e) => setEnginePaths((p) => ({ ...p, worker_source_dir: e.target.value }))}
                    placeholder="/path/to/src"
                  />
                </label>
                <label>
                  <span>gmx_MMPBSA executable</span>
                  <input
                    value={enginePaths.gmx_mmpbsa_executable || ""}
                    onChange={(e) => setEnginePaths((p) => ({ ...p, gmx_mmpbsa_executable: e.target.value }))}
                    placeholder="gmx_MMPBSA or /path/to/gmx_MMPBSA"
                  />
                </label>
                <label>
                  <span>gmx_MMPBSA Python interpreter</span>
                  <input
                    value={enginePaths.gmx_mmpbsa_python || ""}
                    onChange={(e) => setEnginePaths((p) => ({ ...p, gmx_mmpbsa_python: e.target.value }))}
                    placeholder="python or /path/to/gmxMMPBSA/bin/python"
                  />
                </label>
                <label>
                  <span>gmx_MMPBSA worker script</span>
                  <input
                    value={enginePaths.gmx_mmpbsa_worker || ""}
                    onChange={(e) => setEnginePaths((p) => ({ ...p, gmx_mmpbsa_worker: e.target.value }))}
                    placeholder="/path/to/gmx_mmpbsa_worker.py"
                  />
                </label>
                <label>
                  <span>AmberTools bin directory</span>
                  <input
                    value={enginePaths.ambertools_bin || ""}
                    onChange={(e) => setEnginePaths((p) => ({ ...p, ambertools_bin: e.target.value }))}
                    placeholder="/path/to/ambertools/bin"
                  />
                </label>
              </div>
            </section>
          </div>
        )}
      </main>

      <footer>
        <b>CADD SUITE / COMPUTATIONAL RESULTS ARE PREDICTIONS</b>
        <span>Scientific predictions require suitable validation and experimental follow-up.</span>
      </footer>
    </div>
  );
}
