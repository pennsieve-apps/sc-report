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
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_PNG_BYTES = 8 * 1024 ** 2


def inline_png(path: Path) -> str | None:
    """A PNG file as a data: URI; None when it is not a PNG or too large (upstream files are untrusted)."""
    try:
        if path.stat().st_size > MAX_PNG_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if not data.startswith(PNG_MAGIC):
        return None
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


class Figures:
    """Inlines at most `limit` figures per section; counts the rest."""

    def __init__(self, limit: int):
        self.limit = limit
        self.omitted: dict[str, int] = {}
        self.n = 0

    def take(self, key: str, figs: list[dict[str, Any]]) -> list[dict[str, str]]:
        out = []
        for f in figs:
            uri = inline_png(Path(f["path"]))
            if uri is None:
                continue
            if len(out) >= self.limit:
                self.omitted[key] = self.omitted.get(key, 0) + 1
                continue
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
        save("atac_qc.csv", next((t["frame"] for t in at["tables"] if t["name"].startswith("cells removed")), None))
    save("methods.csv", pd.DataFrame([{"app": r["app"], "step": r["step"], "version": r["version"], "tools": r["tools"],
                                       "parameters": r["parameters"], "citations": ";".join(map(str, r["cites"]))}
                                      for r in ctx["methods"]]))
    save("citations.csv", pd.DataFrame([{"number": i + 1, "text": r["text"], "doi": r["doi"], "pmid": r.get("pmid", ""),
                                         "verified_by_report": r["verified"]} for i, r in enumerate(ctx["references"])]))
    return written
