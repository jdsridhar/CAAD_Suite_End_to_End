#!/usr/bin/env python3
"""GROMACS Built-in Solution Builder Pipeline.

Automates the canonical GROMACS preparation pipeline:
    1. gmx pdb2gmx  - Generate coordinates, topology, and position restraints from PDB
    2. gmx editconf - Define simulation box dimensions and center the solute
    3. gmx solvate  - Solvate the simulation box with explicit water
    4. gmx grompp   - Assemble run input parameter file for ion placement
    5. gmx genion   - Neutralize net charge and add physiological ions (e.g., 0.15 M NaCl)
    6. gmx make_ndx - Generate standard index groups for temperature coupling

Supports both apo-protein structures and protein-ligand complexes (by merging
parameterized ligand .gro and .itp files into the system topology).
"""

from __future__ import annotations

import argparse
import importlib
import logging
import math
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("gromacs_solution_builder")


def validate_production_settings(*, length_ns: float, timestep_fs: float, temp_k: float) -> int:
    """Validate the conventional-mass local builder and return its exact step count.

    Larger timesteps require a separately prepared and qualified HMR/virtual-site
    system; this builder does not create either of those topologies.
    """
    if not math.isfinite(timestep_fs) or not 0.1 <= timestep_fs <= 2.0:
        raise ValueError(
            "Local solution builder requires a timestep between 0.1 and 2 fs. "
            "A 4 fs timestep requires separately prepared and validated hydrogen mass "
            "repartitioning or virtual sites; this builder provides neither."
        )
    if not math.isfinite(length_ns) or length_ns <= 0:
        raise ValueError("MD duration must be finite and positive.")
    if not math.isfinite(temp_k) or temp_k <= 0:
        raise ValueError("MD temperature must be finite and positive.")
    steps = round(length_ns * 1_000_000 / timestep_fs)
    if steps < 1:
        raise ValueError("MD duration must include at least one integration step.")
    return steps


@dataclass(frozen=True)
class SolutionBuilderConfig:
    """Configuration parameters for the GROMACS solution builder pipeline."""

    forcefield: str = "amber14sb"
    water_model: str = "tip3p"
    box_type: str = "dodecahedron"  # dodecahedron, cubic, triclinic
    box_padding_nm: float = 1.0  # Minimum distance between solute and box edge (nm)
    ion_concentration_m: float = 0.15  # Salt concentration in mol/L
    neutralize: bool = True
    positive_ion: str = "NA"  # "NA" for Amber/CHARMM, "SOD" for some OPLS
    negative_ion: str = "CL"  # "CL" for Amber/CHARMM, "CLA" for some OPLS
    ignore_hydrogens: bool = True  # Pass -ignh to pdb2gmx
    repair_missing_atoms: bool = True  # Auto-repair missing sidechain heavy atoms with PDBFixer
    run_energy_minimization: bool = True  # Run gentle energy minimization to relax steric clashes
    solvent_model_gro: str = "spc216.gro"  # Template solvent box in GROMACS library
    extra_pdb2gmx_args: tuple[str, ...] = ()


@dataclass
class SolutionSystemSummary:
    """Summary of built MD system properties."""

    total_atoms: int = 0
    solute_atoms: int = 0
    water_molecules: int = 0
    positive_ions: int = 0
    negative_ions: int = 0
    net_charge_estimate: int = 0
    box_vectors_nm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    box_volume_nm3: float = 0.0
    output_files: dict[str, str] = field(default_factory=dict)


class GromacsExecutionError(RuntimeError):
    """Raised when a GROMACS command fails."""

    def __init__(self, cmd: Sequence[str], returncode: int, stdout: str, stderr: str):
        self.cmd = list(cmd)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        msg = (
            f"GROMACS command '{' '.join(cmd)}' failed with exit code {returncode}.\n"
            f"--- STDERR ---\n{stderr.strip()}\n"
            f"--- STDOUT ---\n{stdout.strip()}"
        )
        super().__init__(msg)


def find_gmx_binary(explicit_path: str | Path | None = None) -> Path:
    """Locate the gmx or gmx_mpi executable on the system."""
    if explicit_path:
        p = Path(explicit_path).expanduser().resolve()
        if p.is_file() and os.access(p, os.X_OK):
            return p
        msg = f"Specified GROMACS binary not found or not executable: {explicit_path}"
        raise FileNotFoundError(msg)

    env_gmx = os.environ.get("GMX_BIN") or os.environ.get("GMXBIN")
    if env_gmx:
        p = Path(env_gmx).expanduser().resolve()
        if p.is_file() and os.access(p, os.X_OK):
            return p

    for name in ("gmx", "gmx_mpi", "gmx_d", "gmx_mpi_d"):
        found = shutil.which(name)
        if found:
            return Path(found).resolve()

    # Search common conda and local installation paths
    candidates = [
        Path.home() / "miniconda3" / "envs" / "gmx" / "bin" / "gmx",
        Path.home() / "anaconda3" / "envs" / "gmx" / "bin" / "gmx",
        Path("/usr/local/gromacs/bin/gmx"),
        Path("/usr/bin/gmx"),
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return c.resolve()

    raise FileNotFoundError(
        "Could not find GROMACS executable ('gmx'). Ensure GROMACS is installed and in PATH, "
        "or pass --gmx / set GMX_BIN environment variable."
    )


def find_python_with_pdbfixer() -> Path | None:
    """Find a Python interpreter that has pdbfixer and openmm installed."""
    try:
        importlib.import_module("pdbfixer")

        return Path(sys.executable).resolve()
    except ImportError:
        pass

    try:
        from caddsuite.application.engine_discovery import discover_engine_paths

        discovered = discover_engine_paths().paths
        if discovered.cadd_python:
            p = Path(discovered.cadd_python).expanduser().resolve()
            if p.is_file() and os.access(p, os.X_OK):
                return p
    except Exception as exc:
        logger.debug("Failed discovering cadd_python via engine_discovery: %s", exc)

    candidates = [
        Path.home() / "miniconda3" / "envs" / "cadd" / "bin" / "python",
        Path.home() / "anaconda3" / "envs" / "cadd" / "bin" / "python",
        Path("/opt/conda/envs/cadd/bin/python"),
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return c.resolve()

    return None


def repair_missing_heavy_atoms(
    input_pdb: Path,
    output_pdb: Path,
    python_bin: Path | None = None,
) -> bool:
    """Detect and complete missing sidechain heavy atoms using PDBFixer.

    Returns True if repaired or verified complete, False if skipped.
    """
    python_exec = python_bin or find_python_with_pdbfixer()
    if not python_exec:
        logger.info("PDBFixer Python environment not found; skipping sidechain repair.")
        shutil.copyfile(input_pdb, output_pdb)
        return False

    repair_code = (
        "import sys\n"
        "from pdbfixer import PDBFixer\n"
        "from openmm.app import PDBFile\n"
        "fixer = PDBFixer(filename=sys.argv[1])\n"
        "fixer.findMissingResidues()\n"
        "fixer.findMissingAtoms()\n"
        "if fixer.missingAtoms or fixer.missingTerminals:\n"
        "    fixer.addMissingAtoms()\n"
        "with open(sys.argv[2], 'w') as f:\n"
        "    PDBFile.writeFile(fixer.topology, fixer.positions, f, keepIds=True)\n"
    )

    try:
        res = subprocess.run(  # noqa: S603
            [
                str(python_exec),
                "-c",
                repair_code,
                str(input_pdb.resolve()),
                str(output_pdb.resolve()),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        if res.returncode == 0 and output_pdb.is_file() and output_pdb.stat().st_size > 0:
            logger.info("Repaired missing sidechain atoms with PDBFixer -> %s", output_pdb)
            return True
        logger.warning(
            "PDBFixer repair failed (returncode %d): %s. Proceeding with raw structure.",
            res.returncode,
            res.stderr.strip()[:500],
        )
    except Exception as exc:
        logger.warning("Error running PDBFixer repair: %s. Proceeding with raw structure.", exc)

    shutil.copyfile(input_pdb, output_pdb)
    return False


def sanitize_gro_coordinates(gro_path: Path) -> int:
    """Sanitize any NaN, Inf, or invalid coordinate entries in a .gro file.

    Returns the count of sanitized atom entries.
    """
    if not gro_path.is_file():
        return 0
    raw_text = gro_path.read_text(encoding="utf-8", errors="replace")
    lines = raw_text.splitlines()
    if len(lines) < 3:
        return 0
    title = lines[0]
    try:
        natoms = int(lines[1].strip())
    except ValueError:
        return 0

    box_line = lines[-1]
    atom_lines = lines[2 : 2 + natoms]
    if len(atom_lines) != natoms:
        atom_lines = lines[2:-1]

    sanitized_count = 0
    repaired_lines: list[str] = []
    last_x, last_y, last_z = 0.0, 0.0, 0.0

    for line in atom_lines:
        line_lower = line.lower()
        if "nan" in line_lower or "inf" in line_lower or len(line) < 44:
            res_prefix = line[:20].ljust(20) if len(line) >= 20 else line.ljust(20)
            coord_str = line[20:44] if len(line) >= 44 else line[20:]
            vel_str = line[44:] if len(line) > 44 else ""

            tokens = coord_str.split()
            coords: list[float] = []
            for t in tokens:
                try:
                    val = float(t)
                    if math.isnan(val) or math.isinf(val):
                        coords.append(float("nan"))
                    else:
                        coords.append(val)
                except ValueError:
                    coords.append(float("nan"))

            x = coords[0] if len(coords) > 0 and not math.isnan(coords[0]) else last_x
            y = coords[1] if len(coords) > 1 and not math.isnan(coords[1]) else last_y
            z = coords[2] if len(coords) > 2 and not math.isnan(coords[2]) else last_z

            fixed_line = f"{res_prefix}{x:8.3f}{y:8.3f}{z:8.3f}{vel_str}"
            repaired_lines.append(fixed_line)
            sanitized_count += 1
            last_x, last_y, last_z = x, y, z
        else:
            try:
                last_x = float(line[20:28])
                last_y = float(line[28:36])
                last_z = float(line[36:44])
            except ValueError:
                pass
            repaired_lines.append(line)

    if sanitized_count > 0:
        new_content = "\n".join([title, str(natoms), *repaired_lines, box_line]) + "\n"
        gro_path.write_text(new_content, encoding="utf-8")
        logger.warning(
            "Sanitized %d invalid/NaN coordinate entries in %s",
            sanitized_count,
            gro_path,
        )
    return sanitized_count


class GromacsSolutionBuilder:
    """Executes the standard GROMACS built-in solution preparation workflow."""

    def __init__(
        self,
        gmx_bin: str | Path | None = None,
        config: SolutionBuilderConfig | None = None,
    ):
        self.gmx = find_gmx_binary(gmx_bin)
        self.config = config or SolutionBuilderConfig()
        logger.info("Using GROMACS binary: %s", self.gmx)

    def _run_cmd(
        self,
        subcommand: str,
        args: Sequence[str],
        cwd: Path,
        stdin_input: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Execute a GROMACS tool with robust logging and error handling."""
        cmd = [str(self.gmx), subcommand, *list(args)]
        logger.debug("Executing: %s (in %s)", " ".join(cmd), cwd)

        proc = subprocess.run(  # noqa: S603
            cmd,
            cwd=str(cwd),
            input=stdin_input,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise GromacsExecutionError(cmd, proc.returncode, proc.stdout, proc.stderr)
        return proc

    def step1_pdb2gmx(
        self,
        input_pdb: Path,
        output_gro: Path,
        output_top: Path,
        posre_itp: Path,
        work_dir: Path,
    ) -> None:
        """Step 1: Convert PDB to GROMACS coordinates (.gro) and topology (.top)."""
        logger.info("[Step 1/6] Running gmx pdb2gmx...")
        # Pre-filter to protein ATOM records, stripping non-standard HETATM/UNK
        # and crystallographic waters
        cleaned_pdb = work_dir / "00_protein_cleaned.pdb"
        with (
            input_pdb.open("r", encoding="utf-8", errors="replace") as fin,
            cleaned_pdb.open("w", encoding="utf-8") as fout,
        ):
            prev_chain: str | None = None
            prev_resnum: int | None = None
            for line in fin:
                if line.startswith("ATOM"):
                    resname = line[17:20].strip().upper() if len(line) >= 20 else ""
                    if resname in ("HOH", "WAT", "TIP3", "SOL"):
                        continue
                    chain = line[21] if len(line) > 21 else " "
                    try:
                        resnum = int(line[22:26])
                    except ValueError:
                        resnum = None
                    if (
                        prev_chain is not None
                        and prev_resnum is not None
                        and (
                            chain != prev_chain or (resnum is not None and resnum > prev_resnum + 1)
                        )
                    ):
                        fout.write("TER\n")
                    prev_chain = chain
                    prev_resnum = resnum
                    fout.write(line)
                elif line.startswith(("TER", "ENDMDL", "END")):
                    fout.write(line)
                    prev_chain = None
                    prev_resnum = None

        pdb_for_pdb2gmx = cleaned_pdb
        if self.config.repair_missing_atoms:
            repaired_pdb = work_dir / "00_protein_repaired.pdb"
            if repair_missing_heavy_atoms(cleaned_pdb, repaired_pdb):
                pdb_for_pdb2gmx = repaired_pdb

        args = [
            "-f",
            str(pdb_for_pdb2gmx.resolve()),
            "-o",
            str(output_gro.resolve()),
            "-p",
            str(output_top.resolve()),
            "-i",
            str(posre_itp.resolve()),
            "-ff",
            self.config.forcefield,
            "-water",
            self.config.water_model,
            "-missing",
        ]
        if self.config.ignore_hydrogens:
            args.append("-ignh")
        args.extend(self.config.extra_pdb2gmx_args)

        self._run_cmd("pdb2gmx", args, cwd=work_dir)

        # Sanitize coordinate formatting in case of any remaining -nan or overflows
        sanitize_gro_coordinates(output_gro)

    def step2_editconf(
        self,
        input_gro: Path,
        output_gro: Path,
        work_dir: Path,
    ) -> None:
        """Step 2: Center solute and define periodic simulation box dimensions."""
        logger.info(
            "[Step 2/6] Running gmx editconf (box: %s, padding: %.2f nm)...",
            self.config.box_type,
            self.config.box_padding_nm,
        )
        args = [
            "-f",
            str(input_gro.resolve()),
            "-o",
            str(output_gro.resolve()),
            "-c",
            "-d",
            f"{self.config.box_padding_nm:.3f}",
            "-bt",
            self.config.box_type,
        ]
        self._run_cmd("editconf", args, cwd=work_dir)

    def step3_solvate(
        self,
        input_gro: Path,
        output_gro: Path,
        top_file: Path,
        work_dir: Path,
    ) -> None:
        """Step 3: Solvate the box with explicit water and update topology."""
        logger.info(
            "[Step 3/6] Running gmx solvate with solvent model %s...",
            self.config.solvent_model_gro,
        )
        args = [
            "-cp",
            str(input_gro.resolve()),
            "-cs",
            self.config.solvent_model_gro,
            "-o",
            str(output_gro.resolve()),
            "-p",
            str(top_file.resolve()),
        ]
        self._run_cmd("solvate", args, cwd=work_dir)

    @staticmethod
    def write_ions_mdp(target_path: Path) -> None:
        """Create a minimal energy minimization MDP parameter file required by grompp for genion."""
        content = """\
; ions.mdp - parameter file for grompp prior to genion
integrator              = steep
emtol                   = 1000.0
emstep                  = 0.01
nsteps                  = 50000

; Neighbor searching and electrostatics
nstlist                 = 1
cutoff-scheme           = Verlet
ns_type                 = grid
coulombtype             = PME
rcoulomb                = 1.0
rvdw                    = 1.0
pbc                     = xyz
"""
        target_path.write_text(content, encoding="utf-8")

    @staticmethod
    def write_em_mdp(target_path: Path) -> None:
        """Create an energy minimization MDP parameter file to relax steric clashes."""
        content = """\
; em.mdp - energy minimization parameter file
integrator              = steep
emtol                   = 1000.0
emstep                  = 0.01
nsteps                  = 500

; Neighbor searching and nonbonded
nstlist                 = 20
cutoff-scheme           = Verlet
coulombtype             = PME
rcoulomb                = 1.0
rvdw                    = 1.0
pbc                     = xyz
"""
        target_path.write_text(content, encoding="utf-8")

    @staticmethod
    def write_production_mdp(
        target_path: Path,
        *,
        length_ns: float = 1.0,
        timestep_fs: float = 2.0,
        temp_k: float = 300.0,
    ) -> None:
        """Create a standard NPT production molecular dynamics parameter file."""
        n_steps = validate_production_settings(
            length_ns=length_ns, timestep_fs=timestep_fs, temp_k=temp_k
        )
        dt_ps = timestep_fs / 1000.0
        nst_out = max(100, min(5000, n_steps // 100 if n_steps >= 1000 else 100))
        nst_calc_energy = math.gcd(100, nst_out)

        content = f"""; production.mdp - standard NPT production molecular dynamics
integrator              = md
dt                      = {dt_ps:.8g}
nsteps                  = {n_steps}

; Output control
nstcalcenergy           = {nst_calc_energy}
nstxout-compressed      = {nst_out}
nstenergy               = {nst_out}
nstlog                  = {nst_out}

; Bond constraints
continuation            = no
constraint_algorithm    = lincs
constraints             = h-bonds
lincs_iter              = 1
lincs_order             = 4

; Nonbonded interactions
cutoff-scheme           = Verlet
nstlist                 = 20
rcoulomb                = 1.0
rvdw                    = 1.0

; Electrostatics
coulombtype             = PME
pme_order               = 4
fourierspacing          = 0.16

; Temperature coupling
tcoupl                  = V-rescale
tc-grps                 = System
tau_t                   = 0.1
ref_t                   = {temp_k:.2f}

; Pressure coupling
pcoupl                  = C-rescale
pcoupltype              = isotropic
tau_p                   = 2.0
ref_p                   = 1.0
compressibility         = 4.5e-5

; Periodic boundary conditions & dispersion correction
pbc                     = xyz
DispCorr                = EnerPres

; Velocity generation
gen_vel                 = yes
gen_temp                = {temp_k:.2f}
gen_seed                = -1
"""
        target_path.write_text(content, encoding="utf-8")

    def step4_grompp_for_ions(
        self,
        solvated_gro: Path,
        top_file: Path,
        ions_mdp: Path,
        output_tpr: Path,
        work_dir: Path,
    ) -> None:
        """Step 4: Run grompp to compile atomic parameters for genion."""
        logger.info("[Step 4/6] Running gmx grompp to compile ions.tpr...")
        args = [
            "-f",
            str(ions_mdp.resolve()),
            "-c",
            str(solvated_gro.resolve()),
            "-p",
            str(top_file.resolve()),
            "-o",
            str(output_tpr.resolve()),
            "-maxwarn",
            "2",
        ]
        self._run_cmd("grompp", args, cwd=work_dir)

    def step5_genion(
        self,
        ions_tpr: Path,
        top_file: Path,
        output_gro: Path,
        work_dir: Path,
    ) -> None:
        """Step 5: Add counter-ions and physiological salt concentration via gmx genion."""
        logger.info(
            "[Step 5/6] Running gmx genion (conc: %.2f M %s/%s, neutral=%s)...",
            self.config.ion_concentration_m,
            self.config.positive_ion,
            self.config.negative_ion,
            self.config.neutralize,
        )
        args = [
            "-s",
            str(ions_tpr.resolve()),
            "-o",
            str(output_gro.resolve()),
            "-p",
            str(top_file.resolve()),
            "-pname",
            self.config.positive_ion,
            "-nname",
            self.config.negative_ion,
        ]
        if self.config.neutralize:
            args.append("-neutral")
        if self.config.ion_concentration_m > 0:
            args.extend(["-conc", f"{self.config.ion_concentration_m:.3f}"])

        # Feed "SOL\n" to genion stdin to select solvent molecules for replacement
        self._run_cmd("genion", args, cwd=work_dir, stdin_input="SOL\n")

    def step5b_minimize(
        self,
        ionized_gro: Path,
        top_file: Path,
        em_mdp: Path,
        output_tpr: Path,
        output_gro: Path,
        work_dir: Path,
    ) -> bool:
        """Step 5b: Energy minimization with steep to relax bad steric contacts."""
        logger.info("[Step 5b] Running gmx grompp & mdrun to relax system steric contacts...")
        grompp_args = [
            "-f",
            str(em_mdp.resolve()),
            "-c",
            str(ionized_gro.resolve()),
            "-p",
            str(top_file.resolve()),
            "-o",
            str(output_tpr.resolve()),
            "-maxwarn",
            "1",
        ]
        self._run_cmd("grompp", grompp_args, cwd=work_dir)

        # mdrun minimization on CPU with single thread-MPI rank to avoid thread/GPU conflicts
        mdrun_args = [
            "-v",
            "-s",
            str(output_tpr.resolve()),
            "-deffnm",
            "em",
            "-ntmpi",
            "1",
            "-ntomp",
            "4",
        ]
        try:
            self._run_cmd("mdrun", mdrun_args, cwd=work_dir)
            em_gro = work_dir / "em.gro"
            if em_gro.is_file():
                shutil.copyfile(em_gro, output_gro)
                return True
        except Exception as exc:
            logger.warning(
                "Energy minimization step failed (%s); proceeding with unminimized coordinates.",
                exc,
            )
        return False

    def step6_make_ndx(
        self,
        final_gro: Path,
        output_ndx: Path,
        work_dir: Path,
    ) -> None:
        """Step 6: Generate default index groups (System, Protein, Water_and_ions, etc.)."""
        logger.info("[Step 6/6] Running gmx make_ndx to generate system index file...")
        args = [
            "-f",
            str(final_gro.resolve()),
            "-o",
            str(output_ndx.resolve()),
        ]
        # "q\n" saves the default index groups and exits
        self._run_cmd("make_ndx", args, cwd=work_dir, stdin_input="q\n")

    def build_system(
        self,
        protein_pdb: Path,
        output_dir: Path,
        ligand_gro: Path | None = None,
        ligand_itp: Path | None = None,
        ligand_resname: str = "LIG",
    ) -> SolutionSystemSummary:
        """Execute the end-to-end solution builder pipeline.

        Args:
            protein_pdb: Cleaned receptor/protein PDB file.
            output_dir: Destination folder where all prepared artifacts are saved.
            ligand_gro: Optional coordinates of parameterized ligand to include.
            ligand_itp: Optional topology ITP of parameterized ligand.
            ligand_resname: Residue name for ligand molecule in topology.

        Returns:
            SolutionSystemSummary with atom counts, ion statistics, and output artifact paths.
        """
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        # Output artifact paths
        protein_gro = output_dir / "01_protein.gro"
        topol_top = output_dir / "topol.top"
        posre_itp = output_dir / "posre.itp"
        complex_gro = output_dir / "02_complex.gro"
        boxed_gro = output_dir / "03_boxed.gro"
        solvated_gro = output_dir / "04_solvated.gro"
        ions_mdp = output_dir / "ions.mdp"
        ions_tpr = output_dir / "ions.tpr"
        system_gro = output_dir / "system.gro"
        index_ndx = output_dir / "index.ndx"

        # Step 1: pdb2gmx
        self.step1_pdb2gmx(
            input_pdb=protein_pdb,
            output_gro=protein_gro,
            output_top=topol_top,
            posre_itp=posre_itp,
            work_dir=output_dir,
        )

        # Ensure posre.itp exists (multi-chain pdb2gmx outputs posre_Protein_chain_*.itp)
        if not posre_itp.is_file():
            chain_posres = sorted(output_dir.glob("posre_*.itp"))
            if chain_posres:
                shutil.copyfile(chain_posres[0], posre_itp)
            else:
                posre_itp.write_text("; empty position restraints\n", encoding="utf-8")

        # Handle optional ligand inclusion before box setup
        solute_gro = protein_gro
        if ligand_gro and ligand_itp:
            logger.info("Merging parameterized ligand into system...")
            solute_gro = complex_gro
            self._merge_ligand(
                protein_gro=protein_gro,
                ligand_gro=ligand_gro,
                output_complex_gro=complex_gro,
                top_file=topol_top,
                ligand_itp=ligand_itp,
                ligand_resname=ligand_resname,
                work_dir=output_dir,
            )

        # Step 2: editconf
        self.step2_editconf(
            input_gro=solute_gro,
            output_gro=boxed_gro,
            work_dir=output_dir,
        )

        # Step 3: solvate
        self.step3_solvate(
            input_gro=boxed_gro,
            output_gro=solvated_gro,
            top_file=topol_top,
            work_dir=output_dir,
        )

        # Step 4: Prepare ions.mdp & run grompp
        self.write_ions_mdp(ions_mdp)
        self.step4_grompp_for_ions(
            solvated_gro=solvated_gro,
            top_file=topol_top,
            ions_mdp=ions_mdp,
            output_tpr=ions_tpr,
            work_dir=output_dir,
        )

        # Step 5: genion
        ionized_gro = output_dir / "05_ionized.gro"
        self.step5_genion(
            ions_tpr=ions_tpr,
            top_file=topol_top,
            output_gro=ionized_gro,
            work_dir=output_dir,
        )

        # Step 5b: Energy minimization to relax bad steric contacts
        minimized = False
        em_mdp = output_dir / "em.mdp"
        em_tpr = output_dir / "em.tpr"
        if self.config.run_energy_minimization:
            self.write_em_mdp(em_mdp)
            minimized = self.step5b_minimize(
                ionized_gro=ionized_gro,
                top_file=topol_top,
                em_mdp=em_mdp,
                output_tpr=em_tpr,
                output_gro=system_gro,
                work_dir=output_dir,
            )
        if not minimized:
            shutil.copyfile(ionized_gro, system_gro)

        # Step 6: make_ndx
        self.step6_make_ndx(
            final_gro=system_gro,
            output_ndx=index_ndx,
            work_dir=output_dir,
        )

        # Analyze final prepared system
        summary = self._parse_system_summary(system_gro, topol_top)
        itp_files = {p.name: str(p) for p in output_dir.glob("*.itp")}
        summary.output_files = {
            "coordinates": str(system_gro),
            "topology": str(topol_top),
            "posre": str(posre_itp),
            "index": str(index_ndx),
            "ions_mdp": str(ions_mdp),
            "em_mdp": str(em_mdp),
            **itp_files,
        }
        logger.info(
            "✓ Solution system built successfully: %d atoms (%d water molecules, %d %s, %d %s)",
            summary.total_atoms,
            summary.water_molecules,
            summary.positive_ions,
            self.config.positive_ion,
            summary.negative_ions,
            self.config.negative_ion,
        )
        return summary

    def _merge_ligand(
        self,
        protein_gro: Path,
        ligand_gro: Path,
        output_complex_gro: Path,
        top_file: Path,
        ligand_itp: Path,
        ligand_resname: str,
        work_dir: Path,
    ) -> None:
        """Combine protein and ligand .gro coordinates and link ligand .itp in topol.top."""
        # Read protein .gro
        p_lines = protein_gro.read_text(encoding="utf-8").splitlines()
        p_title = p_lines[0]
        p_natoms = int(p_lines[1].strip())
        p_atoms = p_lines[2 : 2 + p_natoms]
        box_line = p_lines[2 + p_natoms]

        # Read ligand .gro
        l_lines = ligand_gro.read_text(encoding="utf-8").splitlines()
        l_natoms = int(l_lines[1].strip())
        l_atoms = l_lines[2 : 2 + l_natoms]

        total_atoms = p_natoms + l_natoms

        # Write merged complex .gro
        with open(output_complex_gro, "w", encoding="utf-8") as f:
            f.write(f"{p_title} + Ligand\n")
            f.write(f"{total_atoms:5d}\n")
            for line in p_atoms:
                f.write(f"{line}\n")
            for line in l_atoms:
                f.write(f"{line}\n")
            f.write(f"{box_line}\n")

        # Copy ligand itp into destination dir
        dest_itp = work_dir / ligand_itp.name
        if ligand_itp.resolve() != dest_itp.resolve():
            shutil.copy2(ligand_itp, dest_itp)

        # Update topol.top with #include "ligand.itp" and [ molecules ] entry
        top_text = top_file.read_text(encoding="utf-8")
        include_stmt = f'\n; Include ligand topology\n#include "{dest_itp.name}"\n'

        # Insert before position restraints or before [ system ]
        if "; Include Position restraint file" in top_text:
            parts = top_text.split("; Include Position restraint file", 1)
            new_top = parts[0] + include_stmt + "\n; Include Position restraint file" + parts[1]
        elif "[ system ]" in top_text:
            parts = top_text.split("[ system ]", 1)
            new_top = parts[0] + include_stmt + "\n[ system ]" + parts[1]
        else:
            new_top = top_text + include_stmt

        # Append ligand to [ molecules ]
        new_top = new_top.rstrip() + f"\n{ligand_resname:<10s} 1\n"
        top_file.write_text(new_top, encoding="utf-8")

    @staticmethod
    def _parse_system_summary(gro_file: Path, top_file: Path) -> SolutionSystemSummary:
        """Parse coordinate and topology files to extract system atom and molecule metrics."""
        summary = SolutionSystemSummary()
        lines = gro_file.read_text(encoding="utf-8").splitlines()
        if len(lines) >= 3:
            summary.total_atoms = int(lines[1].strip())
            box_parts = lines[-1].split()
            if len(box_parts) >= 3:
                try:
                    bx, by, bz = float(box_parts[0]), float(box_parts[1]), float(box_parts[2])
                    summary.box_vectors_nm = (bx, by, bz)
                    summary.box_volume_nm3 = bx * by * bz
                except ValueError:
                    pass

        # Parse [ molecules ] section from topol.top
        top_text = top_file.read_text(encoding="utf-8")
        if "[ molecules ]" in top_text:
            mol_section = top_text.split("[ molecules ]", 1)[1]
            for line in mol_section.splitlines():
                line = line.strip()
                if not line or line.startswith(";"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    name, count_str = parts[0], parts[1]
                    try:
                        count = int(count_str)
                        if name.upper() in ("SOL", "TIP3", "TIP3P", "SPC", "SPCE"):
                            summary.water_molecules += count
                        elif name.upper() in ("NA", "SOD", "NA+", "K", "POT"):
                            summary.positive_ions += count
                        elif name.upper() in ("CL", "CLA", "CL-"):
                            summary.negative_ions += count
                    except ValueError:
                        pass
        return summary


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for the GROMACS built-in solution builder."""
    desc = "GROMACS Built-in Solution Builder (pdb2gmx, editconf, solvate, genion, make_ndx)"
    parser = argparse.ArgumentParser(
        description=desc,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-f",
        "--protein",
        required=True,
        type=Path,
        help="Input protein PDB file (cleaned coordinates)",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=Path("solvated_system"),
        type=Path,
        help="Directory to save prepared system artifacts",
    )
    parser.add_argument(
        "-ff",
        "--forcefield",
        default="amber14sb",
        help="Force field (e.g. amber14sb, amber99sb-ildn, charmm27, oplsaa)",
    )
    parser.add_argument(
        "-w",
        "--water",
        default="tip3p",
        help="Water model (e.g. tip3p, spce, tip4p)",
    )
    parser.add_argument(
        "-bt",
        "--box-type",
        default="dodecahedron",
        choices=["dodecahedron", "cubic", "triclinic", "octahedron"],
        help="Unit cell simulation box geometry",
    )
    parser.add_argument(
        "-d",
        "--padding",
        default=1.0,
        type=float,
        help="Clearance distance between solute and box boundary in nm",
    )
    parser.add_argument(
        "-c",
        "--conc",
        default=0.15,
        type=float,
        help="Salt concentration in mol/L (e.g. 0.15 M NaCl)",
    )
    parser.add_argument(
        "--pname",
        default="NA",
        help="Positive ion name (e.g. NA, SOD)",
    )
    parser.add_argument(
        "--nname",
        default="CL",
        help="Negative ion name (e.g. CL, CLA)",
    )
    parser.add_argument(
        "--no-neutral",
        action="store_true",
        help="Do not automatically neutralize the net charge",
    )
    parser.add_argument(
        "--no-repair",
        action="store_true",
        help="Do not automatically repair missing sidechain heavy atoms with PDBFixer",
    )
    parser.add_argument(
        "--ligand-gro",
        type=Path,
        default=None,
        help="Optional: Path to parameterized ligand .gro coordinate file",
    )
    parser.add_argument(
        "--ligand-itp",
        type=Path,
        default=None,
        help="Optional: Path to parameterized ligand .itp topology file",
    )
    parser.add_argument(
        "--ligand-resname",
        default="LIG",
        help="Residue name for ligand in topology",
    )
    parser.add_argument(
        "--gmx",
        type=Path,
        default=None,
        help="Path to GROMACS executable (auto-discovered if omitted)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging output",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    config = SolutionBuilderConfig(
        forcefield=args.forcefield,
        water_model=args.water,
        box_type=args.box_type,
        box_padding_nm=args.padding,
        ion_concentration_m=args.conc,
        neutralize=not args.no_neutral,
        positive_ion=args.pname,
        negative_ion=args.nname,
        repair_missing_atoms=not args.no_repair,
    )

    try:
        builder = GromacsSolutionBuilder(gmx_bin=args.gmx, config=config)
        summary = builder.build_system(
            protein_pdb=args.protein,
            output_dir=args.output_dir,
            ligand_gro=args.ligand_gro,
            ligand_itp=args.ligand_itp,
            ligand_resname=args.ligand_resname,
        )

        print("\n" + "=" * 60)
        print(" GROMACS SOLUTION BUILDER - SYSTEM SUMMARY")
        print("=" * 60)
        print(f" Total Atoms:         {summary.total_atoms:,d}")
        print(f" Water Molecules:     {summary.water_molecules:,d}")
        print(f" Positive Ions ({args.pname}): {summary.positive_ions}")
        print(f" Negative Ions ({args.nname}): {summary.negative_ions}")
        bx, by, bz = summary.box_vectors_nm
        print(f" Box Dimensions (nm): {bx:.3f} x {by:.3f} x {bz:.3f}")
        print(f" Box Volume (nm³):    {summary.box_volume_nm3:.2f}")
        print("-" * 60)
        print(" Generated Artifacts:")
        for role, path in summary.output_files.items():
            print(f"   [{role:<12s}] -> {path}")
        print("=" * 60 + "\n")
        return 0

    except Exception as exc:
        logger.error("Build failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
