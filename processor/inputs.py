"""
Finding the upstream outputs.

Every input path comes from safe_inputs.InputDir.walk() (the platform's symlink rule,
conventions.md), and every file is read through its capped readers: a folder's files are the
walked files in that folder, never a fresh glob or join. Linked layout: each port arrives in
INPUT_DIR/<port>/. Flat layout: everything side by side, possibly nested. Either way an upstream
output folder is recognised by the `app` of its provenance.json, else by a file only that app
writes. sc-markers, st-compare and atac-regulome write under <LABEL>/ and may be linked several
times: every such folder is one run. Per-cell files are never read whole: labels.csv is read in
chunks for three columns, st-compare's de.csv in chunks for six, .h5ad files are ignored.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from processor.safe_inputs import InputDir, UnsafeInput

log = logging.getLogger("sc-report")

PORTS = ["metadata", "qc", "integration", "annotation", "markers", "compare", "atac", "regulome"]
MAX_JSON_BYTES = 20 * 1024 ** 2
MAX_CSV_BYTES = 256 * 1024 ** 2          # whole-file reads; chunked reads (labels.csv, de.csv) have no cap
MAX_PNG_BYTES = 8 * 1024 ** 2

# Which app's folder each port takes; the fallback files recognise a folder without provenance.json.
APPS = {
    "metadata": ("sc-prep", ("samples.csv", "prep.json")),
    "qc": ("sc-qc", ()),
    "integration": ("sc-integrate", ("cluster_summary.csv",)),
    "annotation": ("sc-annotate", ()),
    "markers": ("sc-markers", ("markers.csv",)),
    "compare": ("st-compare", ("composition_tests.csv", "de_summary.csv")),
    "atac": ("atac-prep", ("atac_qc.csv",)),
    "regulome": ("atac-regulome", ()),
}
MULTI = ("markers", "compare", "regulome")


@dataclass
class Inputs:
    input_dir: Path
    dir: InputDir
    files: list[Path] = field(default_factory=list)
    runs: dict[str, list["Run"]] = field(default_factory=dict)
    provenances: list[tuple[Path, dict[str, Any]]] = field(default_factory=list)
    samples: pd.DataFrame | None = None
    prep: dict[str, Any] | None = None
    labels_csv: Path | None = None

    def rel(self, path: Path | None) -> str | None:
        return None if path is None else self.dir.rel(path)

    def read_json(self, path: Path | None) -> dict[str, Any] | None:
        if path is None:
            return None
        try:
            value = self.dir.read_json(path, MAX_JSON_BYTES)
            return value if isinstance(value, dict) else None
        except (UnsafeInput, OSError, ValueError) as exc:
            log.warning("cannot read %s: %s", self.rel(path), exc)
            return None

    def read_csv(self, path: Path | None, *cols: str, **kwargs) -> pd.DataFrame | None:
        """A whole CSV (capped), or None when it is missing, too large, unreadable or lacks one of `cols`."""
        if path is None:
            return None
        try:
            df = self.dir.read_csv(path, MAX_CSV_BYTES, **kwargs)
        except (UnsafeInput, OSError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            log.warning("cannot read %s: %s", self.rel(path), exc)
            return None
        return None if any(c not in df.columns for c in cols) else df

    def csv_chunks(self, path: Path, **kwargs):
        """Chunks of a CSV of any size, read from the checked file (kwargs: usecols, dtype, chunksize)."""
        with self.dir.open_checked(path) as fh:
            yield from pd.read_csv(fh, **kwargs)

    def inline_png(self, path: Path) -> str | None:
        return self.dir.inline_png(path, MAX_PNG_BYTES)

    def one(self, port: str) -> "Run | None":
        runs = self.runs.get(port) or []
        return runs[0] if runs else None

    def many(self, port: str) -> list["Run"]:
        return list(self.runs.get(port) or [])

    @property
    def has_any(self) -> bool:
        return self.samples is not None or self.labels_csv is not None or any(self.runs.get(p) for p in PORTS)


@dataclass
class Run:
    """One upstream output folder: only the walked files in it."""
    inp: Inputs
    port: str
    dir: Path
    app: str
    files: dict[str, Path]
    below: list[Path]
    label: str = ""
    summary: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None

    def file(self, name: str) -> Path | None:
        return self.files.get(name)

    def csv(self, name: str, *cols: str, **kwargs) -> pd.DataFrame | None:
        return self.inp.read_csv(self.file(name), *cols, **kwargs)

    def pngs(self) -> list[Path]:
        return sorted(p for p in self.below if p.suffix.lower() == ".png")

    def csvs(self) -> list[Path]:
        return sorted(p for n, p in self.files.items() if n.lower().endswith(".csv"))


def _label_of(run: Run) -> str:
    for v in ((run.summary or {}).get("label"), ((run.provenance or {}).get("parameters") or {}).get("LABEL")):
        if v:
            return str(v)
    return run.dir.name


def gather(input_dir: Path) -> Inputs:
    d = InputDir(input_dir)
    files = d.walk()
    inp = Inputs(input_dir=input_dir, dir=d, files=files)
    in_dir: dict[Path, dict[str, Path]] = {}
    for f in files:
        in_dir.setdefault(f.parent, {})[f.name] = f

    folder_app: dict[Path, str] = {}
    for f in files:
        if f.name == "provenance.json":
            prov = inp.read_json(f)
            if prov and prov.get("app"):
                inp.provenances.append((f, prov))
                folder_app[f.parent] = str(prov["app"])
    for port, (app, marker_files) in APPS.items():
        dirs = [p for p, a in folder_app.items() if a == app]
        dirs += [p for p, names in in_dir.items() if p not in folder_app and any(m in names for m in marker_files)]
        port_dir = input_dir / port
        on_port = [p for p in dirs if p == port_dir or port_dir in p.parents]
        dirs = on_port or dirs
        runs = []
        for p in sorted(set(dirs)):
            own = in_dir.get(p, {})
            run = Run(inp, port, p, app, own, [f for f in files if f.parent == p or p in f.parents],
                      summary=inp.read_json(own.get("summary.json")), provenance=inp.read_json(own.get("provenance.json")))
            run.label = _label_of(run)
            runs.append(run)
        if port == "integration":   # sc-integrate writes cells/, labels/ and integration/: the last one here
            runs = [r for r in runs if not r.file("labels.csv") and not any(n.endswith(".h5ad") for n in r.files)] \
                or runs[:1]
        if port == "annotation":    # sc-annotate's labels/ (labels.csv) and annotation/ (tables, figures)
            runs = [r for r in runs if not any(n.endswith(".h5ad") for n in r.files)]
        if len(runs) > 1 and port not in MULTI and port != "annotation":
            log.warning("%s: %d folders (%s); using the first", port, len(runs), ", ".join(inp.rel(r.dir) for r in runs))
            runs = runs[:1]
        inp.runs[port] = runs

    for f in files:
        if f.name == "samples.csv" and inp.samples is None:
            df = inp.read_csv(f, "sample_id", "n_obs", dtype={"sample_id": str})
            if df is not None:
                inp.samples = df
        elif f.name == "prep.json" and inp.prep is None:
            inp.prep = inp.read_json(f)
    # labels.csv: sc-annotate's (cell_type) over sc-integrate's (cluster).
    candidates = [f for f in files if f.name == "labels.csv"]
    with_type = [f for f in candidates if "cell_type" in getattr(inp.read_csv(f, nrows=0), "columns", [])]
    inp.labels_csv = (with_type or candidates or [None])[0]
    return inp
