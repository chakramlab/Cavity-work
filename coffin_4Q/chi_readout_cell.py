# %% chi to the readout mode for every qubit (pyEPR). Run after the EM_Cavity_with_Transmons eigenmode solve.
# Needs the usual setup cells (imports, paths, HFSS, helpers) and JUNCTIONS from add_transmons in this kernel.
READOUT_F_GHZ = 7.8      # readout mode = high-Q mode closest to this
Q_MIN = 1e3              # modes below this Q are drive-pin / port modes, never qubits or readout
FOCK_TRUNC = 5           # per-mode Fock levels for the numerical diagonalization (5 needed for alpha)
DESIGN_EPR = "EM_Cavity_with_Transmons"

# ---- pyEPR 0.8 compatibility patches (numpy 2 / pandas 2 / pint / QuTiP 5 / AEDT 2023.2); no-ops if applied ----
for alias, target in {"float": float, "int": int, "complex": complex, "bool": bool, "object": object,
                      "str": str, "float_": np.float64, "complex_": np.complex128,
                      "NaN": np.nan, "Inf": np.inf, "infty": np.inf, "product": np.prod,
                      "cumproduct": np.cumprod, "alltrue": np.all, "sometrue": np.any}.items():
    if alias not in np.__dict__:
        setattr(np, alias, target)
if not hasattr(pd.DataFrame, "append"):
    def _df_append(self, other, ignore_index=False, verify_integrity=False, sort=False):
        if isinstance(other, pd.Series):
            other = other.to_frame().T
        elif isinstance(other, dict):
            other = pd.DataFrame([other])
        elif isinstance(other, (list, tuple)):
            return pd.concat([self, *other], ignore_index=ignore_index, sort=sort)
        return pd.concat([self, other], ignore_index=ignore_index, sort=sort)
    pd.DataFrame.append = _df_append
if not hasattr(pd.Series, "append"):
    pd.Series.append = lambda self, o, ignore_index=False, verify_integrity=False: pd.concat(
        [self, *(o if isinstance(o, (list, tuple)) else [o])], ignore_index=ignore_index)
for cls in (pd.DataFrame, pd.Series):
    if not hasattr(cls, "iteritems"):
        cls.iteritems = cls.items
if not getattr(pd.DataFrame.drop, "_epr_compat", False):
    _df_drop = pd.DataFrame.drop

    def _drop_compat(self, labels=None, *args, **kwargs):
        if args:
            kwargs.setdefault("axis", args[0])
        return _df_drop(self, labels, **kwargs)
    _drop_compat._epr_compat = True
    pd.DataFrame.drop = _drop_compat

import importlib
import inspect
import pyEPR as epr
import pyEPR.core_distributed_analysis as _epr_cda
import pyEPR.calcs.back_box_numeric as _epr_bbn


class _VariationUreg:
    def __init__(self, ureg):
        self._ureg = ureg

    def __call__(self, s):
        return int(s) if str(s).strip().isdigit() else self._ureg(s)

    def __getattr__(self, name):
        return getattr(self._ureg, name)


if type(_epr_cda.ureg).__name__ != "_VariationUreg":
    _epr_cda.ureg = _VariationUreg(epr.ansys.ureg)
if not getattr(_epr_cda.set_property, "_epr_compat", False):
    _set_property = _epr_cda.set_property

    def _set_property_compat(*args, **kwargs):
        try:
            return _set_property(*args, **kwargs)
        except Exception as e:
            print(f"[epr] skipped HFSS report styling {args[1:4]}: {e}")
    _set_property_compat._epr_compat = True
    _epr_cda.set_property = _set_property_compat
if getattr(_epr_bbn.make_dispersive, "_epr_compat", 0) != 2:
    importlib.reload(_epr_bbn)
    _src, _first = inspect.getsourcelines(_epr_bbn.make_dispersive)
    _src = "".join(_src)
    for _old, _new in [("(s.dag() * s2[1]).norm()", "abs(s.overlap(s2[1]))"),
                       ("(vector1.dag() * evec).norm()", "abs(vector1.overlap(evec))"),
                       ("N = int(np.log(H.shape[0]) / np.log(fock_trunc))",
                        "N = int(round(np.log(H.shape[0]) / np.log(fock_trunc)))")]:
        assert _old in _src, f"pyEPR make_dispersive changed; patch not applied ({_old})"
        _src = _src.replace(_old, _new)
    exec(compile("\n" * (_first - 1) + _src, _epr_bbn.__file__, "exec"), _epr_bbn.__dict__)
    _epr_bbn.make_dispersive._epr_compat = 2
epr.config.root_dir = str(BASE / "data" / "pyEPR")

# ---- pick the modes from the solved design: 4 qubits (lowest high-Q modes) + readout ----
assert "JUNCTIONS" in globals(), "JUNCTIONS not defined: run the add_transmons / EM_Cavity_with_Transmons build cell"
hfss.set_active_design(DESIGN_EPR)
modes = eigenmode_results("cavity_transmons_eigenmode_results.csv")      # row k = HFSS Mode(k+1)
good = modes[modes["Q"] > Q_MIN]
qubit_modes = list(good.nsmallest(len(JUNCTIONS), "Frequency_Real (GHz)").index)
readout_mode = (good.drop(qubit_modes)["Frequency_Real (GHz)"] - READOUT_F_GHZ).abs().idxmin()
f_ro, Q_ro = modes.loc[readout_mode, "Frequency_Real (GHz)"], modes.loc[readout_mode, "Q"]
print(f"[chi] qubits = {[f'Mode({m + 1})' for m in qubit_modes]}, "
      f"readout = Mode({readout_mode + 1}) at {f_ro:.4f} GHz, Q = {Q_ro:.3g}")

# ---- EPR + numerical diagonalization ----
hfss.save_project()
pinfo = epr.ProjectInfo(project_path=str(AEDT.parent), project_name=NAME,
                        design_name=DESIGN_EPR, setup_name=SETUP_EM_TRANSMONS)
for name, j in JUNCTIONS.items():
    pinfo.junctions[name] = {**j, "length": epr.parse_units(j["length"])}
pinfo.validate_junction_info()
EPR_MODES = sorted(qubit_modes + [readout_mode])
eprd = epr.DistributedAnalysis(pinfo)
eprd.do_EPR_analysis(modes=EPR_MODES)
epra = epr.QuantumAnalysis(eprd.data_filename)
epra.analyze_all_variations(cos_trunc=8, fock_trunc=FOCK_TRUNC, print_result=False)
res = epra.results[list(epra.results.keys())[0]]

# ---- chi to readout per qubit (labelled by the junction that dominates each qubit mode) ----
Pm = pd.DataFrame(res["Pm_raw"]).astype(float)                 # rows: HFSS mode, cols: j1..j4
pos = {m: k for k, m in enumerate(EPR_MODES)}                   # HFSS mode -> row/col in chi matrices
chi_nd = np.real(np.asarray(res["chi_ND"], dtype=complex))     # MHz
chi_o1 = np.real(np.asarray(res["chi_O1"], dtype=complex))     # MHz
f_nd = np.real(np.asarray(res["f_ND"], dtype=complex))         # MHz
kappa_khz = f_ro * 1e6 / Q_ro                                   # readout kappa/2pi (kHz)
T_ro = Q_ro / (2 * np.pi * f_ro * 1e9)                          # readout photon lifetime (s)
r = pos[readout_mode]

rows = {}
for m in qubit_modes:
    q = "Q" + Pm.loc[m].idxmax().lstrip("j")
    k = pos[m]
    chi = abs(chi_nd[k, r]) * 1e3                               # kHz
    alpha = abs(chi_nd[k, k])                                   # MHz
    rows[q] = {"HFSS mode": f"Mode({m + 1})",
               "f01 (GHz)": f_nd[k] / 1e3,
               "alpha (MHz)": -alpha,
               "chi_ND to readout (kHz)": chi,
               "chi_O1 to readout (kHz)": abs(chi_o1[k, r]) * 1e3,
               "chi / kappa": chi / kappa_khz,
               "Purcell T1 ~ (2 alpha/chi) T_ro (us)": 2 * alpha * 1e3 / chi * T_ro * 1e6}
chi_table = pd.DataFrame(rows).T.sort_index()
chi_table.to_csv(BASE / "data" / "pyEPR" / "chi_readout_kHz.csv")
print(f"[chi] readout kappa/2pi = {kappa_khz:.1f} kHz (T_ro = {T_ro * 1e9:.0f} ns), fock_trunc = {FOCK_TRUNC}")
chi_table.round(3)
