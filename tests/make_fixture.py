"""
Synthetic upstream outputs of the single-cell workflows, one folder per sc-report input port,
following conventions.md and the files the apps write (summary tables, summary.json,
provenance.json with citations, small PNGs; labels.csv is per cell):

  metadata/     sc-prep: samples.csv (drg-c2-like paths, condition), prep.json, provenance.json
  qc/           sc-qc: qc_summary.csv (before/after, removed per reason), provenance.json (s4 failed)
  integration/  sc-integrate: cluster_summary.csv, metrics.csv, umap_*.png, summary.json
  annotation/   sc-annotate: labels.csv (cluster, cell_type, cell_type_score), summary.json
  markers/cell-type/  sc-markers
  compare/cell-type/  st-compare (provenance without citations, as st-compare writes it)
  atac/         atac-prep: atac_qc.csv (cells removed), summary.json            (workflow B)
  regulome/cell-type/  atac-regulome: a peaks table, summary.json               (workflow B)

Flat layout: each upstream output under upstream-<i>/, so folders are recognised by content.
Planted: Neuron is 5% of cells in control and 15% in pain; s3 lost 45% to QC (others ~10%);
cluster C05 in one sample only; a DOI one step cites that the report's table does not hold.

    python -m tests.make_fixture data/fixture --layout both --workflow ab
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

SAMPLES = [("s1", "control"), ("s2", "control"), ("s3", "pain"), ("s4", "pain"), ("s5", "pain")]
TYPES = ["Neuron", "Satellite_glia", "Fibroblast", "Endothelial"]
SHARE = {"control": [0.05, 0.40, 0.40, 0.15], "pain": [0.15, 0.35, 0.35, 0.15]}
UNKNOWN_DOI = "10.1234/not-in-the-table"


def png(path: Path, text: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(2, 1.5))
    ax.text(0.5, 0.5, text, ha="center", va="center")
    ax.axis("off")
    fig.savefig(path, dpi=40)
    plt.close(fig)


def prov(app: str, citations: list | None, **extra) -> dict:
    p = {"app": app, "version": "0.1.0", "tools": {"scanpy": "1.12.5"}, "parameters": {"SEED": 42},
         "method": {"step": f"{app} as run"}, **extra}
    if citations is not None:
        p["citations"] = citations
    return p


def write(folder: Path, files: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        p = folder / name
        if isinstance(content, pd.DataFrame):
            content.to_csv(p, index=False)
        elif isinstance(content, (dict, list)):
            p.write_text(json.dumps(content, indent=1))
        else:
            png(p, content)


def build(root: Path, workflow: str, seed: int = 3) -> dict[str, dict]:
    rng = np.random.default_rng(seed)
    ports: dict[str, dict] = {}
    samples = pd.DataFrame({
        "sample_id": [s for s, _ in SAMPLES],
        "path": [f"primary/sub-UTD-CC00{i}/sam-UTD-CC00{i}-DRGL/count/sample_filtered_feature_bc_matrix.h5"
                 for i in range(21, 21 + len(SAMPLES))],
        "source": "cellranger", "n_obs": [3000, 2800, 3100, 2500, 2900], "n_genes": 18082, "organism": "human",
        "condition": [c for _, c in SAMPLES], "sex": ["F", "M", "F", "M", "F"]})
    ports["metadata"] = {"samples.csv": samples, "prep.json": {"samples": {s: {"chemistry": "flex", "warnings": []}
                                                                         for s, _ in SAMPLES}, "skipped": [], "ignored": []},
                         "provenance.json": prov("sc-prep", ["10.1186/s13059-017-1382-0", "10.21105/joss.04371"])}
    if "a" in workflow:
        before = samples["n_obs"].to_numpy()
        lost = np.array([0.10, 0.08, 0.45, 0.12, 0.09])
        after = (before * (1 - lost)).astype(int)
        qc = pd.DataFrame({"sample_id": samples["sample_id"], "n_cells_before": before, "n_cells_after": after,
                           "n_removed_low_counts": (before - after) // 2, "n_removed_high_mt": (before - after) // 3,
                           "n_removed_doublet": (before - after) - (before - after) // 2 - (before - after) // 3,
                           "median_counts": [2100, 1900, 800, 2300, 2000]})
        ports["qc"] = {"qc_summary.csv": qc, "s1_qc.png": "s1 QC", "summary.json": {"n_samples": 5, "ambient": "cellbender"},
                       "provenance.json": prov("sc-qc", [{"doi": "10.1038/s41592-023-01943-7", "text": "CellBender (as given)"}],
                                               samples=[{"sample_id": s, "status": "ok"} for s, _ in SAMPLES])}
        rows, labels = [], []
        for (sid, cond), n in zip(SAMPLES, after):
            types = rng.choice(TYPES, size=n, p=SHARE[cond])
            cluster = np.array([f"C0{TYPES.index(t) + 1}" for t in types], dtype=object)
            if sid == "s2":
                cluster[:60] = "C05"
            score = rng.uniform(0.3, 1.0, n).round(3)
            labels.append(pd.DataFrame({"sample_id": sid, "obs_id": [f"{sid}:BC{i:06d}-1" for i in range(n)],
                                        "cluster": cluster, "cell_type": types, "cell_type_score": score}))
            for c, k in pd.Series(cluster).value_counts().items():
                rows.append({"sample_id": sid, "cluster": c, "n_obs": int(k), "fraction": k / n})
        labels = pd.concat(labels, ignore_index=True)
        cites = [{"name": "scanpy", "doi": "10.1186/s13059-017-1382-0", "pmid": "29409532", "text": "Wolf FA et al."},
                 {"name": "Harmony", "doi": "10.1038/s41592-019-0619-0", "pmid": "31740819", "text": "Korsunsky I et al."},
                 {"name": "x", "doi": UNKNOWN_DOI, "text": "Doe J. A method not in the table. J Test 2026;1:1."}]
        integ = prov("sc-integrate", cites)
        ports["integration"] = {"cluster_summary.csv": pd.DataFrame(rows),
                                "metrics.csv": pd.DataFrame({"metric": ["batch_asw"], "before": [0.5], "after": [0.8]}),
                                "umap_cluster.png": "UMAP cluster", "umap_sample.png": "UMAP sample",
                                "summary.json": {"n_samples": 5, "n_obs": int(after.sum()), "n_clusters": 5,
                                                 "integration": {"method": "harmony"}, "metrics": {"batch_asw": 0.8}},
                                "provenance.json": integ}
        ports["annotation"] = {"labels.csv": labels, "summary.json": {"n_cell_types": 4, "source": "markers"},
                               "provenance.json": prov("sc-annotate", ["10.1186/s13059-017-1382-0"])}
        mk = pd.DataFrame([{"label": t, "gene": f"{t[:3].upper()}{i}", "logfoldchange": 2.0 - i / 10, "pval_adj": 1e-20,
                            "pct_in": 0.8, "pct_out": 0.2, "rank": i + 1, "score": 20 - i, "n_samples_up": 5,
                            "n_samples": 5} for t in TYPES for i in range(6)])
        ports["markers/cell-type"] = {
            "markers.csv": mk, "dotplot.png": "dot plot", "heatmap.png": "heatmap",
            "summary.json": {"label": "cell-type", "label_column": "cell_type", "n_dropped_inconsistent": 3,
                             "labels": [{"label": t, "n_cells": 1000, "n_samples_present": 5, "n_markers": 6,
                                         "n_dropped_inconsistent": 1} for t in TYPES],
                             "notes": [], "caveat": "Cells are treated as independent observations (Squair et al. 2021)."},
            "provenance.json": prov("sc-markers", ["10.1038/s41467-021-25960-2", "10.2307/3001968"])}
        ct = pd.DataFrame({"label": TYPES, "comparison": "pain vs control", "clr_difference": [1.1, -0.1, -0.1, 0.0],
                           "parametric_p_adj": [0.01, 0.8, 0.8, 0.9], "rank_p_adj": [0.2, 0.9, 0.9, 0.9],
                           "tested": True, "mean_fraction_control": [0.05, 0.4, 0.4, 0.15],
                           "mean_fraction_pain": [0.15, 0.35, 0.35, 0.15]})
        ds = pd.DataFrame({"label": TYPES, "comparison": "pain vs control", "status": ["tested", "tested", "tested", "skipped"],
                           "reason": ["", "", "", "too few"], "n_significant": [3, 0, 1, None]})
        de = pd.DataFrame({"label": ["Neuron"] * 3 + ["Fibroblast"], "comparison": "pain vs control",
                           "gene": ["ATF3", "SPRR1A", "GAL", "FOS"], "log2_fold_change": [2.1, 3.0, 1.5, 0.8],
                           "base_mean": [50, 20, 30, 100], "p_adj": [1e-6, 1e-4, 0.01, 0.03]})
        ports["compare/cell-type"] = {
            "composition_tests.csv": ct, "de_summary.csv": ds, "de.csv": de, "composition.png": "composition",
            "volcano_Neuron.png": "volcano",
            "summary.json": {"label": "cell-type", "label_column": "cell_type", "condition_column": "condition",
                             "reference": "control", "levels": ["control", "pain"],
                             "n_samples_per_level": {"control": 2, "pain": 3}},
            "provenance.json": prov("st-compare", None)}
    if "b" in workflow:
        n_bc = {"s1": 300, "s3": 400}
        bc = pd.concat([pd.DataFrame({"sample_id": sid, "obs_id": [f"{sid}:BC{i:06d}-1" for i in range(n)],
                                      "n_fragment": rng.integers(500, 20000, n), "frac_dup": 0.2, "frac_mito": 0.01,
                                      "tsse": rng.uniform(2, 15, n).round(2)}) for sid, n in n_bc.items()],
                       ignore_index=True)
        bc["passed"] = (bc["tsse"] >= 5) & (bc["n_fragment"] >= 1000)
        bc["reason"] = np.where(bc["tsse"] < 5, "low_tsse", np.where(bc["n_fragment"] < 1000, "few_fragments", ""))
        per = bc.groupby("sample_id").agg(n_cells_before=("passed", "size"), n_cells_after=("passed", "sum"),
                                          median_tsse=("tsse", "median"), median_fragments=("n_fragment", "median"))
        per["n_removed_low_tsse"] = bc[bc["reason"] == "low_tsse"].groupby("sample_id").size()
        per["n_removed_few_fragments"] = bc[bc["reason"] == "few_fragments"].groupby("sample_id").size()
        ports["atac"] = {"atac_qc.csv": bc, "qc_summary.csv": per.fillna(0).reset_index(),
                         "summary.json": {"n_cells": int(bc["passed"].sum()), "genome": "GRCh38"},
                         "provenance.json": prov("atac-prep", ["10.1038/s41592-023-02139-9"])}
        ports["regulome/cell-type"] = {
            "peaks_per_type.csv": pd.DataFrame({"cell_type": TYPES, "n_peaks": [5000, 7000, 6000, 3000]}),
            "summary.json": {"label": "cell-type", "n_peaks": 21000, "notes": ["one label had too few cells"]},
            "motifs.png": "motifs", "provenance.json": prov("atac-regulome", ["10.1038/s41592-023-02139-9"])}
    return ports


def make_fixture(root: Path, layout: str = "both", workflow: str = "ab") -> dict[str, Path]:
    """Layouts: linked (one folder per port), flat (upstream-<i>/ folders), platform (the real link layout:
    upstream/<port>/ outputs, and platform/<port>/ real folders whose entries are symlinks into them)."""
    root = Path(root)
    ports = build(root, workflow)
    out = {}
    if layout in ("both", "platform"):
        up, link = root / "upstream", root / "platform"
        for d in (up, link):
            if d.exists():
                shutil.rmtree(d)
        for port, files in ports.items():
            write(up / port, files)
        for port in {p.split("/")[0] for p in ports}:
            (link / port).mkdir(parents=True)
            for e in sorted((up / port).iterdir()):
                (link / port / e.name).symlink_to(Path("..", "..", "upstream", port, e.name))
        out["platform"] = link
        if layout == "platform":
            return out
    for name in (["linked", "flat"] if layout == "both" else [layout]):
        base = root / name
        if base.exists():
            shutil.rmtree(base)
        for i, (port, files) in enumerate(ports.items()):
            # flat (no links): each upstream output in a folder whose name says nothing about the port, so
            # only its provenance.json or its files can tell what it is
            write(base / port if name == "linked" else base / f"upstream-{i}" / port.split("/")[-1], files)
        out[name] = base
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out", type=Path)
    ap.add_argument("--layout", choices=["linked", "flat", "platform", "both"], default="both")
    ap.add_argument("--workflow", default="ab")
    args = ap.parse_args(argv)
    for name, path in make_fixture(args.out, args.layout, args.workflow).items():
        print(f"{name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
