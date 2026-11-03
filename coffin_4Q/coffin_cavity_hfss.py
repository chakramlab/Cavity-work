# -*- coding: utf-8 -*-
"""
coffin_cavity_hfss.py
=====================
HFSS eigenmode run for the 4-transmon coffin cavity, mirroring the
SNAIL_coffin_cavity notebook flow:

    Inventor STEP (from coffin_4Q/inventor_coffin_4q.py)
      -> import into HFSS -> bounding box - metal = vacuum
      -> SMA center pins in the readout + drive bores (50 Ohm on bore end faces)
      -> cryo-copper finite conductivity on every other wall
      -> eigenmode solve -> CSV + mode plot vs. analytic rectangular-box modes

Empty cavity only (no chips yet), like the notebook's EM_Cavity design.
Run cell by cell (# %%) in the .AnE environment.
"""

# %% ---------------------------------------------------------------------------
# 0. CONFIG
# -----------------------------------------------------------------------------
import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from psutil import cpu_count
from scipy.constants import c, giga
from pyaedt import Hfss

NAME     = "coffin_4Q"
BASE     = Path(r"C:\Users\epm114\Documents\GitHub\Cavity work\coffin_4Q")
STEP     = BASE / "inventor_files" / f"{NAME}.stp"
PARAMS   = BASE / "inventor_files" / f"{NAME}_params.json"
AEDT     = BASE / "hfss_files" / f"{NAME}.aedt"
DESIGN   = "EM_Cavity"

# SMA pins (same as the SNAIL coffin: 1.27 mm dia center pin)
PIN_R         = 1.27 / 2     # mm
RO_PIN_LEN    = 5.0          # mm, readout pin length measured in from the +y face
DRIVE_PIN_GAP = 2.0          # mm, drive pin tip height above the seam / chip plane

SETUP = {
    "MinimumFrequency": "2GHz",
    "NumModes": 10,
    "MaxDeltaFreq": 0.05,
    "ConvergeOnRealFreq": True,
    "MaximumPasses": 20,
    "MinimumPasses": 2,
    "MinimumConvergedPasses": 2,
    "BasisOrder": -1,
}
CRYO_CU_SIGMA = 5.8e9        # S/m, OFHC Cu at 4 K, RRR ~100 (same as notebook)

for d in ("hfss_files", "data/eigenmode", "figures"):
    (BASE / d).mkdir(parents=True, exist_ok=True)

P = json.loads(PARAMS.read_text())["values"]       # mm, written by the Inventor builder
READOUTS = [(P["ro1_x"], P["ro1_z"]), (P["ro2_x"], P["ro2_z"])]
QUBIT_X  = [P[f"q{i}_x"] for i in range(1, 5)]
Y_DRIVE  = -(P["cav_W"] / 2 + P["drive_dy"])
num_cores = cpu_count(logical=False)


# %% ---------------------------------------------------------------------------
# 1. INITIALIZE HFSS
# -----------------------------------------------------------------------------
hfss = Hfss(project=str(AEDT), design=DESIGN, solution_type="Eigenmode", remove_lock=True)
hfss.modeler.model_units = "mm"

if not hfss.materials.exists_material("cryo_copper"):
    hfss.materials.add_material("cryo_copper")
hfss.materials["cryo_copper"].conductivity = CRYO_CU_SIGMA

# geometry params as project variables (like the notebook's Inventor -> $vars step)
for k, v in P.items():
    hfss[f"${k}"] = f"{v}mm"
hfss["$pin_r"]         = f"{PIN_R}mm"
hfss["$ro_pin_len"]    = f"{RO_PIN_LEN}mm"
hfss["$drive_pin_gap"] = f"{DRIVE_PIN_GAP}mm"
hfss["$drive_pin_len"] = "$block_H/2 - $drive_pin_gap"


# %% ---------------------------------------------------------------------------
# 2. GEOMETRY: import STEP, bounding box - metal = vacuum
# -----------------------------------------------------------------------------
try:
    hfss.oboundary.DeleteAllBoundaries()       # clean rerun
except Exception:
    pass
if hfss.modeler.object_list:
    hfss.modeler.delete()

hfss.modeler.import_3d_cad(str(STEP))
metal = list(hfss.modeler.solid_names)
assert len(metal) == 2, f"expected 2 solids (top/bottom) from the STEP, got {metal}"

# unit / placement check against the Inventor parameters
bb = hfss.modeler.get_model_bounding_box()
want = [-P["block_L"] / 2, -P["y_back"], -P["block_H"] / 2,
        P["block_L"] / 2, P["y_front"], P["block_H"] / 2]
assert np.allclose(bb, want, atol=1e-3), f"bounding box {bb} != expected {want} (units?)"

metal_vol = sum(float(hfss.modeler.oeditor.GetObjectVolume(m)) for m in metal)
box_dim = [b - a for a, b in zip(bb[:3], bb[3:])]
cavity = hfss.modeler.create_box(origin=bb[:3], sizes=box_dim, name="cavity", material="vacuum")
hfss.modeler.subtract("cavity", metal, keep_originals=False)
try:
    hfss.modeler.ungroup(NAME)
except Exception:
    pass

vac = float(hfss.modeler.oeditor.GetObjectVolume("cavity"))
vac_expected = np.prod(box_dim) - metal_vol
print(f"[geom] vacuum volume {vac:.2f} mm^3 (box - metal = {vac_expected:.2f})")
assert np.isclose(vac, vac_expected, rtol=1e-6), "vacuum != box - metal: subtract went wrong"

# SMA center pins (PEC by subtraction, same trick as the notebook)
pins = []
for i, (x, z) in enumerate(READOUTS, start=1):
    pins.append(hfss.modeler.create_cylinder(
        "Y", [f"$ro{i}_x", "$y_front - $ro_pin_len", f"$ro{i}_z"],
        "$pin_r", "$ro_pin_len", name=f"ro_pin_{i}").name)
for i in range(1, 5):
    pins.append(hfss.modeler.create_cylinder(
        "Z", [f"$q{i}_x", "-($cav_W/2 + $drive_dy)", "$block_H/2 - $drive_pin_len"],
        "$pin_r", "$drive_pin_len", name=f"drive_pin_{i}").name)
hfss.modeler.subtract("cavity", pins, keep_originals=False)
hfss.modeler.fit_all()


# %% ---------------------------------------------------------------------------
# 3. BOUNDARIES: 50 Ohm on each bore end face, cryo copper everywhere else
# -----------------------------------------------------------------------------
def annulus_face(x, y, z_or_none, axis):
    """Face id of the coax annulus at a bore mouth (point midway between pin and bore wall)."""
    if axis == "Y":
        r_mid = (PIN_R + P["ro_dia"] / 2) / 2
        pos = [x + r_mid, y, z_or_none]
    else:
        r_mid = (PIN_R + P["drive_dia"] / 2) / 2
        pos = [x + r_mid, y, P["block_H"] / 2]
    fid = hfss.modeler.get_faceid_from_position(pos, assignment="cavity")
    if not fid:
        raise RuntimeError(f"no cavity face at {pos}")
    return fid


port_faces = {}
for i, (x, z) in enumerate(READOUTS, start=1):
    port_faces[f"ro{i}"] = annulus_face(x, P["y_front"], z, "Y")
for i, x in enumerate(QUBIT_X, start=1):
    port_faces[f"drive{i}"] = annulus_face(x, Y_DRIVE, None, "Z")

omodule = hfss.odesign.GetModule("BoundarySetup")
for name, fid in port_faces.items():
    omodule.AssignImpedance(["NAME:" + name, "Faces:=", [fid],
                             "Resistance:=", "50", "Reactance:=", "0",
                             "InfGroundPlane:=", False])

all_faces = [f.id for f in hfss.modeler["cavity"].faces]
omodule.AssignFiniteCond(["NAME:cryo_copper",
                          "Faces:=", [f for f in all_faces if f not in port_faces.values()],
                          "UseMaterial:=", True, "Material:=", "cryo_copper",
                          "UseThickness:=", False, "Roughness:=", "0um",
                          "InfGroundPlane:=", False, "IsTwoSided:=", False, "IsInternal:=", True])
print(f"[bnd] 50 Ohm on {list(port_faces)}; cryo_copper on {len(all_faces) - len(port_faces)} faces")


# %% ---------------------------------------------------------------------------
# 4. EIGENMODE SOLVE
# -----------------------------------------------------------------------------
if DESIGN not in hfss.get_setups():
    hfss.create_setup(name=DESIGN, **SETUP)
hfss.analyze(cores=num_cores)
hfss.save_project()


# %% ---------------------------------------------------------------------------
# 5. RESULTS (same extraction as the notebook)
# -----------------------------------------------------------------------------
eigenmodes = hfss.post.available_report_quantities()
eigen_q = hfss.post.available_report_quantities(quantities_category="Eigen Q")
soln_data = {
    "Eigenmode": eigenmodes,
    "Frequency_Real (GHz)": [
        hfss.post.get_solution_data(expressions=m).get_expression_data(formula="real")[1][0] / giga
        for m in eigenmodes],
    "Frequency_Imag (GHz)": [
        hfss.post.get_solution_data(expressions=m).get_expression_data(formula="imag")[1][0] / giga
        for m in eigenmodes],
    "Q": [hfss.post.get_solution_data(expressions=q).get_expression_data(formula="real")[1][0]
          for q in eigen_q],
}
results = pd.DataFrame(soln_data)
results.to_csv(BASE / "data/eigenmode/cavity_eigenmode_results.csv", index=False)
print(results)


# %% ---------------------------------------------------------------------------
# 6. SANITY: analytic modes of the bare a x b x d box (ignores corners, tunnels, pins)
# -----------------------------------------------------------------------------
a, b, d = (P["cav_L"] * 1e-3, P["cav_W"] * 1e-3, P["cav_H"] * 1e-3)   # x, y, z


def f_mnl(m, n, l):
    return c / 2 * np.sqrt((m / a) ** 2 + (n / b) ** 2 + (l / d) ** 2)


box_modes = sorted(
    (f_mnl(m, n, l), (m, n, l))
    for m in range(6) for n in range(6) for l in range(6)
    if sum(k == 0 for k in (m, n, l)) <= 1                 # at most one zero index
)[: len(results)]
analytic = pd.DataFrame({"mode (m,n,l)": [str(k) for _, k in box_modes],
                         "f_box (GHz)": [f / giga for f, _ in box_modes]})
print(analytic)
if np.isclose(P["cav_W"], P["cav_H"]):
    print("[note] cav_W == cav_H -> (m,1,0)/(m,0,1)-type modes are degenerate in the bare box; "
          "expect near-degenerate pairs split only by tunnels, pins and corners.")

fig, ax = plt.subplots()
ax.plot(analytic["f_box (GHz)"], "bs--", label="bare box (analytic)")
ax.plot(results["Frequency_Real (GHz)"], "r^", label="HFSS")
ax.set_xticks(range(len(results)))
ax.set_xticklabels(results["Eigenmode"], rotation=45, ha="right")
ax.set_ylabel("Frequency (GHz)")
ax.legend()
fig.tight_layout()
fig.savefig(BASE / "figures/cavity_modes.pdf")
plt.show()


# %% ---------------------------------------------------------------------------
# 7. SAVE & RELEASE (leaves AEDT open)
# -----------------------------------------------------------------------------
hfss.save_project()
hfss.release_desktop(close_projects=False, close_desktop=False)
