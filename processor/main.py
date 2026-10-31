"""
sc-report: the last step of both single-cell workflows (A. Single-nucleus Atlas Mapping &
Condition Comparison; B. Multiome Gene Regulation). It reads whatever upstream outputs it is
given and writes

  OUTPUT_DIR/report/index.html        one self-contained page (inline CSS and images, no scripts)
  OUTPUT_DIR/report/provenance.json
  OUTPUT_DIR/tables/*.csv             the tables the page shows
  OUTPUT_DIR/tables/summary.json      the headline numbers, observations and caveats of the page
  OUTPUT_DIR/tables/provenance.json

Every input is optional; a section is rendered when its inputs are present. Exit 1 when none
of the inputs is found, 2 on a bad parameter.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import resource
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
log = logging.getLogger("sc-report")
log.setLevel(logging.INFO)   # the Lambda runtime sets the root logger to WARNING first
for noisy in ("matplotlib", "PIL", "fontTools"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

APP_NAME = "sc-report"
PARAMETERS = ("REPORT_TITLE", "FDR", "MAX_ITEMS", "MAX_FIGURES")
DEFAULT_TITLE = "Single-cell Report"
REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = {"A": "Single-nucleus Atlas Mapping & Condition Comparison", "B": "Multiome Gene Regulation"}


class BadParameter(ValueError):
    pass


def parameters() -> dict[str, Any]:
    def env(name: str, default: str) -> str:
        v = os.environ.get(name)
        return default if v is None or not str(v).strip() else str(v).strip()

    out: dict[str, Any] = {"REPORT_TITLE": env("REPORT_TITLE", DEFAULT_TITLE)[:200]}
    try:
        out["FDR"] = float(env("FDR", "0.05"))
        out["MAX_ITEMS"] = int(env("MAX_ITEMS", "20"))
        out["MAX_FIGURES"] = int(env("MAX_FIGURES", "12"))
    except ValueError as exc:
        raise BadParameter(f"FDR must be a number, MAX_ITEMS and MAX_FIGURES integers ({exc})") from exc
    if not 0 < out["FDR"] < 1:
        raise BadParameter(f"FDR must be between 0 and 1, got {out['FDR']}")
    if out["MAX_ITEMS"] < 1 or out["MAX_FIGURES"] < 1:
        raise BadParameter("MAX_ITEMS and MAX_FIGURES must be at least 1")
    return out


def app_version() -> str:
    try:
        return (REPO_ROOT / "VERSION").read_text().strip()
    except OSError:
        return "unknown"


def tool_versions() -> dict[str, str]:
    return {"python": platform.python_version(), **{p: version(p) for p in ("pandas", "numpy", "matplotlib", "jinja2")}}


def peak_rss_mb() -> float:
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(r / (1024 * 1024) if sys.platform == "darwin" else r / 1024, 1)


def cgroup_peak_mb():
    try:
        return round(int(open("/sys/fs/cgroup/memory.peak").read()) / 1024 / 1024, 1)
    except (OSError, ValueError):
        return None


def _section(name: str, fn, errors: list[dict[str, str]], *args):
    """Run one section; a failing section is logged, reported on the page, and the rest goes on."""
    t0 = time.monotonic()
    try:
        result = fn(*args)
        log.info("section %s: %s (%.1fs)", name, "rendered" if result else "no inputs", time.monotonic() - t0)
        return result
    except Exception as exc:  # noqa: BLE001 - one broken input must not sink the report
        log.error("section %s FAILED: %s\n%s", name, exc, traceback.format_exc())
        errors.append({"section": name, "error": f"{type(exc).__name__}: {exc}"})
        return None


def _text(v: Any) -> str:
    return json.dumps(v, separators=(",", ":")) if isinstance(v, (dict, list)) else str(v)


def methods(inp, numbers: dict[str, list[int]], own: dict[str, Any]) -> list[dict[str, Any]]:
    from processor import citations as C

    rows: dict[str, dict[str, Any]] = {}
    for path, prov in inp.provenances + [(None, own)]:
        app = str(prov.get("app"))
        params = prov.get("parameters") or {}
        ver = str(prov.get("version") or prov.get("appVersion") or "")
        key = json.dumps([app, ver, params], sort_keys=True, default=str)
        if key in rows:
            rows[key]["files"].append(inp.rel(path))
            continue
        method = prov.get("method")
        rows[key] = {"app": app, "step": C.STEPS.get(app, ""), "version": ver,
                     "tools": ", ".join(f"{k} {v}" for k, v in (prov.get("tools") or {}).items() if v),
                     "parameters": ", ".join(f"{k}={_text(v)}" for k, v in params.items()),
                     "method": [f"{k}: {_text(v) if not isinstance(v, str) else v}" for k, v in method.items()]
                     if isinstance(method, dict) else [str(method)] if method else [],
                     "cites": numbers.get(app, []), "files": [inp.rel(path)] if path else []}
    return sorted(rows.values(), key=lambda r: (C.ORDER.index(r["app"]) if r["app"] in C.ORDER else 98, r["app"]))


def main() -> int:
    started = datetime.now(timezone.utc)
    t_start = time.monotonic()
    input_dir, output_dir = os.environ.get("INPUT_DIR"), os.environ.get("OUTPUT_DIR")
    if not input_dir or not output_dir:
        log.error("INPUT_DIR and OUTPUT_DIR must be set")
        return 2
    try:
        params = parameters()
    except BadParameter as exc:
        log.error("bad parameter: %s", exc)
        return 2
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    if not input_dir.is_dir():
        log.error("INPUT_DIR %s is not a folder", input_dir)
        return 2
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
    fdr, max_items = params["FDR"], params["MAX_ITEMS"]

    from processor import analysis as A, citations as C, figures as F, inputs as I, report as R

    inp = I.gather(input_dir)
    for port in I.PORTS:
        log.info("input %s: %s", port, ", ".join(inp.rel(r.dir) or "." for r in inp.many(port)) or "none")
    log.info("labels.csv: %s; samples.csv: %s; %d provenance.json", inp.rel(inp.labels_csv) or "none",
             "yes" if inp.samples is not None else "none", len(inp.provenances))
    if not inp.has_any:
        log.error("none of the expected inputs was found (samples.csv, labels.csv, or an output folder of sc-qc, "
                  "sc-integrate, sc-annotate, sc-markers, st-compare, atac-prep, atac-regulome); INPUT_DIR holds %d "
                  "file(s)", len(inp.files))
        return 1

    report_dir, tables_dir = output_dir / "report", output_dir / "tables"
    for d in (report_dir, tables_dir):
        d.mkdir(parents=True, exist_ok=True)
    errors: list[dict[str, str]] = []
    figs = R.Figures(params["MAX_FIGURES"], inp)

    st = _section("samples", A.study, errors, inp, max_items)
    qc = _section("qc", A.qc, errors, inp, max_items)
    ig = _section("clusters", A.integration, errors, inp, max_items)
    ct = _section("cell types", A.celltypes, errors, inp, max_items)
    mk = _section("markers", A.markers, errors, inp, max_items)
    cp = _section("condition comparison", A.compare, errors, inp, fdr, max_items)
    at = _section("atac qc", A.atac, errors, inp, max_items)
    rg = _section("gene regulation", A.regulome, errors, inp, max_items)
    if ct and ct.get("composition") is not None:
        own = _section("composition figure", F.composition_bars, errors, ct["composition"], A.condition_of(inp),
                       f"{ct['label_column'].replace('_', ' ')} composition per sample", Path(tempfile.gettempdir()) / "sc_report_composition.png")
        if own:
            ct["figures"].insert(0, {"path": own, "own": True, "caption": "Composition per sample (condition in brackets); the "
                                                             "largest types coloured, the rest as 'other'"})
    for key, sec in (("study", st), ("qc", qc), ("integration", ig), ("celltypes", ct), ("atac", at)):
        if sec:
            sec["figures"] = figs.take(key, sec["figures"])
    for key, runs in (("markers", mk), ("compare", cp), ("regulome", rg)):
        for r in runs or []:
            r["key"] = f"{key}-{r['label']}"
            r["figures"] = figs.take(r["key"], r["figures"])

    own_prov = {"app": APP_NAME, "version": app_version(), "tools": tool_versions(), "parameters": params,
                "method": {"report": "summaries, tables and figures of the upstream steps; composition counted from "
                                     "labels.csv; significance re-thresholded at FDR from upstream adjusted p-values"}}
    references, numbers = C.gather(inp.provenances)
    meth = methods(inp, numbers, own_prov)
    pairs: list[tuple[str, str]] = []
    if inp.samples is not None:
        pairs += [(str(r.sample_id), str(getattr(r, "path", ""))) for r in inp.samples.itertuples()]
    pairs += [(str(k), str((v.get("files") or {}).get("matrix") or v.get("source") or ""))
              for k, v in ((inp.prep or {}).get("samples") or {}).items() if isinstance(v, dict)
              and str(k) not in {p[0] for p in pairs}]
    credit = C.datasets(pairs)
    apps = {r["app"] for r in meth}
    workflows = [WORKFLOWS[k] for k, hit in (("A", bool(apps & {"sc-qc", "sc-integrate", "sc-annotate", "sc-markers",
                                                                 "st-compare"}) or ct), ("B", bool(at or rg))) if hit]

    generated = started.isoformat(timespec="seconds")
    context = {"title": params["REPORT_TITLE"], "generated_at": generated, "app_version": own_prov["version"],
               "params": params, "study": st, "qc": qc, "integration": ig, "celltypes": ct, "markers": mk, "compare": cp,
               "atac": at, "regulome": rg, "methods": meth, "references": references, "credit": credit,
               "errors": errors, "workflows": workflows, "omitted": figs.omitted, "fdr": fdr,
               "platform": C.platform()}
    R.write_index(report_dir / "index.html", context)
    written = R.write_tables(tables_dir, context)
    texts = lambda s: {"observations": s["observations"], "caveats": s["caveats"], "facts": dict(s["facts"])} if s else None  # noqa: E731
    summary = {"app": APP_NAME, "appVersion": own_prov["version"], "generatedAt": generated, "title": params["REPORT_TITLE"],
               "workflows": workflows, "parameters": params, "sectionErrors": errors,
               "samples": texts(st), "qc": texts(qc), "clusters": texts(ig), "cellTypes": texts(ct),
               "markers": [{"label": r["label"], **texts(r)} for r in mk or []],
               "comparison": [{"label": r["label"], "de_n_significant": r.get("de_n_significant"), **texts(r)} for r in cp or []],
               "atac": texts(at), "regulome": [{"label": r["label"], **texts(r)} for r in rg or []],
               "citations": [{"role": "platform", "number": None, "doi": C.PLATFORM_DOI,
                              "pmid": C.platform()["record"].get("pmid") or None, "text": C.PLATFORM_STATEMENT,
                              "verifiedByReport": True}]
                            + [{"role": "method", "number": i + 1, "doi": r["doi"], "pmid": r.get("pmid") or None,
                                "text": r["text"], "verifiedByReport": r["verified"]} for i, r in enumerate(references)],
               "inputData": [{"doi": d["doi"], "text": d["record"]["text"], "licence": d["record"].get("license"),
                              "n_samples": d["n_samples"]} for d in credit]}
    (tables_dir / "summary.json").write_text(json.dumps(A.clean(summary), indent=2, ensure_ascii=False) + "\n")
    written.append("summary.json")
    sections = {"samples": st, "qc": qc, "clusters": ig, "cell_types": ct, "markers": mk, "comparison": cp, "atac": at,
                "regulome": rg}
    sample_ids = [str(x) for x in inp.samples["sample_id"]] if inp.samples is not None else []
    provenance = {**own_prov,
                  "inputs": sorted({inp.rel(p) for r in (x for port in I.PORTS for x in inp.many(port))
                                    for p in r.files.values() if not p.name.endswith(".h5ad")}
                                   | {inp.rel(p) for p, _ in inp.provenances}
                                   | ({inp.rel(inp.labels_csv)} if inp.labels_csv else set())),
                  "started": generated, "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "samples": [{"sample_id": s, "status": "reported"} for s in sample_ids],
                  "peak_rss_mb": peak_rss_mb(), "cgroup_peak_mb": cgroup_peak_mb(), "threads": 1,
                  "citations": C.OWN_SHORT,
                  "folders": {port: [inp.rel(r.dir) or "." for r in inp.many(port)] for port in I.PORTS},
                  "timings_seconds": {"total": round(time.monotonic() - t_start, 2)},
                  "runtime": "lambda" if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") else "container",
                  "workflows": workflows, "sections": {k: bool(v) for k, v in sections.items()},
                  "section_errors": errors, "figures_omitted": figs.omitted,
                  "outputs": {"report": ["index.html", "provenance.json"], "tables": written + ["provenance.json"]}}
    for d in (report_dir, tables_dir):
        (d / "provenance.json").write_text(json.dumps(A.clean(provenance), indent=2, ensure_ascii=False) + "\n")
    log.info("wrote %s (%d KB, %d section(s), %d error(s), %d figure(s)) and %d table(s) in %.1fs, peak RSS %.0f MB",
             report_dir / "index.html", (report_dir / "index.html").stat().st_size // 1024,
             sum(bool(v) for v in sections.values()), len(errors), figs.n, len(written), time.monotonic() - t_start,
             peak_rss_mb())
    return 0


if __name__ == "__main__":
    sys.exit(main())
