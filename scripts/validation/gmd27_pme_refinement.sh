#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <G-MD-27 artifact-capture directory> [--ewald-rtol VALUE] [PME spacings in nm...]" >&2
  exit 2
fi

capture_root=$(realpath -e -- "$1")
shift
ewald_rtol=""
spacings=()
while (($#)); do
  case "$1" in
    --ewald-rtol)
      shift
      if (($# == 0)) || [[ ! $1 =~ ^[0-9]+([.][0-9]+)?([eE][-+]?[0-9]+)?$ ]]; then
        echo "--ewald-rtol requires a numeric value" >&2
        exit 2
      fi
      ewald_rtol=$1
      ;;
    *)
      spacings+=("$1")
      ;;
  esac
  shift
done
if ((${#spacings[@]} == 0)); then
  spacings=(0.08 0.06)
fi
gmx=${CADDSUITE_GROMACS_EXECUTABLE:-gmx}
cd "$capture_root"

for spacing in "${spacings[@]}"; do
  if [[ ! $spacing =~ ^0\.[0-9]{2}$ ]]; then
    echo "Invalid PME spacing: $spacing (expected 0.xx nm)" >&2
    exit 2
  fi
  tag="pme-grid-${spacing//./}"
  if [[ -n $ewald_rtol ]]; then
    tag="${tag}-rtol-${ewald_rtol//./}"
  fi
  work="$capture_root/$tag"
  mkdir -- "$work"
  sed -E "s/^fourierspacing = .*/fourierspacing = $spacing/" energy.mdp \
    > "$work/energy.mdp"
  if [[ -n $ewald_rtol ]]; then
    printf 'ewald-rtol = %s\n' "$ewald_rtol" >> "$work/energy.mdp"
  fi
  (
    cd "$work"
    "$gmx" grompp -f energy.mdp -c "$capture_root/system.gro" \
      -p "$capture_root/topol.top" -o energy.tpr > grompp.log 2>&1
    "$gmx" mdrun -s energy.tpr -rerun "$capture_root/system.gro" \
      -deffnm rerun -nt 1 -nb cpu > mdrun.log 2>&1
    printf '%s\n' '1 2 3 4 5 6 7 8 9 10' '0' |
      "$gmx" energy -f rerun.edr -o components.xvg -xvg none > energy.log 2>&1
  )
  echo "PME spacing $spacing nm; mesh and component row:"
  grep -E 'Using a fourier grid' "$work/grompp.log" || true
  cat "$work/components.xvg"
done
