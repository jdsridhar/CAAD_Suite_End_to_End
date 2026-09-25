# Conceptual-DFT descriptor audit

The frozen legacy descriptors.py implements six descriptors from frontier orbital energies. It is pure arithmetic, engine-independent. Inputs are eV; softness is eV inverse and other outputs are eV. It estimates IP as negative HOMO and EA as negative LUMO (Koopmans-style approximations), then calculates mu=-(IP+EA)/2, hardness=(IP-EA)/2, softness=1/(2 hardness), and electrophilicity=mu squared/(2 hardness). These are not delta-SCF vertical IP/EA calculations or measured properties.

Findings: output is an untyped dictionary; NaN/infinite energies are accepted; negative hardness yields negative division-based descriptors. The migrated analysis rejects non-finite inputs and leaves softness/electrophilicity null at non-positive hardness with an explicit reason. It records method/units in a strict typed result. QMResult.conceptual_dft remains a dictionary in schema qm_result/2.0 for payload compatibility; callers may serialize the typed result to that existing field.

Unit coverage uses hand-calculated energies, zero/negative hardness, and non-finite inputs. Engine regression remains separately covered.
