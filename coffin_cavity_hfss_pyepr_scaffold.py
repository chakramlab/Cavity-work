# -*- coding: utf-8 -*-
"""
coffin_cavity_hfss.py
=====================
Starter scaffold: HFSS (AEDT 2023.2) + pyEPR 0.8 for the multiplexed-transmon
"coffin" cavity jig with a common, shared readout cavity.
(Lab notebook, 09/17/26 fab meeting, design (1)).

Planned device (geometry NOT built yet, only parameterized):
  * Coffin-shaped Cu package with a common readout cavity
  * Transmon chip in a tunnel coupled to the readout cavity
  * 5x coax drive lines coming in from the TOP, coupled to the transmon chip
  * 2x coax readout lines coupled to the readout cavity

Run top to bottom, or cell by cell (# %%) in VS Code / Jupyter.

Cells
  0. Config
  1. pyEPR 0.8 compat patches (numpy 2 / pandas 2), which must run BEFORE importing pyEPR
  2. Connect to AEDT, then open or create the project and design
  3. Units and design variables (placeholders for the coffin)
  4. Raw-COM helpers (junction rect + line + lumped RLC, 50-ohm coax terminations)
  5. Geometry build (stub, to fill in next)
  6. Eigenmode setup
  7. Smoke test (draw → verify → delete a test box)
  8. pyEPR analysis (off by default until geometry + junctions exist)
"""

# %% ---------------------------------------------------------------------------
# 0. CONFIG
# -----------------------------------------------------------------------------
from pathlib import Path

PROJECT_DIR   = Path(r"C:\Users\epm114\Documents\GitHub\Cavity work\coffin_cavity")
PROJECT_NAME  = "CoffinCavity"                         # no .aedt extension
DESIGN_NAME   = "Coffin_EM"                            # eigenmode design
DM_DESIGN_NAME = "Coffin_DM"                           # driven-modal design (S21 of readout lines)
MAKE_DM_DESIGN = False                                 # flip on when you want S-params

SETUP_NAME    = "Setup1"
MODEL_UNITS   = "mm"

# Optional: your existing compat-patch module from previous projects.
# If it imports cleanly, it's used instead of the inline patches below.
COMPAT_MODULE = None          # e.g. "pyepr_compat"

RUN_SMOKE_TEST = True
RUN_EPR        = False        # needs geometry + junctions + a solved setup


# %% ---------------------------------------------------------------------------
# 1. pyEPR 0.8 COMPAT PATCHES (must run before `import pyEPR`)
# -----------------------------------------------------------------------------
import importlib
import numpy as np
import pandas as pd


def _apply_inline_compat_patches():
    """Minimal, idempotent patches so pyEPR 0.8 runs on numpy>=1.24/2.x and pandas 2.x."""
    # numpy: removed scalar aliases / functions
    for alias, target in {
        "float": float, "int": int, "complex": complex, "bool": bool,
        "object": object, "str": str,
        "float_": np.float64, "complex_": np.complex128,
        "NaN": np.nan, "Inf": np.inf, "infty": np.inf,
    }.items():
        if alias not in np.__dict__:
            setattr(np, alias, target)
    for alias, target in {
        "product": np.prod, "cumproduct": np.cumprod,
        "alltrue": np.all, "sometrue": np.any,
    }.items():
        if alias not in np.__dict__:
            setattr(np, alias, target)

    # pandas: DataFrame/Series.append and .iteritems were removed in 2.0
    if not hasattr(pd.DataFrame, "append"):
        def _df_append(self, other, ignore_index=False, verify_integrity=False, sort=False):
            if isinstance(other, pd.Series):
                other = other.to_frame().T
            elif isinstance(other, dict):
                other = pd.DataFrame([other])
            elif isinstance(other, (list, tuple)):
                return pd.concat([self, *other], ignore_index=ignore_index,
                                 verify_integrity=verify_integrity, sort=sort)
            return pd.concat([self, other], ignore_index=ignore_index,
                             verify_integrity=verify_integrity, sort=sort)
        pd.DataFrame.append = _df_append

    if not hasattr(pd.Series, "append"):
        def _s_append(self, to_append, ignore_index=False, verify_integrity=False):
            others = list(to_append) if isinstance(to_append, (list, tuple)) else [to_append]
            return pd.concat([self, *others], ignore_index=ignore_index,
                             verify_integrity=verify_integrity)
        pd.Series.append = _s_append

    if not hasattr(pd.DataFrame, "iteritems"):
        pd.DataFrame.iteritems = pd.DataFrame.items
    if not hasattr(pd.Series, "iteritems"):
        pd.Series.iteritems = pd.Series.items


_patched_by = "inline"
if COMPAT_MODULE:
    try:
        importlib.import_module(COMPAT_MODULE)
        _patched_by = COMPAT_MODULE
    except ImportError as e:
        print(f"[compat] couldn't import {COMPAT_MODULE!r} ({e}); using inline patches")
        _apply_inline_compat_patches()
else:
    _apply_inline_compat_patches()

import pyEPR as epr                                     # noqa: E402
from pyEPR.ansys import HfssApp                         # noqa: E402

print(f"[compat] patches: {_patched_by} | numpy {np.__version__} | "
      f"pandas {pd.__version__} | pyEPR {getattr(epr, '__version__', '?')}")


# %% ---------------------------------------------------------------------------
# 2. CONNECT → OPEN/CREATE PROJECT → OPEN/CREATE DESIGN
# -----------------------------------------------------------------------------
# pyEPR's ProjectInfo/load_ansys_project asserts that the .aedt already exists,
# so we bootstrap the project + design ourselves, then hand off to ProjectInfo.

def get_or_create_project(desktop, project_dir: Path, project_name: str):
    project_dir.mkdir(parents=True, exist_ok=True)
    aedt_path = project_dir / f"{project_name}.aedt"

    if project_name in desktop.get_project_names():
        desktop.set_active_project(project_name)
        project = desktop.get_active_project()
        print(f"[hfss] using already-open project: {project_name}")
    elif aedt_path.is_file():
        project = desktop.open_project(str(aedt_path))
        print(f"[hfss] opened: {aedt_path}")
    else:
        project = desktop.new_project()
        project.save(str(aedt_path))
        print(f"[hfss] created: {aedt_path}")
    return project


def get_or_create_design(project, name: str, kind: str = "eigenmode"):
    if name in project.get_design_names():
        design = project.get_design(name)
        print(f"[hfss] using existing design: {name} ({design.solution_type})")
        return design
    if kind == "eigenmode":
        design = project.new_em_design(name)
    elif kind == "driven_modal":
        design = project.new_dm_design(name)
    else:
        raise ValueError(f"unknown design kind: {kind}")
    print(f"[hfss] created design: {name} ({kind})")
    return design


app     = HfssApp()                 # attaches to a running AEDT, else launches one
desktop = app.get_app_desktop()
project = get_or_create_project(desktop, PROJECT_DIR, PROJECT_NAME)
design  = get_or_create_design(project, DESIGN_NAME, "eigenmode")
dm_design = get_or_create_design(project, DM_DESIGN_NAME, "driven_modal") if MAKE_DM_DESIGN else None

# Raw COM handles, used by the helpers below (stable across AEDT versions)
oDesign     = design._design
oEditor     = oDesign.SetActiveEditor("3D Modeler")
oBoundaries = oDesign.GetModule("BoundarySetup")


# %% ---------------------------------------------------------------------------
# 3. UNITS + DESIGN VARIABLES
# -----------------------------------------------------------------------------
# ALL VALUES ARE PLACEHOLDERS. They set up names so geometry can be written
# against variables and swept later. Fix dimensions once the layout is set.

oEditor.SetModelUnits(["NAME:Units Parameter", "Units:=", MODEL_UNITS, "Rescale:=", False])

DESIGN_VARS = {
    # --- coffin package (outer vacuum volume that's cut from the Cu) ---
    "coffin_L":        "40mm",
    "coffin_W":        "20mm",
    "coffin_H":        "10mm",
    "coffin_end_r":    "5mm",       # end-cap radius for the coffin/stadium outline

    # --- common, shared readout cavity ---
    "ro_L":            "30mm",
    "ro_W":            "4mm",
    "ro_H":            "4mm",
    "ro_z":            "3mm",       # height of readout cavity centerline

    # --- chip tunnel + sapphire chip ---
    "tunnel_W":        "2.5mm",
    "tunnel_H":        "1.5mm",
    "tunnel_L":        "25mm",
    "chip_W":          "2mm",
    "chip_T":          "0.43mm",
    "chip_L":          "20mm",

    # --- junction (one per transmon; add Lj2..Lj5 as needed) ---
    "Lj1":             "10nH",
    "Cj1":             "2fF",
    "jj_len":          "0.1mm",
    "jj_w":            "0.05mm",

    # --- 5x top drive coax (SMA-ish, 50 ohm: r_out/r_in ≈ 2.3 in vacuum) ---
    "drv_r_in":        "0.25mm",
    "drv_r_out":       "0.575mm",
    "drv_pitch":       "4mm",
    "drv_x0":          "-8mm",      # x of drive #1; drive k at drv_x0 + (k-1)*drv_pitch
    "drv_depth":       "2mm",       # pin penetration below the package ceiling

    # --- 2x readout coax ---
    "rop_r_in":        "0.25mm",
    "rop_r_out":       "0.575mm",
    "rop_depth":       "1.5mm",
    "rop_x1":          "-10mm",
    "rop_x2":          "10mm",
}

for k, v in DESIGN_VARS.items():
    design.set_variable(k, v)
print(f"[hfss] set {len(DESIGN_VARS)} design variables")


# %% ---------------------------------------------------------------------------
# 4. RAW-COM HELPERS
# -----------------------------------------------------------------------------
def _attrs(name, material='"vacuum"', solve_inside=True, color="(143 175 143)", transparency=0.0):
    return ["NAME:Attributes",
            "Name:=", name, "Flags:=", "", "Color:=", color,
            "Transparency:=", transparency, "PartCoordinateSystem:=", "Global",
            "UDMId:=", "", "MaterialValue:=", material,
            "SurfaceMaterialValue:=", '""', "SolveInside:=", solve_inside,
            "IsMaterialEditable:=", True, "UseMaterialAppearance:=", False,
            "IsLightweight:=", False]


def draw_rect_z(name, x0, y0, z0, w, h):
    """Covered sheet in the XY plane at z0 (w along x, h along y). Expressions OK."""
    return oEditor.CreateRectangle(
        ["NAME:RectangleParameters", "IsCovered:=", True,
         "XStart:=", x0, "YStart:=", y0, "ZStart:=", z0,
         "Width:=", w, "Height:=", h, "WhichAxis:=", "Z"],
        _attrs(name, color="(255 128 0)"))


def draw_line(name, p0, p1):
    """Open 2-point polyline (used as the pyEPR junction current line)."""
    pt = lambda p: ["NAME:PLPoint", "X:=", p[0], "Y:=", p[1], "Z:=", p[2]]
    return oEditor.CreatePolyline(
        ["NAME:PolylineParameters", "IsPolylineCovered:=", True, "IsPolylineClosed:=", False,
         ["NAME:PolylinePoints", pt(p0), pt(p1)],
         ["NAME:PolylineSegments",
          ["NAME:PLSegment", "SegmentType:=", "Line", "StartIndex:=", 0, "NoOfPoints:=", 2]],
         ["NAME:PolylineXSection", "XSectionType:=", "None", "XSectionOrient:=", "Auto",
          "XSectionWidth:=", "0mm", "XSectionTopWidth:=", "0mm", "XSectionHeight:=", "0mm",
          "XSectionNumSegments:=", "0", "XSectionBendType:=", "Corner"]],
        _attrs(name, color="(0 0 255)"))


def assign_lumped_rlc(name, sheet, start, end, L=None, C=None, R=None):
    """Parallel lumped RLC on a sheet; start/end define the current line."""
    args = ["NAME:" + name, "Objects:=", [sheet],
            ["NAME:CurrentLine", "Start:=", list(start), "End:=", list(end)],
            "RLC Type:=", "Parallel",
            "UseResist:=", R is not None, "UseInduct:=", L is not None, "UseCap:=", C is not None]
    if R is not None: args += ["Resistance:=", R]
    if L is not None: args += ["Inductance:=", L]
    if C is not None: args += ["Capacitance:=", C]
    oBoundaries.AssignLumpRLC(args)


def make_junction(tag, center, Lj_var, Cj_var="", axis="x"):
    """
    Junction sheet + current line + lumped L(C), named for pyEPR:
        rect = f"{tag}_rect", line = f"{tag}_line", boundary = f"{tag}_RLC"
    center: (x, y, z) expression strings. The junction lies in the XY plane at z.
    """
    cx, cy, cz = center
    if axis == "x":
        x0, y0, w, h = f"{cx}-jj_len/2", f"{cy}-jj_w/2", "jj_len", "jj_w"
        p0, p1 = (f"{cx}-jj_len/2", cy, cz), (f"{cx}+jj_len/2", cy, cz)
    else:
        x0, y0, w, h = f"{cx}-jj_w/2", f"{cy}-jj_len/2", "jj_w", "jj_len"
        p0, p1 = (cx, f"{cy}-jj_len/2", cz), (cx, f"{cy}+jj_len/2", cz)
    draw_rect_z(f"{tag}_rect", x0, y0, cz, w, h)
    draw_line(f"{tag}_line", p0, p1)
    assign_lumped_rlc(f"{tag}_RLC", f"{tag}_rect", p0, p1, L=Lj_var, C=(Cj_var or None))
    return {"Lj_variable": Lj_var, "rect": f"{tag}_rect", "line": f"{tag}_line",
            "length": epr.parse_units(DESIGN_VARS["jj_len"])}


def terminate_coax_50ohm(tag, sheet, start, end):
    """Eigenmode stand-in for a port: 50-ohm lumped R across the coax annulus → gives Q_ext."""
    assign_lumped_rlc(f"{tag}_R50", sheet, start, end, R="50ohm")


def delete_objects(*names):
    oEditor.Delete(["NAME:Selections", "Selections:=", ",".join(names)])


# %% ---------------------------------------------------------------------------
# 5. GEOMETRY (stub, to build next)
# -----------------------------------------------------------------------------
JUNCTIONS = {}   # filled by make_junction(...) calls, handed to pyEPR


def build_geometry():
    """
    TODO, next step:
      1. coffin vacuum body (stadium outline × coffin_H)
      2. readout cavity + chip tunnel, united into the vacuum
      3. sapphire chip + transmon pads (PerfE sheets) + make_junction(...) per qubit
      4. 5 top drive coax (outer vacuum cyl + inner PEC pin, drv_depth penetration)
      5. 2 readout coax into the readout cavity
      6. 50-ohm terminations on each coax face
    """
    pass


build_geometry()


# %% ---------------------------------------------------------------------------
# 6. EIGENMODE SETUP
# -----------------------------------------------------------------------------
if SETUP_NAME not in design.get_setup_names():
    design.create_em_setup(
        name=SETUP_NAME,
        min_freq_ghz=3.0,     # below the transmons
        n_modes=3,            # bump to (n_qubits + readout + spurious) once built
        max_delta_f=0.1,      # percent
        max_passes=20,
        min_passes=2,
        min_converged=2,
        pct_refinement=30,
        basis_order=1,
    )
    print(f"[hfss] created eigenmode setup: {SETUP_NAME}")
else:
    print(f"[hfss] setup exists: {SETUP_NAME}")


# %% ---------------------------------------------------------------------------
# 7. SMOKE TEST: draw a variable-driven box, confirm it exists, delete it
# -----------------------------------------------------------------------------
if RUN_SMOKE_TEST:
    _name = "zz_smoke_box"
    oEditor.CreateBox(
        ["NAME:BoxParameters",
         "XPosition:=", "-coffin_L/2", "YPosition:=", "-coffin_W/2", "ZPosition:=", "0mm",
         "XSize:=", "coffin_L", "YSize:=", "coffin_W", "ZSize:=", "coffin_H"],
        _attrs(_name, transparency=0.8))
    ok = _name in oEditor.GetObjectsInGroup("Solids")
    delete_objects(_name)
    print(f"[smoke] draw/verify/delete with design variables: {'OK' if ok else 'FAILED'}")

project.save()
print("[hfss] project saved")


# %% ---------------------------------------------------------------------------
# 8. pyEPR ANALYSIS (enable once geometry + junctions exist and Setup1 is solved)
# -----------------------------------------------------------------------------
if RUN_EPR:
    pinfo = epr.ProjectInfo(project_path=str(PROJECT_DIR),
                            project_name=PROJECT_NAME,
                            design_name=DESIGN_NAME,
                            setup_name=SETUP_NAME)

    for jname, jinfo in JUNCTIONS.items():
        pinfo.junctions[jname] = jinfo
    pinfo.validate_junction_info()

    # Loss participation (set once objects exist)
    pinfo.dissipative["dielectrics_bulk"] = []   # e.g. ["chip"]
    pinfo.dissipative["dielectric_surfaces"] = None

    pinfo.setup.analyze()

    eprd = epr.DistributedAnalysis(pinfo)
    eprd.do_EPR_analysis()

    epra = epr.QuantumAnalysis(eprd.data_filename)
    epra.analyze_all_variations(cos_trunc=8, fock_trunc=7)
    epra.report_results(swp_variable="variation", numeric=True)
