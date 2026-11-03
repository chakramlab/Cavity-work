# -*- coding: utf-8 -*-
"""
inventor_coffin_4q.py
=====================
Builds the 4-transmon "coffin" cavity as two machinable halves in Autodesk
Inventor via COM, then exports the assembly to STEP for the HFSS pipeline
(same flow as SNAIL_coffin_cavity: Inventor → .stp → HFSS bounding-box subtract).

Starting point = the old SNAIL coffin cavity (dimensions read from its STEP):
    cavity 32 x 9 x 32 mm, r = 2 mm vertical corners, split at z = 0
    chip pocket 7.5 w x 0.43 d x 30 l (bottom), clearance pocket 3.86 l (top)
    SMA bores 2.946 mm dia, 8.75 mm long through the +y wall
Changes:
    cavity 50 mm long, 4 chip tunnels on the -y wall, 2 readout bores on the
    +y wall, 4 drive bores from the top face landing on each chip tunnel.

Coordinates (mm): origin at cavity center, seam plane z = 0,
    x = cavity length, y = cavity width (+y readout side, -y chip side), z = height.
    bottom half: z <= 0  (cavity pocket, chip tunnels, readout ports with z < 0)
    top half:    z >= 0  (cavity pocket, chip clearance pockets, drive bores, ports z > 0)

Every dimension is an Inventor user parameter (fx table) and sketches carry
driving dimensions tied to those parameters, so the machine shop can edit
the .ipt directly. NOTE: rerunning this script rebuilds from PARAMS below and
overwrites the parts (old files are backed up to inventor_files/_previous/).

Run cell by cell (# %%) or top to bottom in the .AnE env with Inventor installed.
"""

# %% ---------------------------------------------------------------------------
# 0. CONFIG + PARAMETERS
# -----------------------------------------------------------------------------
import json
import math
import shutil
import datetime
from pathlib import Path

NAME    = "coffin_4Q"
OUT_DIR = Path(r"C:\Users\epm114\Documents\GitHub\Cavity work\coffin_4Q\inventor_files")

ADD_CONSTRAINTS = True   # driving sketch dimensions linked to parameters
EXPORT_STEP     = True

# (name, expression, comment). Numbers are mm. Expressions may reference earlier
# names, and are written to Inventor verbatim, so keep to + - * / ( ) and numbers.
PARAMS = [
    # --- cavity (coffin) ---
    ("cav_L",        50.0,   "cavity length (x)"),
    ("cav_W",        15.0  ,    "cavity width (y)"),
    ("cav_H",        20.8,   "cavity height (z), split evenly at the seam"),
    ("cav_r",        2.0,    "vertical corner radius (>= end mill radius)"),
    # --- walls / block ---
    ("wall_x",       6.0,    "wall beyond cavity ends (x)"),
    ("wall_z",       5.0,    "wall above/below cavity (z)"),
    ("wall_back",    5.0,    "wall behind the end of the chip tunnels (-y)"),
    # --- chip tunnels (bottom half, -y side) ---
    ("chip_T",       0.5,   "chip tunnel depth = chip thickness"),
    ("tunnel_W",     6.5,    "chip tunnel width"),
    ("tunnel_L",     30.0,   "chip tunnel length from cavity wall"),
    ("tunnel_r",     0.0,    "tunnel corner radius (0 = sharp; keep <= ovl)"),
    ("q1_x",         "-3*cav_L/8", "transmon 1 x position"),
    ("q2_x",         "-cav_L/8",   "transmon 2 x position"),
    ("q3_x",         "cav_L/8",    "transmon 3 x position"),
    ("q4_x",         "3*cav_L/8",  "transmon 4 x position"),
    # --- chip clearance pockets (top half, above chips near the cavity) ---
    ("top_pocket_L", 10,   "clearance pocket length from cavity wall"),
    ("top_pocket_D", 0.43,   "clearance pocket depth"),
    # --- drive bores (top half, from top face down onto each chip tunnel) ---
    ("drive_dia",    2.946,  "drive bore diameter"),
    ("drive_dy",     7.5,    "drive bore center distance from cavity wall (-y)"),
    # --- readout bores (+y wall) ---
    ("ro_dia",       2.946,  "readout bore diameter"),
    ("ro_port_len",  8.75,   "readout bore length = +y wall thickness"),
    ("ro1_x",        0, "readout 1 x"),
    ("ro1_z",        -5, "readout 1 z (<0 -> bottom half)"),
    ("ro2_x",        0,  "readout 2 x"),
    ("ro2_z",       5,  "readout 2 z (>0 -> top half)"),
    # --- construction ---
    ("ovl",          0.5,    "cut overlap into the cavity void (clean booleans)"),
    # --- derived (update automatically when the above change) ---
    ("block_L",      "cav_L + 2*wall_x",                 "block length (x)"),
    ("block_H",      "cav_H + 2*wall_z",                 "block height (z), both halves"),
    ("y_front",      "cav_W/2 + ro_port_len",            "+y block face"),
    ("y_back",       "cav_W/2 + tunnel_L + wall_back",   "-y block face (distance)"),
]

N_Q = 4
READOUTS = [("ro1_x", "ro1_z"), ("ro2_x", "ro2_z")]


# %% ---------------------------------------------------------------------------
# 1. PURE-PYTHON GEOMETRY: evaluate, validate, expected volumes
# -----------------------------------------------------------------------------
def evaluate(params):
    v = {}
    for name, expr, _ in params:
        v[name] = float(expr) if isinstance(expr, (int, float)) else float(
            eval(expr, {"__builtins__": {}}, dict(v)))
    return v


def validate(v):
    """Catch layouts that would overlap / break walls before touching Inventor."""
    errs = []
    flat_half = v["cav_L"] / 2 - v["cav_r"]
    xs = sorted(v[f"q{i}_x"] for i in range(1, N_Q + 1))
    for a, b in zip(xs, xs[1:]):
        if b - a <= v["tunnel_W"]:
            errs.append(f"chip tunnels overlap (pitch {b - a:.3f} <= tunnel_W)")
    for i in range(1, N_Q + 1):
        if abs(v[f"q{i}_x"]) + v["tunnel_W"] / 2 > flat_half:
            errs.append(f"tunnel {i} runs into the cavity corner radius")
    if v["drive_dy"] - v["drive_dia"] / 2 <= 0:
        errs.append("drive bores break into the cavity wall (drive_dy <= drive_dia/2)")
    if v["drive_dia"] >= v["tunnel_W"]:
        errs.append("drive bores wider than the chip tunnels")
    if v["drive_dy"] + v["drive_dia"] / 2 >= v["tunnel_L"]:
        errs.append("drive bores land beyond the end of the chip tunnels")
    if v["tunnel_r"] > v["ovl"]:
        errs.append("tunnel_r > ovl (volume check assumes otherwise)")
    for xn, zn in READOUTS:
        x, z, r = v[xn], v[zn], v["ro_dia"] / 2
        if abs(x) + r > flat_half:
            errs.append(f"{xn}: bore hits the cavity corner radius")
        if abs(z) - r <= 0 or abs(z) + r >= v["cav_H"] / 2:
            errs.append(f"{zn}: bore must sit fully inside one half's cavity wall")
    for a, b in zip(READOUTS, READOUTS[1:]):
        if (math.isclose(math.copysign(1, v[a[1]]), math.copysign(1, v[b[1]]))
                and abs(v[a[0]] - v[b[0]]) <= v["ro_dia"]):
            errs.append("readout bores overlap")
    if errs:
        raise ValueError("Bad parameters:\n  - " + "\n  - ".join(errs))


def circle_rect_area(xc, yc, r, x0, x1, y0, y1, n=20000):
    """Area of circle ∩ axis-aligned rectangle (midpoint rule over x)."""
    a, b = max(xc - r, x0), min(xc + r, x1)
    if a >= b:
        return 0.0
    dx, area = (b - a) / n, 0.0
    for k in range(n):
        x = a + (k + 0.5) * dx
        h = math.sqrt(max(r * r - (x - xc) ** 2, 0.0))
        area += max(0.0, min(yc + h, y1) - max(yc - h, y0)) * dx
    return area


def expected_volumes(v):
    """Metal volume of each half (mm^3), assuming validate() passed.
    The only overlap allowed is drive bore ∩ top clearance pocket (handled below;
    ignores tunnel_r rounding inside that overlap)."""
    hh = v["block_H"] / 2
    block = v["block_L"] * (v["y_front"] + v["y_back"]) * hh
    cav = (v["cav_L"] * v["cav_W"] - (4 - math.pi) * v["cav_r"] ** 2) * v["cav_H"] / 2
    rc = (1 - math.pi / 4) * v["tunnel_r"] ** 2          # far-end corner loss
    tunnel = v["tunnel_W"] * v["tunnel_L"] * v["chip_T"] - 2 * rc * v["chip_T"]
    pocket = v["tunnel_W"] * v["top_pocket_L"] * v["top_pocket_D"] - 2 * rc * v["top_pocket_D"]
    ro = math.pi * (v["ro_dia"] / 2) ** 2 * v["ro_port_len"]
    rd, yd = v["drive_dia"] / 2, -(v["cav_W"] / 2 + v["drive_dy"])
    shared = circle_rect_area(0.0, yd, rd, -v["tunnel_W"] / 2, v["tunnel_W"] / 2,
                              -(v["cav_W"] / 2 + v["top_pocket_L"]), -v["cav_W"] / 2)
    drive = math.pi * rd ** 2 * hh - shared * v["top_pocket_D"]   # already cut by the pocket
    n_ro_bot = sum(v[z] < 0 for _, z in READOUTS)
    n_ro_top = len(READOUTS) - n_ro_bot
    return {
        "bottom": block - cav - N_Q * tunnel - n_ro_bot * ro,
        "top":    block - cav - N_Q * pocket - N_Q * drive - n_ro_top * ro,
    }


VALS = evaluate(PARAMS)
validate(VALS)
EXPECTED = expected_volumes(VALS)
print(f"[geom] block {VALS['block_L']:.2f} x {VALS['y_front'] + VALS['y_back']:.2f} x "
      f"{VALS['block_H']:.2f} mm | expected metal: bottom {EXPECTED['bottom']:.1f}, "
      f"top {EXPECTED['top']:.1f} mm^3")


# %% ---------------------------------------------------------------------------
# 2. INVENTOR CONNECTION + CONSTANTS
# -----------------------------------------------------------------------------
def connect_inventor():
    import pythoncom
    import pywintypes
    from win32com.client import dynamic
    # Attach to a running Inventor through raw pythoncom: win32com's GetActiveObject wraps the
    # object with the gen_py classes and fails (KeyError '_dispobj_') once they exist, and the
    # old Dispatch fallback then started an extra Inventor on every run.
    try:
        unk = pythoncom.GetActiveObject(pywintypes.IID("Inventor.Application"))
        app = dynamic.Dispatch(unk.QueryInterface(pythoncom.IID_IDispatch))
        print("[inv] attached to running Inventor")
    except pythoncom.com_error:
        app = dynamic.Dispatch("Inventor.Application")  # late binding: Document.ComponentDefinition works
        print("[inv] started Inventor")
    app.Visible = True
    return app


_FALLBACK = {   # Inventor enum values, used if the type library can't be loaded
    "kPartDocumentObject": 12290, "kAssemblyDocumentObject": 12291,
    "kMetricSystemOfMeasure": 8963, "kMillimeterLengthUnits": 11269,
    "kJoinOperation": 20481, "kCutOperation": 20482,
    "kPositiveExtentDirection": 20993, "kNegativeExtentDirection": 20994,
    "kSymmetricExtentDirection": 20995,
    "kHorizontalDim": 19202, "kVerticalDim": 19203,
}


def load_constants():
    try:
        from win32com.client import gencache, constants
        gencache.EnsureModule("{D98A091D-3A0F-4C3E-B36E-61F62068D488}", 0, 1, 0)
        consts = {k: getattr(constants, k) for k in _FALLBACK}
        print("[inv] enums from the Inventor type library")
    except Exception as e:
        consts = dict(_FALLBACK)
        print(f"[inv] type library not loaded ({e}); using built-in enum values")
    return consts


# %% ---------------------------------------------------------------------------
# 3. BUILDER HELPERS
# -----------------------------------------------------------------------------
class Part:
    """One .ipt: parameters, sketches with driving dims, extrudes with checks."""

    def __init__(self, app, K, name):
        self.app, self.K, self.name = app, K, name
        self.tg = app.TransientGeometry
        kpart = K["kPartDocumentObject"]
        try:
            tmpl = app.FileManager.GetTemplateFile(kpart, K["kMetricSystemOfMeasure"])
        except Exception:
            tmpl = app.FileManager.GetTemplateFile(kpart)
        self.doc = app.Documents.Add(kpart, tmpl, True)
        try:
            self.doc.UnitsOfMeasure.LengthUnits = K["kMillimeterLengthUnits"]
        except Exception:
            pass
        self.cd = self.doc.ComponentDefinition
        self.xy = self.cd.WorkPlanes.Item(3)
        self.xz = self.cd.WorkPlanes.Item(2)
        self.warnings = []

    # ---------------- parameters ----------------
    def add_parameters(self, params, vals):
        up = self.cd.Parameters.UserParameters
        for name, expr, comment in params:
            e = f"{expr} mm" if isinstance(expr, (int, float)) else expr
            p = up.AddByExpression(name, e, "mm")
            try:
                p.Comment = comment
            except Exception:
                pass
            got = p.Value * 10.0                          # Inventor stores cm
            if not math.isclose(got, vals[name], rel_tol=1e-9, abs_tol=1e-9):
                self.warnings.append(f"param {name}: Inventor={got} vs Python={vals[name]}")

    # ---------------- geometry checks ----------------
    def volume_mm3(self):
        return self.cd.MassProperties.Volume * 1000.0     # cm^3 → mm^3

    def zrange_mm(self):
        rb = self.cd.RangeBox
        return rb.MinPoint.Z * 10.0, rb.MaxPoint.Z * 10.0

    # ---------------- workplanes ----------------
    def xz_offset_plane(self, y_mm, expr, name):
        """Plane parallel to XZ at model y = y_mm (sign checked, since XZ normal may be ±y)."""
        for e in (expr, f"-({expr})"):
            wp = self.cd.WorkPlanes.AddByPlaneAndOffset(self.xz, e)
            if math.isclose(wp.Plane.RootPoint.Y * 10.0, y_mm, abs_tol=1e-6):
                wp.Name, wp.Visible = name, False
                return wp
            wp.Delete()
        raise RuntimeError(f"could not place work plane at y = {y_mm}")

    # ---------------- extrude ----------------
    def extrude(self, sketch, op, name, dist=None, through_all=False, directions=None):
        """Extrude; for cuts, try each direction and keep the one that removes metal."""
        K, ef = self.K, self.cd.Features.ExtrudeFeatures
        directions = directions or [K["kNegativeExtentDirection"], K["kPositiveExtentDirection"]]
        is_cut = op == K["kCutOperation"]
        last = None
        for d in directions:
            v0 = self.volume_mm3() if is_cut else None
            dfn = ef.CreateExtrudeDefinition(sketch.Profiles.AddForSolid(), op)
            if through_all:
                dfn.SetThroughAllExtent(d)
            else:
                dfn.SetDistanceExtent(dist, d)
            try:
                f = ef.Add(dfn)
            except Exception as e:
                last = e
                continue
            if is_cut and math.isclose(self.volume_mm3(), v0, rel_tol=1e-9):
                f.Delete(True)                            # keep sketch; cut hit empty space
                continue
            f.Name = name
            print(f"  [{self.name}] {name}: ok")
            return f
        raise RuntimeError(f"extrude '{name}' failed in every direction ({last})")


class Sketch:
    """Planar sketch with model-space placement and parameter-driven dimensions.

    embed(a, b) -> (x, y, z) maps in-plane coordinates (mm) to model space.
    exprs for positions are the Inventor expressions of those same a/b values.
    """

    def __init__(self, part, plane, name, embed):
        self.p, self.K, self.tg = part, part.K, part.tg
        print(f"  [{part.name}] sketch {name} ...")
        self.sk = part.cd.Sketches.Add(plane)
        self.sk.Name = name
        self.embed = embed
        self.origin = None
        if ADD_CONSTRAINTS:
            try:
                self.origin = self.sk.AddByProjectingEntity(part.cd.WorkPoints.Item(1))
            except Exception as e:
                part.warnings.append(f"{name}: could not project origin ({e})")
        p0, pa, pb = self.pt(0, 0), self.pt(1, 0), self.pt(0, 1)
        ua, ub = (pa.X - p0.X, pa.Y - p0.Y), (pb.X - p0.X, pb.Y - p0.Y)
        self.ccw = (ua[0] * ub[1] - ua[1] * ub[0]) > 0      # sketch handedness vs (a, b)
        self.a_is_horizontal = abs(ua[0]) > abs(ua[1])

    def pt(self, a, b):
        x, y, z = self.embed(a, b)
        return self.sk.ModelToSketchSpace(self.tg.CreatePoint(x / 10, y / 10, z / 10))

    # ---- constraint helpers (best effort; failures are logged, geometry stays) ----
    def _try(self, label, fn):
        if not ADD_CONSTRAINTS:
            return None
        try:
            return fn()
        except Exception as e:
            self.p.warnings.append(f"{self.sk.Name}: {label} ({e})")
            return None

    def _drive(self, dim, expr):
        if dim is not None:
            dim.Parameter.Expression = expr

    def _pos(self, sketch_point, axis, value, expr, text):
        """Driving distance from the projected origin along in-plane axis 'a' or 'b'."""
        if self.origin is None or abs(value) < 1e-9:
            return
        horiz = self.a_is_horizontal if axis == "a" else not self.a_is_horizontal
        orient = self.K["kHorizontalDim"] if horiz else self.K["kVerticalDim"]
        e = expr if value > 0 else f"-({expr})"
        dc = self.sk.DimensionConstraints
        dim = self._try(f"pos {axis}", lambda: dc.AddTwoPointDistance(
            self.origin, sketch_point, orient, text))
        self._try(f"pos {axis} expr", lambda: self._drive(dim, e))

    def _hv(self, line):
        gc = self.sk.GeometricConstraints
        s, t = line.StartSketchPoint.Geometry, line.EndSketchPoint.Geometry
        if abs(t.X - s.X) > abs(t.Y - s.Y):
            self._try("horizontal", lambda: gc.AddHorizontal(line))
        else:
            self._try("vertical", lambda: gc.AddVertical(line))

    # ---- shapes ----
    def rect(self, a0, b0, w, h, r, ex):
        """Rectangle with min corner (a0, b0), size w x h (mm), corner radius r.
        ex: expressions {'a0','b0','w','h','r'}."""
        sl, sa = self.sk.SketchLines, self.sk.SketchArcs
        a1, b1 = a0 + w, b0 + h
        if r <= 0:
            c = [self.pt(a0, b0), self.pt(a1, b0), self.pt(a1, b1), self.pt(a0, b1)]
            bot = sl.AddByTwoPoints(c[0], c[1])
            rgt = sl.AddByTwoPoints(bot.EndSketchPoint, c[2])
            top = sl.AddByTwoPoints(rgt.EndSketchPoint, c[3])
            lft = sl.AddByTwoPoints(top.EndSketchPoint, bot.StartSketchPoint)
            anchor = bot.StartSketchPoint
            anchor_ab = (a0, b0, ex["a0"], ex["b0"])
            arcs = []
        else:
            ccw = self.ccw
            cen = [(a0 + r, b0 + r), (a1 - r, b0 + r), (a1 - r, b1 - r), (a0 + r, b1 - r)]
            # (start, end) tangent points walking around the shape in +a,+b orientation
            se = [((a0, b0 + r), (a0 + r, b0)), ((a1 - r, b0), (a1, b0 + r)),
                  ((a1, b1 - r), (a1 - r, b1)), ((a0 + r, b1), (a0, b1 - r))]
            arcs = []
            for (ca, cb), (s, e) in zip(cen, se):
                if ccw:
                    arcs.append(sa.AddByCenterStartEndPoint(self.pt(ca, cb), self.pt(*s), self.pt(*e), True))
                else:
                    arcs.append(sa.AddByCenterStartEndPoint(self.pt(ca, cb), self.pt(*e), self.pt(*s), True))

            def tail(arc):  # end of the arc in shape-walk order
                return arc.EndSketchPoint if ccw else arc.StartSketchPoint

            def head(arc):
                return arc.StartSketchPoint if ccw else arc.EndSketchPoint

            bot = sl.AddByTwoPoints(tail(arcs[0]), head(arcs[1]))
            rgt = sl.AddByTwoPoints(tail(arcs[1]), head(arcs[2]))
            top = sl.AddByTwoPoints(tail(arcs[2]), head(arcs[3]))
            lft = sl.AddByTwoPoints(tail(arcs[3]), head(arcs[0]))
            gc = self.sk.GeometricConstraints
            for ln, (i, j) in zip((bot, rgt, top, lft), ((0, 1), (1, 2), (2, 3), (3, 0))):
                self._try("tangent", lambda ln=ln, i=i: gc.AddTangent(ln, arcs[i]))
                self._try("tangent", lambda ln=ln, j=j: gc.AddTangent(ln, arcs[j]))
            anchor = arcs[0].CenterSketchPoint
            anchor_ab = (a0 + r, b0 + r, f"({ex['a0']}) + ({ex['r']})", f"({ex['b0']}) + ({ex['r']})")

        for ln in (bot, rgt, top, lft):
            self._hv(ln)
        dc = self.sk.DimensionConstraints
        txt = self.pt(a0 + w / 2, b0 - 1.0)
        d_w = self._try("width", lambda: dc.AddOffset(lft, rgt, txt, False))
        self._try("width expr", lambda: self._drive(d_w, ex["w"]))
        txt = self.pt(a0 - 1.0, b0 + h / 2)
        d_h = self._try("height", lambda: dc.AddOffset(bot, top, txt, False))
        self._try("height expr", lambda: self._drive(d_h, ex["h"]))
        for k, arc in enumerate(arcs):
            txt = self.pt(*[(a0 - 1, b0 - 1), (a1 + 1, b0 - 1), (a1 + 1, b1 + 1), (a0 - 1, b1 + 1)][k])
            d_r = self._try("radius", lambda arc=arc, txt=txt: dc.AddRadius(arc, txt))
            self._try("radius expr", lambda d_r=d_r: self._drive(d_r, ex["r"]))
        aa, bb, ea, eb = anchor_ab
        self._pos(anchor, "a", aa, ea, self.pt(aa / 2, bb - 2))
        self._pos(anchor, "b", bb, eb, self.pt(aa - 2, bb / 2))

    def circle(self, a, b, d, ex):
        """Circle at (a, b), diameter d (mm). ex: {'a','b','d'}."""
        c = self.sk.SketchCircles.AddByCenterRadius(self.pt(a, b), d / 20.0)
        dc = self.sk.DimensionConstraints
        txt = self.pt(a + d, b + d)
        dim = self._try("diameter", lambda: dc.AddDiameter(c, txt))
        self._try("diameter expr", lambda: self._drive(dim, ex["d"]))
        self._pos(c.CenterSketchPoint, "a", a, ex["a"], self.pt(a / 2, b + d + 1))
        self._pos(c.CenterSketchPoint, "b", b, ex["b"], self.pt(a + d + 1, b / 2))


# %% ---------------------------------------------------------------------------
# 4. BUILD ONE HALF
# -----------------------------------------------------------------------------
def build_half(app, K, half, v):
    """half: 'bottom' (z <= 0) or 'top' (z >= 0)."""
    part = Part(app, K, f"{NAME}_{half}")
    part.add_parameters(PARAMS, v)
    XY = lambda a, b: (a, b, 0.0)                         # seam plane z = 0
    away = K["kNegativeExtentDirection"] if half == "bottom" else K["kPositiveExtentDirection"]
    toward = K["kPositiveExtentDirection"] if half == "bottom" else K["kNegativeExtentDirection"]
    CUT, JOIN = K["kCutOperation"], K["kJoinOperation"]

    # --- block: from the seam outward ---
    sk = Sketch(part, part.xy, "Block_sketch", XY)
    sk.rect(-v["block_L"] / 2, -v["y_back"], v["block_L"], v["y_back"] + v["y_front"], 0.0,
            {"a0": "-block_L/2", "b0": "-y_back", "w": "block_L",
             "h": "y_back + y_front", "r": "0 mm"})
    f = part.extrude(sk.sk, JOIN, "Block", dist="block_H/2", directions=[away])
    zmin, zmax = part.zrange_mm()
    if (half == "bottom" and zmax > 1e-6) or (half == "top" and zmin < -1e-6):
        f.Delete(True)                                    # XY normal opposite; keep sketch
        f = part.extrude(sk.sk, JOIN, "Block", dist="block_H/2", directions=[toward])
        away, toward = toward, away

    # --- cavity pocket ---
    sk = Sketch(part, part.xy, "Cavity_sketch", XY)
    sk.rect(-v["cav_L"] / 2, -v["cav_W"] / 2, v["cav_L"], v["cav_W"], v["cav_r"],
            {"a0": "-cav_L/2", "b0": "-cav_W/2", "w": "cav_L", "h": "cav_W", "r": "cav_r"})
    part.extrude(sk.sk, CUT, "Cavity_pocket", dist="cav_H/2", directions=[away, toward])

    if half == "bottom":
        # --- chip tunnels (start ovl inside the cavity so the cut opens cleanly) ---
        sk = Sketch(part, part.xy, "Chip_tunnels_sketch", XY)
        for i in range(1, N_Q + 1):
            sk.rect(v[f"q{i}_x"] - v["tunnel_W"] / 2, -(v["cav_W"] / 2 + v["tunnel_L"]),
                    v["tunnel_W"], v["tunnel_L"] + v["ovl"], v["tunnel_r"],
                    {"a0": f"q{i}_x - tunnel_W/2", "b0": "-(cav_W/2 + tunnel_L)",
                     "w": "tunnel_W", "h": "tunnel_L + ovl", "r": "tunnel_r"})
        part.extrude(sk.sk, CUT, "Chip_tunnels", dist="chip_T", directions=[away, toward])
    else:
        # --- chip clearance pockets ---
        sk = Sketch(part, part.xy, "Chip_clearance_sketch", XY)
        for i in range(1, N_Q + 1):
            sk.rect(v[f"q{i}_x"] - v["tunnel_W"] / 2, -(v["cav_W"] / 2 + v["top_pocket_L"]),
                    v["tunnel_W"], v["top_pocket_L"] + v["ovl"], v["tunnel_r"],
                    {"a0": f"q{i}_x - tunnel_W/2", "b0": "-(cav_W/2 + top_pocket_L)",
                     "w": "tunnel_W", "h": "top_pocket_L + ovl", "r": "tunnel_r"})
        part.extrude(sk.sk, CUT, "Chip_clearance", dist="top_pocket_D", directions=[away, toward])

        # --- drive bores: seam → top face, centered over each tunnel ---
        sk = Sketch(part, part.xy, "Drive_bores_sketch", XY)
        for i in range(1, N_Q + 1):
            sk.circle(v[f"q{i}_x"], -(v["cav_W"] / 2 + v["drive_dy"]), v["drive_dia"],
                      {"a": f"q{i}_x", "b": "-(cav_W/2 + drive_dy)", "d": "drive_dia"})
        part.extrude(sk.sk, CUT, "Drive_bores", through_all=True, directions=[away, toward])

    # --- readout bores in this half: from the +y face into the cavity ---
    mine = [(xn, zn) for xn, zn in READOUTS if (v[zn] < 0) == (half == "bottom")]
    if mine:
        wp = part.xz_offset_plane(v["y_front"], "y_front", "RO_face_plane")
        XZ = lambda a, b: (a, v["y_front"], b)
        sk = Sketch(part, wp, "Readout_bores_sketch", XZ)
        for xn, zn in mine:
            sk.circle(v[xn], v[zn], v["ro_dia"], {"a": xn, "b": zn, "d": "ro_dia"})
        part.extrude(sk.sk, CUT, "Readout_bores", dist="ro_port_len + ovl")

    # --- checks ---
    vol, exp = part.volume_mm3(), EXPECTED[half]
    status = "OK" if math.isclose(vol, exp, rel_tol=1e-4) else "MISMATCH"
    print(f"[{half}] metal volume {vol:.2f} mm^3 (expected {exp:.2f}) {status}")
    for w in part.warnings:
        print(f"[{half}] warn: {w}")
    return part


# %% ---------------------------------------------------------------------------
# 5. SAVE, ASSEMBLE, EXPORT
# -----------------------------------------------------------------------------
def close_if_open(app, path):
    """Close an open copy of `path` so it can be overwritten. Never fatal."""
    target = str(path.resolve()).lower()
    try:
        docs = list(app.Documents)              # enumerate; Item(i) can throw E_INVALIDARG
    except Exception as e:
        print(f"[inv] could not list open documents ({e}); skipping close")
        return
    for d in docs:
        try:
            name = d.FullFileName
            if name and str(Path(name).resolve()).lower() == target:
                d.Close(True)
                print(f"[inv] closed open copy of {path.name}")
        except Exception as e:
            print(f"[inv] skipped a document while closing ({e})")


def backup_existing(paths):
    existing = [p for p in paths if p.exists()]
    if not existing:
        return
    dest = OUT_DIR / "_previous" / datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    for p in existing:
        shutil.copy2(p, dest / p.name)
    print(f"[save] backed up {len(existing)} file(s) to {dest}")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = {
        "bottom": OUT_DIR / f"{NAME}_bottom.ipt",
        "top":    OUT_DIR / f"{NAME}_top.ipt",
        "iam":    OUT_DIR / f"{NAME}.iam",
        "stp":    OUT_DIR / f"{NAME}.stp",
    }
    app = connect_inventor()
    K = load_constants()
    for p in paths.values():
        close_if_open(app, p)
    backup_existing(list(paths.values()))

    for half in ("bottom", "top"):
        part = build_half(app, K, half, VALS)
        part.doc.SaveAs(str(paths[half]), False)
        print(f"[save] {paths[half].name}")

    asm_type = K["kAssemblyDocumentObject"]
    try:
        tmpl = app.FileManager.GetTemplateFile(asm_type, K["kMetricSystemOfMeasure"])
    except Exception:
        tmpl = app.FileManager.GetTemplateFile(asm_type)
    asm = app.Documents.Add(asm_type, tmpl, True)
    for half in ("bottom", "top"):
        occ = asm.ComponentDefinition.Occurrences.Add(str(paths[half]),
                                                      app.TransientGeometry.CreateMatrix())
        occ.Grounded = True                     # both parts share the global frame
    asm.SaveAs(str(paths["iam"]), False)
    print(f"[save] {paths['iam'].name}")

    if EXPORT_STEP:
        asm.SaveAs(str(paths["stp"]), True)     # save copy as STEP (AP214)
        print(f"[save] {paths['stp'].name}")

    with open(OUT_DIR / f"{NAME}_params.json", "w") as fh:
        json.dump({"units": "mm", "values": VALS,
                   "expressions": {n: e for n, e, _ in PARAMS}}, fh, indent=2)
    print("[done]")


if __name__ == "__main__":
    main()
