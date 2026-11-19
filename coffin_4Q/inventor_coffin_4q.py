# -*- coding: utf-8 -*-
"""
inventor_coffin_4q.py
=====================
Builds the 4-transmon "coffin" cavity as two machinable halves in Autodesk
Inventor via COM, then exports the assembly to STEP for the HFSS pipeline
(same flow as SNAIL_coffin_cavity: Inventor → .stp → HFSS bounding-box subtract).

Starting point = the old SNAIL coffin cavity (dimensions read from its STEP):
    cavity 32 x 9 x 32 mm, r = 2 mm vertical corners, split at z = 0  (old design)
    chip pocket 7.5 w x 0.43 d x 30 l (bottom), clearance pocket 3.86 l (top)
    SMA bores 2.946 mm dia, 8.75 mm long through the +y wall
Changes:
    cavity 50 mm long, 4 chip tunnels on the -y wall, 2 readout bores on the
    +y wall, 4 drive bores from the top face landing on each chip tunnel.
    The chip is held by a clamp at its back end (clamp to be designed later) and passes through
    the tunnel into the cavity. Near the cavity it sits between two clearance pockets, one in each
    half (2.18 mm deep, 10 mm long), so its pads have ~2.2 mm of vacuum above and below.

Coordinates (mm): origin at cavity center, seam plane z = 0,
    x = cavity length, y = cavity width (+y readout side, -y chip side), z = height.
    bottom half: z <= 0  (cavity pocket, chip tunnels, readout ports with z < 0)
    top half:    z >= 0  (cavity pocket, chip clearance pockets, drive bores, ports z > 0)

Hardware (imperial):
    clamp screws  4-40 SHCS ring around cavity + tunnels: counterbored #30 clearance
                  through the top half, 4-40 UNC-2B tapped blind into the bottom half
    SMA ports     2-hole flange jacks, 2-56 UNC-2B tapped pairs at sma_hole_spacing
                  (front face: across each readout port; top face: at each drive port, pair rotated
                  45 deg from y so the screw nearest the cavity clears its wall)
    Hole features carry real thread callouts; if Inventor rejects the threaded-hole
    API call, plain tap-drill holes are cut instead (named with the thread) + warning.

Every dimension is an Inventor user parameter (fx table) and sketches carry
driving dimensions tied to those parameters, so the machine shop can edit
the .ipt directly. NOTE: rerunning this script rebuilds from PARAMS below and
overwrites the parts (old files are backed up to inventor_files/_previous/).

Exports: coffin_4Q.stp (machinable, with all screw / flange holes) and coffin_4Q_hfss.stp
(same parts with the hardware features suppressed; the HFSS notebook imports this one, so the
simulated vacuum is exactly the RF geometry).

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
EXPORT_STEP     = True    # machinable assembly (all hardware)  -> coffin_4Q.stp
EXPORT_HFSS     = True    # RF-only assembly (hardware suppressed) -> coffin_4Q_hfss.stp (used by the notebook)

# (name, expression, comment). Numbers are mm. Expressions may reference earlier
# names, and are written to Inventor verbatim, so keep to + - * / ( ), numbers and
# min(a; b) / max(a; b) (Inventor syntax: arguments separated by ';').
PARAMS = [
    # --- cavity (coffin) ---
    ("cav_L",        60.0,   "cavity length (x)"),
    ("cav_W",        8.0,    "cavity width (y)"),
    ("cav_H",        21.86,  "cavity height (z), split evenly at the seam; TE101 7.30 GHz bare -> ~7.25 GHz with chips (was 20.27 for 7.8)"),
    ("cav_r",        2.0,    "vertical corner radius (>= end mill radius)"),
    # --- walls / block ---
    ("wall_x",       10.0,   "wall beyond cavity ends (x); room for clamp-screw counterbores"),
    ("wall_z",       5.0,    "wall above/below cavity (z)"),
    ("wall_back",    10.0,   "wall behind the end of the chip tunnels (-y); room for clamp screws"),
    # --- chip tunnels (bottom half, -y side) ---
    ("chip_T",       0.5,   "chip tunnel depth = chip thickness"),
    ("tunnel_W",     3.45,    "chip tunnel width"),
    ("tunnel_L",     33.0,   "chip tunnel length from cavity wall: 32 mm chip at ~1.9-2.3 mm protrude + ~3 mm behind it (was 18.63)"),
    ("tunnel_r",     0.0,    "tunnel corner radius (0 = sharp; keep <= ovl)"),
    # --- transmon chip (held by a clamp at its back end; read by the HFSS notebook and the clamp design) ---
    ("chip_W",       2.45,   "transmon chip width (x)"),
    ("chip_L",       32.0,   "transmon chip length (y), full real chip (was 16.63)"),
    ("chip_thk",     0.43,   "transmon chip thickness (sapphire); chip bottom face at the tunnel floor height"),
    # qubit spacing: even spacing (L/4 -> qubits at +-L/8, +-3L/8) unless that exceeds q_pitch_max,
    # in which case the qubits are packed inward at q_pitch_max (outer qubits sit in stronger TE101 field)
    ("q_pitch_max",  10.5,   "max center-to-center qubit spacing"),
    ("q_pitch",      "min(q_pitch_max; cav_L/4)", "qubit spacing = smaller of q_pitch_max and L/4"),
    ("q1_x",         "-3*q_pitch/2", "transmon 1 x position"),
    ("q2_x",         "-q_pitch/2",   "transmon 2 x position"),
    ("q3_x",         "q_pitch/2",    "transmon 3 x position"),
    ("q4_x",         "3*q_pitch/2",  "transmon 4 x position"),
    # --- chip clearance pockets (top half, above chips near the cavity) ---
    ("top_pocket_L", 10,   "clearance pocket length from cavity wall"),
    ("top_pocket_D", 2.18,   "clearance pocket depth above the seam (was 2.43; bottom pocket follows)"),
    # --- chip clearance pockets (bottom half, below the tunnel floor; identical to the top ones) ---
    ("bot_pocket_L", "top_pocket_L", "bottom clearance pocket length from cavity wall"),
    ("bot_pocket_D", "top_pocket_D", "bottom clearance pocket depth below the tunnel floor"),
    # --- drive bores (top half, from top face down onto each chip tunnel) ---
    ("drive_dia",    2.946,  "drive bore diameter"),
    # drive bore center distance from the cavity wall (-y), per qubit. The inner chips protrude 0.4 mm less, so their
    # pads sit 0.4 mm further back; outer/inner bores differ by 0.4 mm too -> equal pad-to-pin distance (2.235 mm).
    # Both moved back 0.2 mm with the chips (protrude 2.5/2.1 -> 2.3/1.9 for the 7.25 GHz readout).
    ("drive_dy_outer", 6.2,  "drive bore center from cavity wall, Q1 and Q4 (was 6.0)"),
    ("drive_dy_inner", 6.6,  "drive bore center from cavity wall, Q2 and Q3 (was 6.4)"),
    # --- readout bores (+y wall) ---
    ("ro_dia",       2.946,  "readout bore diameter"),
    ("ro_port_len",  8.75,   "readout bore length = +y wall thickness"),
    ("ro1_x",        0, "readout 1 x"),
    ("ro1_z",        -5, "readout 1 z (<0 -> bottom half)"),
    ("ro2_x",        0,  "readout 2 x"),
    ("ro2_z",       5,  "readout 2 z (>0 -> top half)"),
    # --- clamp screws: 4-40 socket head cap screws (counterbored top half, tapped bottom half) ---
    ("clamp_clear_dia",   3.264, "4-40 clearance, #30 drill (0.1285 in)"),
    ("clamp_cbore_dia",   5.556, "4-40 SHCS counterbore, 7/32 in (head 0.183 in)"),
    ("clamp_cbore_depth", 3.2,   "counterbore depth (head 0.112 in = 2.84 mm + margin)"),
    ("clamp_tap_depth",   10.0,  "4-40 tap-drill depth into the bottom half, from the seam"),
    ("clamp_thread_depth", 8.0,  "4-40 full-thread depth"),
    ("clamp_tap_drill",   2.261, "4-40 tap drill #43 (fallback hole size)"),
    # --- SMA 2-hole flange jacks: 2-56 screws ---
    ("sma_hole_spacing",  10.795, "2-hole flange screw spacing, 0.425 in: CHECK against the connector datasheet"),
    ("sma_tap_depth",     6.3,   "2-56 tap-drill depth"),
    ("sma_thread_depth",  5.5,   "2-56 full-thread depth"),
    ("sma_tap_drill",     1.778, "2-56 tap drill #50 (fallback hole size)"),
    ("sma_flange_T",      1.57,  "SMA flange thickness (for screw length only): CHECK datasheet"),
    # drive flanges are rotated 45 deg about their pin so the screw nearest the cavity clears its -y wall
    # (needed from drive_dy_outer = 6.0; 35 deg cleared 6.5 only). cos(45 deg) = sin(45 deg) = 0.7071.
    ("drive_flange_dy",   "sma_hole_spacing/2 * 0.7071", "drive flange screw offset along y from the pin (45 deg rotation)"),
    ("drive_flange_dx",   "sma_hole_spacing/2 * 0.7071", "drive flange screw offset along x from the pin (45 deg rotation)"),
    ("hw_min_wall",       1.0,   "min copper between a screw hole and any other feature / edge"),
    # --- construction ---
    ("ovl",          0.5,    "cut overlap into the cavity void (clean booleans)"),
    # --- derived (update automatically when the above change) ---
    ("block_L",      "cav_L + 2*wall_x",                 "block length (x)"),
    ("block_H",      "cav_H + 2*wall_z",                 "block height (z), both halves"),
    ("y_front",      "cav_W/2 + ro_port_len",            "+y block face"),
    ("y_back",       "cav_W/2 + tunnel_L + wall_back",   "-y block face (distance)"),
]

N_Q = 4
DRIVE_DY = {1: "drive_dy_outer", 2: "drive_dy_inner", 3: "drive_dy_inner", 4: "drive_dy_outer"}   # qubit -> param
READOUTS = [("ro1_x", "ro1_z"), ("ro2_x", "ro2_z")]

THREAD_TYPE  = "ANSI Unified Screw Threads"     # Inventor thread table name
CLAMP_THREAD = ("4-40 UNC", "2B")
SMA_THREAD   = ("2-56 UNC", "2B")
DRILL_TIP_DEG = 118.0                           # Inventor's default drill point


# %% ---------------------------------------------------------------------------
# 1. PURE-PYTHON GEOMETRY: evaluate, validate, expected volumes
# -----------------------------------------------------------------------------
def evaluate(params):
    v = {}
    for name, expr, _ in params:
        v[name] = float(expr) if isinstance(expr, (int, float)) else float(
            eval(expr.replace(";", ","), {"__builtins__": {}, "min": min, "max": max}, dict(v)))
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
    dys = {v[DRIVE_DY[i]] for i in range(1, N_Q + 1)}
    if min(dys) - v["drive_dia"] / 2 <= 0:
        errs.append("drive bores break into the cavity wall (drive_dy <= drive_dia/2)")
    if v["drive_dia"] >= v["tunnel_W"]:
        errs.append("drive bores wider than the chip tunnels")
    if max(dys) + v["drive_dia"] / 2 >= v["tunnel_L"]:
        errs.append("drive bores land beyond the end of the chip tunnels")
    if v["tunnel_r"] > v["ovl"]:
        errs.append("tunnel_r > ovl (volume check assumes otherwise)")
    if v["chip_W"] >= v["tunnel_W"]:
        errs.append("chip is not narrower than the tunnel")
    if v["chip_thk"] > v["chip_T"]:
        errs.append("chip thicker than the tunnel height")
    if v["chip_L"] > v["tunnel_L"] + v["cav_W"]:
        errs.append("chip longer than tunnel + cavity")
    for side in ("top", "bot"):
        if v[f"{side}_pocket_L"] > v["tunnel_L"]:
            errs.append(f"{side} clearance pocket runs past the end of the tunnel")
    if v["chip_T"] + v["bot_pocket_D"] >= v["block_H"] / 2 - v["hw_min_wall"]:
        errs.append("tunnel + bottom pocket too deep for the bottom half")
    if v["top_pocket_D"] >= v["block_H"] / 2 - v["hw_min_wall"]:
        errs.append("top pocket too deep for the top half")
    if max(dys) + v["drive_dia"] / 2 > v["top_pocket_L"]:
        errs.append("drive bore lands outside the top clearance pocket")
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
    bot_pocket = v["tunnel_W"] * v["bot_pocket_L"] * v["bot_pocket_D"] - 2 * rc * v["bot_pocket_D"]
    pocket = v["tunnel_W"] * v["top_pocket_L"] * v["top_pocket_D"] - 2 * rc * v["top_pocket_D"]
    ro = math.pi * (v["ro_dia"] / 2) ** 2 * v["ro_port_len"]
    rd = v["drive_dia"] / 2
    drive = 0.0                                                    # all N_Q drive bores
    for i in range(1, N_Q + 1):
        yd = -(v["cav_W"] / 2 + v[DRIVE_DY[i]])
        shared = circle_rect_area(0.0, yd, rd, -v["tunnel_W"] / 2, v["tunnel_W"] / 2,
                                  -(v["cav_W"] / 2 + v["top_pocket_L"]), -v["cav_W"] / 2)
        drive += math.pi * rd ** 2 * hh - shared * v["top_pocket_D"]   # already cut by the pocket
    n_ro_bot = sum(v[z] < 0 for _, z in READOUTS)
    n_ro_top = len(READOUTS) - n_ro_bot
    return {
        "bottom": block - cav - N_Q * (tunnel + bot_pocket) - n_ro_bot * ro,
        "top":    block - cav - N_Q * pocket - drive - n_ro_top * ro,
    }


def _ev(expr, v):
    return float(eval(expr.replace(";", ","), {"__builtins__": {}, "min": min, "max": max}, dict(v)))


def hardware_layout(v):
    """Hole centers (mm) + the Inventor expressions that position them.

    clamp: ring of 4-40 screws on a front row, a back row (behind the tunnels) and the two end columns.
    sma_front: 2-56 pairs across each readout bore on the +y face  (a = x, b = z).
    sma_top:   2-56 pairs along y at each drive bore on the top face (a = x, b = y).
    """
    yf = "(cav_W/2 + y_front)/2"                          # front row: middle of the +y wall
    yb = "-(cav_W/2 + tunnel_L + wall_back/2)"            # back row: middle of the back wall
    xe = "(cav_L/2 + wall_x/2)"                           # end columns: middle of the end walls
    clamp = []
    for ex in (f"-{xe}",  "-cav_L/5", "cav_L/5", xe):   # front row (gap at the RO ports)
        clamp.append((ex, yf))
    for k in range(-1, 2):                                                       # back row, 7 evenly spaced
        clamp.append((f"{k}*{xe}" if k else "0", yb))
    for k in range(1, 2):                                                          # end columns, between the rows
        ey = f"({yb}) + {k}*(({yf}) - ({yb}))/2"
        clamp += [(f"-{xe}", ey), (xe, ey)]
    half = "sma_hole_spacing/2"
    sma_front = [(f"{xn} + {s}{half}", zn) for xn, zn in READOUTS for s in ("-", "")]
    sma_top = [(f"q{i}_x {sx} drive_flange_dx", f"-(cav_W/2 + {DRIVE_DY[i]}) {sy} drive_flange_dy")
               for i in range(1, N_Q + 1) for sx, sy in (("-", "-"), ("+", "+"))]   # same rotation for all four
    num = lambda pts: [(_ev(a, v), _ev(b, v), a, b) for a, b in pts]
    return {"clamp": num(clamp), "sma_front": num(sma_front), "sma_top": num(sma_top)}


def _rect_dist(x, y, x0, x1, y0, y1):
    """Distance from a point to an axis-aligned rectangle (0 inside)."""
    dx = max(x0 - x, 0.0, x - x1)
    dy = max(y0 - y, 0.0, y - y1)
    return math.hypot(dx, dy)


def validate_hardware(v, hw):
    errs, m = [], v["hw_min_wall"]
    r_cl, r_cb = v["clamp_clear_dia"] / 2, v["clamp_cbore_dia"] / 2
    r_st = v["sma_tap_drill"] / 2
    bx0, bx1, by0, by1 = -v["block_L"] / 2, v["block_L"] / 2, -v["y_back"], v["y_front"]
    cav = (-v["cav_L"] / 2, v["cav_L"] / 2, -v["cav_W"] / 2, v["cav_W"] / 2)
    tun = [(v[f"q{i}_x"] - v["tunnel_W"] / 2, v[f"q{i}_x"] + v["tunnel_W"] / 2,
            -(v["cav_W"] / 2 + v["tunnel_L"]), -v["cav_W"] / 2) for i in range(1, N_Q + 1)]
    pock = [(a, b, -(v["cav_W"] / 2 + v[f"{s}_pocket_L"]), -v["cav_W"] / 2)
            for a, b, _, _ in tun for s in ("top", "bot")]
    drives = [(v[f"q{i}_x"], -(v["cav_W"] / 2 + v[DRIVE_DY[i]])) for i in range(1, N_Q + 1)]
    r_dr, r_ro = v["drive_dia"] / 2, v["ro_dia"] / 2
    ro = [(v[xn] - r_ro, v[xn] + r_ro, v["cav_W"] / 2, v["y_front"]) for xn, _ in READOUTS]
    tip = lambda r: r / math.tan(math.radians(DRILL_TIP_DEG / 2))
    front_len = v["sma_tap_depth"] + tip(r_st)
    sma_f = [(x - r_st, x + r_st, v["y_front"] - front_len, v["y_front"]) for x, _, _, _ in hw["sma_front"]]

    for x, y, *_ in hw["clamp"]:
        tag = f"clamp screw at ({x:.2f}, {y:.2f})"
        if min(x - bx0, bx1 - x, y - by0, by1 - y) < r_cb + m:
            errs.append(f"{tag}: counterbore too close to the block edge")
        for name, rects in (("cavity", [cav]), ("chip tunnel", tun), ("clearance pocket", pock),
                            ("readout bore", ro), ("SMA front screw", sma_f)):
            for rc in rects:
                if _rect_dist(x, y, *rc) < r_cl + m:
                    errs.append(f"{tag}: too close to a {name}")
        for xd, yd in drives:
            if math.hypot(x - xd, y - yd) < r_cl + r_dr + m:
                errs.append(f"{tag}: too close to a drive bore")
        for xs, ys, *_ in hw["sma_top"]:
            if math.hypot(x - xs, y - ys) < r_cb + r_st + m:
                errs.append(f"{tag}: too close to a drive SMA screw")
    pts = [(x, y) for x, y, *_ in hw["clamp"]]
    for i, (x1, y1) in enumerate(pts):
        for x2, y2 in pts[i + 1:]:
            if math.hypot(x1 - x2, y1 - y2) < 2 * r_cb + m:
                errs.append(f"clamp screws at ({x1:.1f},{y1:.1f}) and ({x2:.1f},{y2:.1f}) overlap")

    # drive SMA screws (top face, blind): may only sit over the cavity / pocket if they stop short of it
    z_bot = v["block_H"] / 2 - v["sma_tap_depth"] - tip(r_st)
    for x, y, *_ in hw["sma_top"]:
        tag = f"drive SMA screw at ({x:.2f}, {y:.2f})"
        if min(x - bx0, bx1 - x, y - by0, by1 - y) < r_st + m:
            errs.append(f"{tag}: too close to the block edge")
        if _rect_dist(x, y, *cav) < r_st + m and z_bot < v["cav_H"] / 2 + m:
            errs.append(f"{tag}: breaks into / too close to the cavity")
        if any(_rect_dist(x, y, *rc) < r_st + m for rc in pock) and z_bot < v["top_pocket_D"] + m:
            errs.append(f"{tag}: breaks into / too close to a top clearance pocket")
        for xd, yd in drives:
            if math.hypot(x - xd, y - yd) < r_st + r_dr + m:
                errs.append(f"{tag}: too close to a drive bore")
    tops = [(x, y) for x, y, *_ in hw["sma_top"]]
    for i, (x1, y1) in enumerate(tops):
        for x2, y2 in tops[i + 1:]:
            if math.hypot(x1 - x2, y1 - y2) < 2 * r_st + m:
                errs.append(f"drive SMA screws at ({x1:.1f},{y1:.1f}) and ({x2:.1f},{y2:.1f}) overlap")

    # readout SMA screws (front face, blind along -y): stay out of the cavity, the other port, the halves' seam
    for x, z, *_ in hw["sma_front"]:
        tag = f"readout SMA screw at (x={x:.2f}, z={z:.2f})"
        if v["y_front"] - front_len < v["cav_W"] / 2 + m:
            errs.append(f"{tag}: reaches the cavity (sma_tap_depth too long for the front wall)")
        if abs(z) - r_st < m:
            errs.append(f"{tag}: too close to the seam (would split between the halves)")
        if abs(z) + r_st > v["block_H"] / 2 - m:
            errs.append(f"{tag}: too close to the top/bottom face")
        if min(x - bx0, bx1 - x) < r_st + m:
            errs.append(f"{tag}: too close to the block end")
        for xn, zn in READOUTS:
            if math.hypot(x - v[xn], z - v[zn]) < r_st + r_ro + m:
                errs.append(f"{tag}: too close to a readout bore")
    if errs:
        raise ValueError("Bad hardware layout:\n  - " + "\n  - ".join(dict.fromkeys(errs)))


def screw_lengths(v):
    """Standard inch screw lengths that fit the holes (engagement 1.5 d .. thread depth - 0.5 mm)."""
    std = [3 / 16, 1 / 4, 5 / 16, 3 / 8, 7 / 16, 1 / 2, 5 / 8, 3 / 4, 7 / 8, 1.0, 1.25]
    def pick(grip, d_major, thread_depth):
        lo, hi = grip + 1.5 * d_major, grip + thread_depth - 0.5
        ok = [L for L in std if lo <= L * 25.4 <= hi]
        return (ok[-1], lo, hi) if ok else (None, lo, hi)
    clamp = pick(v["block_H"] / 2 - v["clamp_cbore_depth"], 2.845, v["clamp_thread_depth"])   # 4-40 major 0.112 in
    sma = pick(v["sma_flange_T"], 2.184, v["sma_thread_depth"])                              # 2-56 major 0.086 in
    return {"clamp 4-40 SHCS": clamp, "SMA flange 2-56": sma}


VALS = evaluate(PARAMS)
validate(VALS)
HW = hardware_layout(VALS)
validate_hardware(VALS, HW)
EXPECTED = expected_volumes(VALS)
print(f"[geom] block {VALS['block_L']:.2f} x {VALS['y_front'] + VALS['y_back']:.2f} x "
      f"{VALS['block_H']:.2f} mm | expected metal: bottom {EXPECTED['bottom']:.1f}, "
      f"top {EXPECTED['top']:.1f} mm^3")
print(f"[hw] {len(HW['clamp'])} x 4-40 clamp screws, {len(HW['sma_front'])} + {len(HW['sma_top'])} x 2-56 SMA screw holes")
for _k, (_L, _lo, _hi) in screw_lengths(VALS).items():
    print(f"[hw] {_k}: " + (f'{_L:g}" long' if _L else "NO standard length fits") +
          f"  (fits {_lo:.1f}-{_hi:.1f} mm)")


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
        self.hw_features = []          # screw / flange holes: suppressed for the HFSS export

    # ---------------- parameters ----------------
    def add_parameters(self, params, vals):
        up = self.cd.Parameters.UserParameters
        for name, expr, comment in params:
            e = f"{expr} mm" if isinstance(expr, (int, float)) else expr
            try:
                p = up.AddByExpression(name, e, "mm")
            except Exception as err:                      # e.g. Inventor rejects min()/max() syntax
                p = up.AddByExpression(name, f"{vals[name]} mm", "mm")
                self.warnings.append(f"param {name}: expression {e!r} rejected ({err}); "
                                     f"written as the value {vals[name]} mm")
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

    def xy_offset_plane(self, z_mm, expr, name):
        """Plane parallel to XY at model z = z_mm (sign checked)."""
        for e in (expr, f"-({expr})"):
            wp = self.cd.WorkPlanes.AddByPlaneAndOffset(self.xy, e)
            if math.isclose(wp.Plane.RootPoint.Z * 10.0, z_mm, abs_tol=1e-6):
                wp.Name, wp.Visible = name, False
                return wp
            wp.Delete()
        raise RuntimeError(f"could not place work plane at z = {z_mm}")

    # ---------------- hole features ----------------
    def holes(self, plane, embed, pts, name, kind, spec, directions=None):
        """Hole features at pts [(a, b, expr_a, expr_b)] on `plane` (embed(a, b) -> model xyz).

        kind "cbore_thru": spec = (clear_dia, cbore_dia, cbore_depth) expressions; through all.
        kind "tapped":     spec = (designation, class, drill_depth, thread_depth, tap_drill) expressions.
        Tries each drill direction and keeps the one that removes metal. If the hole API fails, falls back
        to plain cut extrudes (tap-drill size for tapped holes) named with the thread, and warns.
        """
        K = self.K
        sk = Sketch(self, plane, name + "_sketch", embed)
        sp = [sk.point(a, b, ea, eb) for a, b, ea, eb in pts]
        hf = self.cd.Features.HoleFeatures
        directions = directions or [K["kNegativeExtentDirection"], K["kPositiveExtentDirection"]]
        last = None
        for d in directions:
            v0 = self.volume_mm3()
            try:
                oc = self.app.TransientObjects.CreateObjectCollection()
                for p_ in sp:
                    oc.Add(p_)
                placement = hf.CreateSketchPlacementDefinition(oc)
                if kind == "cbore_thru":
                    clear, cb_d, cb_h = spec
                    f = hf.AddCBoreByThroughAllExtent(placement, clear, cb_d, cb_h, d)
                else:
                    desig, cls, depth, tdepth, _ = spec
                    tap = hf.CreateTapInfo(True, THREAD_TYPE, desig, cls, False, tdepth)
                    f = hf.AddDrilledByDistanceExtent(placement, tap, depth, d)
            except Exception as e:
                last = e
                continue
            if math.isclose(self.volume_mm3(), v0, rel_tol=1e-9):
                f.Delete(True)                                # drilled into empty space
                continue
            f.Name = name
            self.hw_features.append(f)
            print(f"  [{self.name}] {name}: ok ({len(pts)} holes)")
            return f
        # ---- fallback: plain holes as cut extrudes ----
        self.warnings.append(f"{name}: hole feature failed ({last}); cut plain holes instead "
                             + ("(tap drill size; tap per callout)" if kind == "tapped" else ""))
        CUT = K["kCutOperation"]
        if kind == "cbore_thru":
            clear, cb_d, cb_h = spec
            sk1 = Sketch(self, plane, name + "_cbore_sketch", embed)
            for a, b, ea, eb in pts:
                sk1.circle(a, b, VALS[cb_d], {"a": ea, "b": eb, "d": cb_d})
            self.hw_features.append(self.extrude(sk1.sk, CUT, name + "_cbore", dist=cb_h))
            sk2 = Sketch(self, plane, name + "_clear_sketch", embed)
            for a, b, ea, eb in pts:
                sk2.circle(a, b, VALS[clear], {"a": ea, "b": eb, "d": clear})
            f = self.extrude(sk2.sk, CUT, name + "_clearance", through_all=True)
            self.hw_features.append(f)
            return f
        desig, cls, depth, tdepth, drill = spec
        sk1 = Sketch(self, plane, name + "_tapdrill_sketch", embed)
        for a, b, ea, eb in pts:
            sk1.circle(a, b, VALS[drill], {"a": ea, "b": eb, "d": drill})
        f = self.extrude(sk1.sk, CUT, f"{name}_TAP_{desig.replace(' ', '_')}", dist=depth)
        self.hw_features.append(f)
        return f

    def set_hardware_suppressed(self, flag):
        """Suppress (True) / restore (False) every screw and flange hole feature."""
        for f in self.hw_features:
            f.Suppressed = flag
        self.doc.Update()

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

    def point(self, a, b, ea, eb):
        """Hole-center sketch point at (a, b) mm, positioned by driving dims from the origin."""
        sp = self.sk.SketchPoints.Add(self.pt(a, b), True)
        self._pos(sp, "a", a, ea, self.pt(a / 2, b + 1.5))
        self._pos(sp, "b", b, eb, self.pt(a + 1.5, b / 2))
        return sp

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

        # --- bottom chip clearance pockets: from the tunnel floor (z = -chip_T) down, open into the cavity ---
        floor = part.xy_offset_plane(-v["chip_T"], "chip_T", "Tunnel_floor_plane")
        FLOOR = lambda a, b: (a, b, -v["chip_T"])
        sk = Sketch(part, floor, "Chip_clearance_bottom_sketch", FLOOR)
        for i in range(1, N_Q + 1):
            sk.rect(v[f"q{i}_x"] - v["tunnel_W"] / 2, -(v["cav_W"] / 2 + v["bot_pocket_L"]),
                    v["tunnel_W"], v["bot_pocket_L"] + v["ovl"], v["tunnel_r"],
                    {"a0": f"q{i}_x - tunnel_W/2", "b0": "-(cav_W/2 + bot_pocket_L)",
                     "w": "tunnel_W", "h": "bot_pocket_L + ovl", "r": "tunnel_r"})
        part.extrude(sk.sk, CUT, "Chip_clearance_bottom", dist="bot_pocket_D", directions=[away, toward])
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
            sk.circle(v[f"q{i}_x"], -(v["cav_W"] / 2 + v[DRIVE_DY[i]]), v["drive_dia"],
                      {"a": f"q{i}_x", "b": f"-(cav_W/2 + {DRIVE_DY[i]})", "d": "drive_dia"})
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

    # --- checks (RF features only, before hardware) ---
    vol, exp = part.volume_mm3(), EXPECTED[half]
    status = "OK" if math.isclose(vol, exp, rel_tol=1e-4) else "MISMATCH"
    print(f"[{half}] metal volume {vol:.2f} mm^3 (expected {exp:.2f}) {status}")

    # --- hardware ---
    hw = HW
    if half == "top":
        top = part.xy_offset_plane(v["block_H"] / 2, "block_H/2", "Top_face_plane")
        TOPF = lambda a, b: (a, b, v["block_H"] / 2)
        part.holes(top, TOPF, hw["clamp"], "Clamp_cbore_4-40", "cbore_thru",
                   ("clamp_clear_dia", "clamp_cbore_dia", "clamp_cbore_depth"))
        part.holes(top, TOPF, hw["sma_top"], "Drive_SMA_2-56", "tapped",
                   (SMA_THREAD[0], SMA_THREAD[1], "sma_tap_depth", "sma_thread_depth", "sma_tap_drill"))
    else:
        part.holes(part.xy, XY, hw["clamp"], "Clamp_tap_4-40", "tapped",
                   (CLAMP_THREAD[0], CLAMP_THREAD[1], "clamp_tap_depth", "clamp_thread_depth", "clamp_tap_drill"))
    mine_f = [p_ for p_ in hw["sma_front"] if (p_[1] < 0) == (half == "bottom")]
    if mine_f:
        wp = part.xz_offset_plane(v["y_front"], "y_front", "SMA_face_plane")
        XZ = lambda a, b: (a, v["y_front"], b)
        part.holes(wp, XZ, mine_f, "Readout_SMA_2-56", "tapped",
                   (SMA_THREAD[0], SMA_THREAD[1], "sma_tap_depth", "sma_thread_depth", "sma_tap_drill"))
    print(f"[{half}] hardware removed {vol - part.volume_mm3():.1f} mm^3")
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
        "hfss":   OUT_DIR / f"{NAME}_hfss.stp",
    }
    app = connect_inventor()
    K = load_constants()
    for p in paths.values():
        close_if_open(app, p)
    backup_existing(list(paths.values()))

    parts = {}
    for half in ("bottom", "top"):
        part = build_half(app, K, half, VALS)
        part.doc.SaveAs(str(paths[half]), False)
        parts[half] = part
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
        print(f"[save] {paths['stp'].name} (machinable, with hardware)")

    if EXPORT_HFSS:
        # RF-only model for HFSS: suppress the screw / flange holes, check the copper matches the
        # hardware-free geometry exactly, export, then restore (the saved .ipt files keep the holes).
        for half, part in parts.items():
            part.set_hardware_suppressed(True)
            vol, exp = part.volume_mm3(), EXPECTED[half]
            if not math.isclose(vol, exp, rel_tol=1e-4):
                for p_ in parts.values():
                    p_.set_hardware_suppressed(False)
                raise RuntimeError(f"[hfss] {half}: {vol:.2f} mm^3 with hardware suppressed, expected "
                                   f"{exp:.2f}: a hardware feature was not suppressed; HFSS STEP not written")
            print(f"[hfss] {half}: hardware suppressed, metal volume {vol:.2f} mm^3 = RF-only geometry OK")
        asm.Update()
        asm.SaveAs(str(paths["hfss"]), True)
        print(f"[save] {paths['hfss'].name} (HFSS: no screw / flange holes)")
        for part in parts.values():
            part.set_hardware_suppressed(False)
        asm.Update()

    with open(OUT_DIR / f"{NAME}_params.json", "w") as fh:
        json.dump({"units": "mm", "values": VALS,
                   "expressions": {n: e for n, e, _ in PARAMS}}, fh, indent=2)
    lengths = screw_lengths(VALS)
    with open(OUT_DIR / f"{NAME}_hardware.json", "w") as fh:
        json.dump({"units": "mm",
                   "clamp_4-40": {"count": len(HW["clamp"]), "xy": [p_[:2] for p_ in HW["clamp"]],
                                  "screw_length_in": lengths["clamp 4-40 SHCS"][0]},
                   "sma_2-56_front": {"count": len(HW["sma_front"]), "xz": [p_[:2] for p_ in HW["sma_front"]]},
                   "sma_2-56_top": {"count": len(HW["sma_top"]), "xy": [p_[:2] for p_ in HW["sma_top"]]},
                   "sma_screw_length_in": lengths["SMA flange 2-56"][0]}, fh, indent=2)
    print("[done]")


if __name__ == "__main__":
    main()
