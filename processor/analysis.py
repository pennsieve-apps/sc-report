"""
What the report says: per section the numbers, tables and figures, plus observations (plain
sentences drawn from the data) and caveats (what to keep in mind before trusting a number, mostly
the limitations each upstream app states). It describes the data; it does not advise.

Formats known from conventions.md (samples.csv, labels.csv) and from the apps (sc-markers,
st-compare, sc-integrate) get dedicated handling; for everything else a step wrote, the section
shows the headline numbers of its summary.json, its per-sample status from provenance.json, its
CSV tables (first rows) and its figures, so a new column or table shows up without a code change.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from processor.inputs import Inputs, Run

LABELS_CHUNK = 500_000
MAX_TABLE_COLS = 14
PER_CELL_TABLES = ("labels.csv", "atac_qc.csv", "markers.csv", "de.csv")   # never shown as raw tables
DE_CHUNK = 200_000


# ---------------------------------------------------------------- formatting

def pct(frac: Any) -> str:
    try:
        v = 100.0 * float(frac)
    except (TypeError, ValueError):
        return "–"
    if math.isnan(v):
        return "–"
    a = abs(v)
    return "0%" if a == 0 else f"{v:.0f}%" if a >= 10 else f"{v:.1f}%" if a >= 1 else f"{v:.2f}%" if a >= 0.1 else "<0.1%"


def pval(p: Any) -> str:
    try:
        p = float(p)
    except (TypeError, ValueError):
        return "–"
    if math.isnan(p):
        return "–"
    if p == 0:
        return "<1e-300"
    return f"{p:.0e}".replace("e-0", "e-") if p < 0.001 else f"{p:.2g}"


def count(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "–"
    return "–" if math.isnan(f) else f"{int(round(f)):,}"


def cell(v: Any) -> str:
    """Any table value as short text."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    if isinstance(v, (bool, np.bool_)):
        return "yes" if v else "no"
    if isinstance(v, (int, np.integer)):
        return f"{int(v):,}"
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return f"{f:,.0f}" if abs(f) >= 1000 else f"{f:.3g}"
    if isinstance(v, (list, tuple)):
        return ", ".join(cell(x) for x in v[:12]) + (" …" if len(v) > 12 else "")
    return str(v)


def joined(items: list[Any]) -> str:
    items = [str(i) for i in items]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def plural(n: int, word: str) -> str:
    return f"{count(n)} {word if n == 1 else word + 's'}"


def clean(obj: Any) -> Any:
    """JSON-safe: NaN -> None, numpy scalars -> Python, paths -> str."""
    if isinstance(obj, pd.DataFrame):
        return clean(obj.to_dict(orient="records"))
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, Path):
        return str(obj)
    return obj


def section() -> dict[str, Any]:
    return {"observations": [], "caveats": [], "facts": [], "tables": [], "figures": []}


def table(name: str, df: pd.DataFrame | None, max_rows: int, note: str = "") -> dict[str, Any] | None:
    if df is None or df.empty:
        return None
    cols = list(df.columns[:MAX_TABLE_COLS])
    return {"name": name, "columns": cols, "rows": [[cell(v) for v in r] for r in df[cols].head(max_rows).itertuples(index=False)],
            "n_rows": len(df), "n_cols": df.shape[1], "note": note,
            "numeric": [bool(pd.api.types.is_numeric_dtype(df[c])) for c in cols], "frame": df}


def facts(summary: dict[str, Any] | None, skip: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """Scalar headline numbers of a summary.json (one level of nesting flattened), as (key, text)."""
    out = []
    for k, v in (summary or {}).items():
        if k in skip or k in ("parameters", "figures", "notes", "citations"):
            continue
        if isinstance(v, dict):
            out += [(f"{k}.{k2}", cell(v2)) for k2, v2 in v.items() if not isinstance(v2, (dict, list))]
        elif not isinstance(v, list) or (v and all(not isinstance(x, (dict, list)) for x in v)):
            out.append((k, cell(v)))
    return out[:40]


def sample_status(run: Run) -> pd.DataFrame | None:
    """The per-sample status a step recorded in provenance.json (conventions: 'per-sample status')."""
    s = (run.provenance or {}).get("samples")
    rows = list(s.values()) if isinstance(s, dict) else s if isinstance(s, list) else []
    rows = [{k: v for k, v in r.items() if not isinstance(v, (dict, list))} for r in rows if isinstance(r, dict)]
    return pd.DataFrame(rows) if rows else None


def generic(run: Run, sec: dict[str, Any], max_items: int, skip_tables: tuple[str, ...] = ()) -> None:
    """Headline numbers, per-sample status, CSV tables and figures of a step's output folder."""
    sec["facts"] += facts(run.summary)
    for note in (run.summary or {}).get("notes") or []:
        sec["observations"].append(f"{run.app}: {note}")
    for p in run.csvs():
        if p.name in PER_CELL_TABLES + skip_tables:
            continue
        df = run.inp.read_csv(p)
        if df is not None and "obs_id" in df.columns:      # a per-cell table (e.g. sc-qc's <sample>_qc.csv)
            continue
        sec["tables"].append(table(p.name, df, max_items))
    st = sample_status(run)
    if st is not None and not any(t and t["name"] == "qc" for t in sec["tables"]):
        sec["tables"].append(table(f"{run.app}: per-sample status (provenance.json)", st, 200))
        if "status" in st:
            bad = st[st["status"].astype(str) != "ok"]
            for _, r in bad.iterrows():
                sec["observations"].append(f"{r.get('sample_id', '?')}: {r['status']} in {run.app}"
                                           + (f" ({r['reason'] if 'reason' in r and pd.notna(r['reason']) else r.get('error', '')})"))
    sec["figures"] += [{"path": p, "caption": caption(p)} for p in run.pngs()]
    sec["tables"] = [t for t in sec["tables"] if t]


def caption(p: Path) -> str:
    stem = p.stem
    for pre, text in (("umap_", "UMAP by "), ("volcano_", "Volcano: ")):
        if stem.startswith(pre):
            return text + stem[len(pre):].replace("_", " ")
    return stem.replace("_", " ")


# ---------------------------------------------------------------- study design

GROUPING_HINTS = ("donor", "patient", "subject", "individual", "batch", "replicate", "pool", "lane")


def condition_column(inp: Inputs) -> str | None:
    for run in inp.many("compare"):
        col = (run.summary or {}).get("condition_column")
        if col and inp.samples is not None and col in inp.samples.columns:
            return str(col)
    if inp.samples is not None and "condition" in inp.samples.columns:
        return "condition"
    return None


def condition_of(inp: Inputs) -> dict[str, str]:
    col = condition_column(inp)
    if not col:
        return {}
    return {str(k): str(v) for k, v in zip(inp.samples["sample_id"], inp.samples[col]) if pd.notna(v) and str(v) != ""}


def study(inp: Inputs, max_items: int) -> dict[str, Any] | None:
    s = inp.samples
    if s is None:
        return None
    out = section()
    n = len(s)
    obs = pd.to_numeric(s["n_obs"], errors="coerce")
    sentence = f"{plural(n, 'sample')}: {count(obs.sum())} cells or nuclei in all"
    if n > 1:
        sentence += f" ({count(obs.min())}–{count(obs.max())} per sample)"
    if "n_genes" in s:
        g = pd.to_numeric(s["n_genes"], errors="coerce")
        sentence += f", {count(g.max())} genes" if g.nunique() == 1 else f", {count(g.min())}–{count(g.max())} genes"
    out["observations"].append(sentence + ".")
    for col, what in (("organism", "Organism"), ("source", "Input format")):
        if col in s:
            out["observations"].append(f"{what}: " + joined([f"{k} ({v})" for k, v in s[col].astype(str).value_counts().items()]) + ".")
    chem = [str(v.get("chemistry")) for v in ((inp.prep or {}).get("samples") or {}).values()
            if isinstance(v, dict) and v.get("chemistry")]
    if chem:
        out["observations"].append("Chemistry: " + joined([f"{k} ({v})" for k, v in pd.Series(chem).value_counts().items()]) + ".")
    out["n_samples"], out["n_obs"] = n, float(obs.sum())
    cond = condition_column(inp)
    out["condition_column"] = cond
    if cond:
        counts = s[cond].fillna("").astype(str).replace("", "(none)").value_counts().sort_index()
        out["conditions"] = {k: int(v) for k, v in counts.items()}
        out["observations"].append(f"Conditions ({cond}): " + joined([f"{k} ({v})" for k, v in counts.items()]) + ".")
        if len(counts) > 1 and counts.min() < 3:
            out["caveats"].append(f"'{counts.idxmin()}' has {plural(int(counts.min()), 'sample')}: comparisons between "
                                  "conditions use the sample (donor) as the replicate, so only large, consistent "
                                  "differences can be detected.")
        copied_from = (inp.prep or {}).get("condition_from") or (inp.prep or {}).get("conditionFrom")  # copied to `condition`
        extra = [c for c in s.columns if c not in ("sample_id", "path", "source", "n_obs", "n_genes", "organism", cond,
                                                   copied_from)]
        for c in extra:
            if s[c].isna().all() or s[c].nunique() < 2:
                continue
            pairs = s[[c, cond]].astype(str).drop_duplicates()
            if s[c].nunique() == counts.size and len(pairs) == counts.size:
                out["caveats"].append(f"'{c}' and '{cond}' group the samples identically: a difference between "
                                      f"{cond} levels is also a difference in {c}.")
            elif any(h in c.lower() for h in GROUPING_HINTS) and pairs.groupby(c).size().max() == 1 and len(counts) > 1 \
                    and s[c].nunique() < n:
                out["caveats"].append(f"Every '{c}' value occurs in one {cond} level only: {cond} and {c} are confounded.")
    shown = [c for c in s.columns if c != "path"]
    out["tables"].append(table("samples", s[shown], 500))
    if inp.prep:
        skipped = inp.prep.get("skipped") or []
        ignored = inp.prep.get("ignored") or []
        if skipped or ignored:
            out["caveats"].append(f"sc-prep skipped {len(skipped)} and ignored {len(ignored)} input entries (see prep.json).")
        warns = [(k, w) for k, v in (inp.prep.get("samples") or {}).items() if isinstance(v, dict)
                 for w in (v.get("warnings") or [])]
        out["warnings"] = [f"{k}: {w}" for k, w in warns][:max_items * 5]
    return out


# ---------------------------------------------------------------- QC

BEFORE = re.compile(r"^n_(obs|cells|nuclei|barcodes)_(before|in|input)$|^n_before$")
AFTER = re.compile(r"^n_(obs|cells|nuclei|barcodes)_(after|out|kept|pass(ed)?)$|^n_after$")
REMOVED = re.compile(r"^n_(removed|failed|dropped)_(.+)$")


def qc(inp: Inputs, max_items: int) -> dict[str, Any] | None:
    run = inp.one("qc")
    if run is None:
        return None
    out = section()
    per_sample = run.csv("qc_summary.csv", "sample_id")
    used = "qc_summary.csv"
    if per_sample is None:
        per_sample = sample_status(run)
    if per_sample is not None:
        b = next((c for c in per_sample.columns if BEFORE.match(c)), None)
        a = next((c for c in per_sample.columns if AFTER.match(c)), None)
        if b and a:
            before = pd.to_numeric(per_sample[b], errors="coerce")
            after = pd.to_numeric(per_sample[a], errors="coerce")
            removed = before.sum() - after.sum()
            frac = 1 - after / before
            out["observations"].append(f"QC removed {count(removed)} of {count(before.sum())} cells or nuclei "
                                       f"({pct(removed / before.sum() if before.sum() else 0)})"
                                       + (f"; per sample {pct(frac.min())} ({per_sample.loc[frac.idxmin(), 'sample_id']}) to "
                                          f"{pct(frac.max())} ({per_sample.loc[frac.idxmax(), 'sample_id']})" if len(per_sample) > 1 else "")
                                       + ".")
            out["n_before"], out["n_after"] = float(before.sum()), float(after.sum())
            med = float(frac.median())
            for _, r in per_sample[(frac > max(2 * med, med + 0.1)) & (frac > 0.2)].iterrows():
                out["observations"].append(f"{r['sample_id']} lost more than the others: "
                                           f"{pct(1 - float(r[a]) / float(r[b]))} against a median of {pct(med)}.")
        reasons = {m.group(2).replace("_", " "): int(pd.to_numeric(per_sample[c], errors="coerce").fillna(0).sum())
                   for c in per_sample.columns if (m := REMOVED.match(c))}
        reasons = {k: v for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]) if v}
        if reasons:
            out["by_reason"] = reasons
            out["observations"].append("Removed by reason: " + joined([f"{k} {count(v)}" for k, v in reasons.items()])
                                       + " (a cell can fail several tests).")
        out["tables"].append(table("qc", per_sample, 500))
    generic(run, out, max_items, skip_tables=(used,))
    out["caveats"].append("Single-nucleus data keep little cytoplasmic RNA; mitochondrial and ambient reads behave "
                          "differently from whole cells, and large neurons can be over-represented among high-count "
                          "barcodes or removed as doublets. Look at what each sample lost before reading differences.")
    return out


# ---------------------------------------------------------------- integration / clusters

def integration(inp: Inputs, max_items: int) -> dict[str, Any] | None:
    run = inp.one("integration")
    if run is None:
        return None
    out = section()
    sm = run.summary or {}
    method = (sm.get("integration") or {}).get("method") if isinstance(sm.get("integration"), dict) else sm.get("integration")
    if sm.get("n_clusters"):
        out["observations"].append(f"{plural(int(sm['n_clusters']), 'cluster')} over {count(sm.get('n_obs'))} cells in "
                                   f"{plural(int(sm.get('n_samples') or 0), 'sample')}"
                                   + (f", integrated with {method}" if method else "") + ".")
    clusters = run.csv("cluster_summary.csv")
    if clusters is not None and "sample_id" in clusters and "cluster" in clusters:
        n_obs = pd.to_numeric(clusters.get("n_obs"), errors="coerce")
        present = clusters[n_obs >= 20].groupby("cluster")["sample_id"].nunique() if n_obs is not None else None
        n_s = clusters["sample_id"].nunique()
        if present is not None and n_s > 2:
            single = present[present == 1].index.tolist()
            if single:
                out["observations"].append(f"Clusters with >= 20 cells in one sample only (possibly sample-specific "
                                           f"or an integration artefact): {joined(single)}.")
    generic(run, out, max_items)
    order = ["umap_cluster", "umap_sample", "umap_condition"]
    out["figures"].sort(key=lambda f: order.index(f["path"].stem) if f["path"].stem in order else 9)
    out["caveats"].append("Clusters come from a resolution parameter: the number of clusters is a choice, not a finding. "
                          "UMAP distances between clusters are not meaningful.")
    return out


# ---------------------------------------------------------------- cell types and composition

def read_labels(inp: Inputs, path: Path) -> tuple[pd.DataFrame, str, dict[str, Any]]:
    """Counts per sample x label from labels.csv (read in chunks; three columns)."""
    header = inp.read_csv(path, nrows=0).columns
    col = "cell_type" if "cell_type" in header else "cluster"
    use = ["sample_id", col] + (["cell_type_score"] if "cell_type_score" in header and col == "cell_type" else [])
    counts: pd.Series | None = None
    scores: list = []
    n = 0
    for chunk in inp.csv_chunks(path, usecols=use, dtype={"sample_id": str, col: str}, chunksize=LABELS_CHUNK):
        chunk[col] = chunk[col].fillna("(none)")
        c = chunk.groupby(["sample_id", col]).size()
        counts = c if counts is None else counts.add(c, fill_value=0)
        n += len(chunk)
        if "cell_type_score" in chunk:
            scores.append(pd.to_numeric(chunk["cell_type_score"], errors="coerce").dropna().to_numpy(np.float32))
    table_ = counts.unstack(fill_value=0).astype(int) if counts is not None else pd.DataFrame()
    median = float(np.median(np.concatenate(scores))) if scores and sum(len(x) for x in scores) else None
    return table_, col, {"n": n, "median_score": median}


def celltypes(inp: Inputs, max_items: int) -> dict[str, Any] | None:
    runs = inp.many("annotation")
    if inp.labels_csv is None and not runs:
        return None
    out = section()
    if inp.labels_csv is not None:
        counts, col, info = read_labels(inp, inp.labels_csv)
        out["label_column"] = col
        frac = counts.div(counts.sum(axis=1), axis=0)
        out["composition"] = frac
        totals = counts.sum().sort_values(ascending=False)
        out["observations"].append(f"{plural(len(totals), col.replace('_', ' '))} over {count(info['n'])} cells; largest: "
                                   + joined([f"{k} {pct(v / totals.sum())}" for k, v in totals.head(5).items()]) + ".")
        if "Unassigned" in totals:
            out["observations"].append(f"{pct(totals['Unassigned'] / totals.sum())} of cells are Unassigned: no "
                                       "reference or marker set called them confidently. Their share is part of every "
                                       "composition below.")
        rare = totals[totals / totals.sum() < 0.01]
        if len(rare):
            out["observations"].append(f"Below 1% of cells: {joined(rare.index.tolist()[:10])}"
                                       + (" …" if len(rare) > 10 else "") + ".")
        if info["median_score"] is not None:
            mode = next(((r.summary or {}).get("mode") for r in runs if (r.summary or {}).get("mode")), None)
            out["observations"].append(f"Median cell-type score {info['median_score']:.2f} (sc-annotate's "
                                       "cell_type_score, 0–1" + (f", {mode} mode" if mode else "") + "; its scale "
                                       "depends on the mode, so compare it between runs of the same mode only).")
        one = [k for k in counts.columns if (counts[k] >= 20).sum() == 1 and counts.shape[0] > 2]
        if one:
            out["observations"].append(f"With >= 20 cells in one sample only: {joined(one[:10])}.")
        cond = condition_of(inp)
        if cond:
            by = frac.groupby(frac.index.map(lambda s: cond.get(s, "(none)"))).mean()
            out["by_condition"] = by
            if len(by) == 2:
                (a, ra), (b, rb) = by.iterrows()
                diff = (rb - ra).abs().sort_values(ascending=False)
                big = [t for t in diff.index[:3] if diff[t] >= 0.02]
                if big:
                    out["observations"].append("Largest differences in mean share between conditions (descriptive; the "
                                               "tests are in the condition comparison): " + joined(
                                                   [f"{t} {pct(ra[t])} in {a} vs {pct(rb[t])} in {b}" for t in big]) + ".")
            long = by.T.reset_index().rename(columns={"index": col, col: col})
            out["tables"].append(table(f"mean share of each {col} per condition", long.round(4), max_items * 3))
        long = (counts.stack().rename("n_cells").reset_index()
                .merge(frac.stack().rename("fraction").reset_index(), on=["sample_id", col]))
        long["condition"] = long["sample_id"].map(cond) if cond else None
        out["composition_long"] = long
        out["tables"].append(table(f"cells per sample and {col}", counts.reset_index(), 500))
    for run in runs:
        generic(run, out, max_items)
    out["caveats"].append("Shares are of the cells that passed QC: dissociation and nuclei isolation do not sample every "
                          "cell type equally (large neurons, adipocytes), so a share is not a tissue proportion. Tests of "
                          "composition between conditions are in the condition-comparison section.")
    return out


# ---------------------------------------------------------------- markers

def markers_one(run: Run, max_items: int) -> dict[str, Any] | None:
    m = run.csv("markers.csv", "label", "gene", "rank")
    if m is None:
        return None
    out = section()
    sm = run.summary or {}
    out["label"], out["label_column"] = run.label, sm.get("label_column") or run.label
    m["label"] = m["label"].astype(str)
    top = (m[m["rank"] <= 5].sort_values(["label", "rank"]).groupby("label")["gene"].apply(lambda g: ", ".join(g)))
    rows = []
    for r in sm.get("labels") or [{"label": k} for k in top.index]:
        rows.append({"label": r["label"], "n_cells": r.get("n_cells"), "n_samples": r.get("n_samples_present"),
                     "n_markers": r.get("n_markers", int((m["label"] == r["label"]).sum())),
                     "dropped_inconsistent": r.get("n_dropped_inconsistent"), "top markers": top.get(r["label"], "")})
    out["rows"] = rows
    out["tables"].append(table("top markers per label", pd.DataFrame(rows), 500))
    out["observations"].append(f"{plural(len(rows), 'label')}, {count(len(m))} markers written"
                               + (f"; {count(sm['n_dropped_inconsistent'])} pooled hits dropped as inconsistent "
                                  "across samples" if sm.get("n_dropped_inconsistent") else "") + ".")
    none = [r["label"] for r in rows if not r["n_markers"]]
    if none:
        out["observations"].append(f"No marker passed the filters for {joined(none)}.")
    out["observations"] += [str(n) for n in sm.get("notes") or []]
    if sm.get("caveat"):
        out["caveats"].append(str(sm["caveat"]))
    out["figures"] = [{"path": p, "caption": c} for n, c in (("dotplot", "Top markers per label: mean expression (scaled "
                                                               "per gene) and fraction of cells"),
                                                              ("heatmap", "Top markers in single cells"))
                      if (p := run.file(f"{n}.png"))]
    out["frame"] = m
    return out


def markers(inp: Inputs, max_items: int) -> list[dict[str, Any]] | None:
    runs = [r for r in (markers_one(run, max_items) for run in inp.many("markers")) if r]
    return runs or None


# ---------------------------------------------------------------- condition comparison (st-compare)

def min_rank_p(n1: int, n2: int) -> float:
    return 1.0 if n1 < 1 or n2 < 1 else min(1.0, 2.0 / math.comb(n1 + n2, n1))


def truthy(v: Any) -> bool:
    return bool(v) if isinstance(v, (bool, np.bool_)) else str(v).strip().lower() in ("true", "1", "yes")


def compare_one(run: Run, fdr: float, max_items: int) -> dict[str, Any] | None:
    ct = run.csv("composition_tests.csv", "label")
    ds = run.csv("de_summary.csv", "label", "status")
    if ct is None and ds is None:
        return None
    out = section()
    sm = run.summary or {}
    ref, levels = sm.get("reference"), [str(x) for x in sm.get("levels") or []]
    others = [x for x in levels if x != ref]
    per_level = {str(k): int(v) for k, v in (sm.get("n_samples_per_level") or {}).items()}
    out.update(label=run.label, label_column=sm.get("label_column") or run.label, condition_column=sm.get("condition_column"),
               reference=ref, levels=levels, per_level=per_level)
    if ct is not None:
        ct["label"] = ct["label"].astype(str)
        tested = ct["tested"].map(truthy) if "tested" in ct else pd.Series(True, index=ct.index)
        padj = pd.to_numeric(ct.get("parametric_p_adj"), errors="coerce")
        ct["significant"] = tested & (padj < fdr)
        cols = ["label", "comparison", "clr_difference", "parametric_p_adj", "rank_p_adj", "significant"] + \
               [c for c in ct.columns if c.startswith("mean_fraction_")]
        out["composition"] = ct[[c for c in cols if c in ct]].sort_values("parametric_p_adj")
        out["tables"].append(table("composition tests", out["composition"], max_items))
        sig = ct[ct["significant"]]
        if len(sig):
            out["observations"].append(f"Composition: {plural(len(sig), 'label')} of {int(tested.sum())} "
                                       f"{'differs' if len(sig) == 1 else 'differ'} at FDR "
                                       f"{fdr:g}: " + joined([f"{r['label']} (adj. p {pval(r['parametric_p_adj'])})"
                                                               for _, r in sig.head(6).iterrows()]) + ".")
        elif tested.any():
            why = ""
            if len(others) == 1 and ref in per_level and others[0] in per_level:
                why = (f" With {per_level[ref]} vs {per_level[others[0]]} samples the rank test cannot go below "
                       f"p = {pval(min_rank_p(per_level[ref], per_level[others[0]]))} before correction.")
            out["observations"].append(f"Composition: no label's share differs significantly at FDR {fdr:g}." + why
                                       + " Not significant is not evidence of no change.")
        else:
            out["observations"].append("Composition: nothing could be tested (each level needs at least two samples).")
    if ds is not None:
        tested = ds[ds["status"] == "tested"]
        n_sig = int(pd.to_numeric(tested.get("n_significant"), errors="coerce").fillna(0).sum()) if len(tested) else 0
        hits = significant_de(run, fdr)
        if hits is not None:
            n_sig = len(hits)
            out["top_genes"] = hits[[c for c in ("label", "comparison", "gene", "log2_fold_change", "base_mean", "p_adj")
                                     if c in hits]].head(max_items)
            out["tables"].append(table("top DE genes (pseudobulk)", out["top_genes"], max_items))
        out["de_n_significant"] = n_sig
        if len(tested):
            out["observations"].append(f"Pseudobulk DE: {count(n_sig)} significant gene × label results at FDR {fdr:g} "
                                       f"over {plural(len(tested), 'tested label')}.")
        skipped = ds[ds["status"] != "tested"]
        if len(skipped):
            out["observations"].append(f"Not tested ({plural(skipped['label'].nunique(), 'label')}): "
                                       + joined(skipped["label"].astype(str).unique().tolist()[:12]) + " (too few "
                                       "samples with enough cells of the label; see the DE summary).")
        out["tables"].append(table("DE summary per label", ds, 500))
        out["de_summary"] = ds
    if per_level and min(per_level.values()) < 5:
        out["caveats"].append("The sample (donor) is the replicate. With fewer than five per group only large and "
                              "consistent changes are detectable.")
    out["caveats"].append("Each condition level is a different set of donors; anything else that differs between them "
                          "(age, sex, surgery, processing batch) is part of the comparison unless it is the block.")
    out["figures"] = [{"path": p, "caption": c} for n, c in (("composition", "Share of each label per sample and condition"),
                                                              ("de_heatmap", "Top genes of every DE test (log2 fold change)"))
                      if (p := run.file(f"{n}.png"))]
    out["figures"] += [{"path": p, "caption": caption(p)} for p in run.pngs() if p.name.startswith("volcano_")]
    return out


def significant_de(run: Run, fdr: float) -> pd.DataFrame | None:
    """The rows of st-compare's de.csv with p_adj < fdr, read in chunks of six columns (de.csv is genes x labels)."""
    path = run.file("de.csv")
    if path is None:
        return None
    header = run.inp.read_csv(path, nrows=0)
    if header is None or not {"label", "gene", "p_adj"} <= set(header.columns):
        return None
    use = [c for c in ("label", "comparison", "gene", "log2_fold_change", "base_mean", "p_adj") if c in header.columns]
    parts = []
    for chunk in run.inp.csv_chunks(path, usecols=use, dtype={"label": str, "gene": str}, chunksize=DE_CHUNK):
        chunk["p_adj"] = pd.to_numeric(chunk["p_adj"], errors="coerce")
        parts.append(chunk[chunk["p_adj"] < fdr])
    return pd.concat(parts).sort_values("p_adj") if parts else header


def compare(inp: Inputs, fdr: float, max_items: int) -> list[dict[str, Any]] | None:
    runs = [r for r in (compare_one(run, fdr, max_items) for run in inp.many("compare")) if r]
    return runs or None


# ---------------------------------------------------------------- ATAC

def atac(inp: Inputs, max_items: int) -> dict[str, Any] | None:
    """atac-prep: qc_summary.csv (one row per sample) and atac_qc.csv (every barcode, `passed`, `reason`)."""
    run = inp.one("atac")
    if run is None:
        return None
    out = section()
    per_sample = run.csv("qc_summary.csv", "sample_id")
    if per_sample is not None and {"n_cells_before", "n_cells_after"} <= set(per_sample.columns):
        before = pd.to_numeric(per_sample["n_cells_before"], errors="coerce").sum()
        after = pd.to_numeric(per_sample["n_cells_after"], errors="coerce").sum()
        out["observations"].append(f"ATAC QC kept {count(after)} of {count(before)} barcodes "
                                   f"({pct(after / before if before else 0)}).")
        reasons = {m.group(2).replace("_", " "): int(pd.to_numeric(per_sample[c], errors="coerce").fillna(0).sum())
                   for c in per_sample.columns if (m := REMOVED.match(c))}
        reasons = {k: v for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]) if v}
        if reasons:
            out["observations"].append("Removed by reason: " + joined([f"{k} {count(v)}" for k, v in reasons.items()])
                                       + ".")
        for c, what in (("median_tsse", "TSS enrichment"), ("median_fragments", "fragments per nucleus")):
            if c in per_sample:
                v = pd.to_numeric(per_sample[c], errors="coerce")
                out["observations"].append(f"Median {what} per sample: {v.min():.3g}–{v.max():.3g}.")
        out["tables"].append(table("qc", per_sample, 500))
    elif run.file("atac_qc.csv"):
        removed: dict[str, int] = {}
        why: dict[str, int] = {}
        header = run.csv("atac_qc.csv", "sample_id", "passed", nrows=0)
        if header is not None:
            use = ["sample_id", "passed"] + (["reason"] if "reason" in header.columns else [])
            for chunk in inp.csv_chunks(run.file("atac_qc.csv"), usecols=use, dtype=str, chunksize=LABELS_CHUNK):
                fail = chunk[~chunk["passed"].map(truthy)]
                for k, v in fail["sample_id"].value_counts().items():
                    removed[k] = removed.get(k, 0) + int(v)
                if "reason" in fail:
                    for k, v in fail["reason"].fillna("").value_counts().items():
                        why[k] = why.get(k, 0) + int(v)
            out["observations"].append(f"ATAC QC removed {count(sum(removed.values()))} barcodes"
                                       + (": " + joined([f"{k} {count(v)}" for k, v in sorted(why.items(), key=lambda x: -x[1])[:6]])
                                          if why else "") + ".")
            out["tables"].append(table("barcodes removed by ATAC QC, per sample",
                                       pd.DataFrame({"sample_id": list(removed), "n_removed": list(removed.values())}), 500))
    generic(run, out, max_items, skip_tables=("qc_summary.csv",))
    out["caveats"].append("ATAC signal is sparse per nucleus (a few thousand fragments); TSS enrichment and fragment "
                          "counts depend on the chemistry and sequencing depth, so compare samples with care.")
    return out


def regulome(inp: Inputs, max_items: int) -> list[dict[str, Any]] | None:
    runs = []
    for run in inp.many("regulome"):
        out = section()
        out["label"] = run.label
        generic(run, out, max_items)
        out["caveats"].append("Peaks and motif enrichment describe accessibility, not binding or regulation: a motif "
                              "is shared by a family of transcription factors, and accessibility at a gene does not "
                              "mean it is expressed.")
        runs.append(out)
    return runs or None
