"""
The page (Jinja2 with autoescape, inline CSS, no scripts, images inlined as data: URIs, so the
single index.html works offline and can be moved alone) and the tables behind it.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES = Path(__file__).parent / "templates"


class Figures:
    """Inlines at most `limit` figures per section; counts the rest. Upstream figures go through
    InputDir.inline_png (walk rule, size cap, PNG signature); the report's own figure (`own`) is a file it
    wrote itself under /tmp."""

    def __init__(self, limit: int, inp):
        self.limit = limit
        self.inp = inp
        self.omitted: dict[str, int] = {}
        self.n = 0

    def _uri(self, f: dict[str, Any]) -> str | None:
        if f.get("own"):
            return "data:image/png;base64," + base64.b64encode(Path(f["path"]).read_bytes()).decode("ascii")
        return self.inp.inline_png(Path(f["path"]))

    def take(self, key: str, figs: list[dict[str, Any]]) -> list[dict[str, str]]:
        out = []
        for f in figs:
            if len(out) >= self.limit:
                self.omitted[key] = self.omitted.get(key, 0) + 1
                continue
            uri = self._uri(f)
            if uri is not None:
                out.append({"src": uri, "caption": f["caption"]})
        self.n += len(out)
        return out


def write_index(path: Path, context: dict[str, Any]) -> None:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html", "j2"]),
                      trim_blocks=True, lstrip_blocks=True)
    path.write_text(env.get_template("index.html.j2").render(**context), encoding="utf-8")


def write_tables(tables_dir: Path, ctx: dict[str, Any]) -> list[str]:
    written: list[str] = []

    def save(name: str, df: pd.DataFrame | None) -> None:
        if df is not None and not df.empty:
            df.to_csv(tables_dir / name, index=False, float_format="%.6g", lineterminator="\n")
            written.append(name)

    st, qc, ig, ct, at = (ctx.get(k) for k in ("study", "qc", "integration", "celltypes", "atac"))
    if st:
        save("samples.csv", st["tables"][0]["frame"])
    if qc:
        save("qc.csv", next((t["frame"] for t in qc["tables"] if t["name"] == "qc"), None))
    if ig:
        save("clusters.csv", next((t["frame"] for t in ig["tables"] if t["name"] == "cluster_summary.csv"), None))
    if ct and ct.get("composition_long") is not None:
        save("composition.csv", ct["composition_long"])
        if ct.get("by_condition") is not None:
            save("composition_by_condition.csv", ct["by_condition"].stack().rename("mean_fraction").reset_index()
                 .rename(columns={"level_0": "condition"}))
    save("markers_top.csv", pd.concat([pd.DataFrame(r["rows"]).assign(label_set=r["label"])
                                       for r in ctx.get("markers") or []]) if ctx.get("markers") else None)
    for key, name in (("composition", "composition_tests.csv"), ("de_summary", "de_summary.csv"),
                      ("top_genes", "de_top_genes.csv")):
        frames = [r[key].assign(label_set=r["label"]) for r in ctx.get("compare") or [] if r.get(key) is not None]
        save(name, pd.concat(frames) if frames else None)
    if at:
        save("atac_qc.csv", next((t["frame"] for t in at["tables"] if t["name"] in ("qc", "barcodes removed by ATAC QC, per sample")), None))
    save("methods.csv", pd.DataFrame([{"app": r["app"], "step": r["step"], "version": r["version"], "tools": r["tools"],
                                       "parameters": r["parameters"], "citations": ";".join(map(str, r["cites"]))}
                                      for r in ctx["methods"]]))
    pf = ctx["platform"]
    save("citations.csv", pd.DataFrame([{"role": "platform", "number": "", "text": pf["record"]["text"], "doi": pf["doi"],
                                         "pmid": pf["record"].get("pmid", ""), "verified_by_report": True}]
                                       + [{"role": "method", "number": i + 1, "text": r["text"], "doi": r["doi"],
                                           "pmid": r.get("pmid", ""), "verified_by_report": r["verified"]}
                                          for i, r in enumerate(ctx["references"])]))
    return written
