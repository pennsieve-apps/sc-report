"""
Finding the upstream outputs.

Linked layout: each input port arrives in INPUT_DIR/<port>/ (placement: subfolder). Flat
layout: everything side by side, possibly nested. Either way an upstream output folder is
recognised by the `app` of its provenance.json (every app of the single-cell workflows writes
one per output folder), else by a file only that app writes. sc-markers, st-compare and
atac-regulome write under <LABEL>/ and may be linked several times: every such folder is one run.

INPUT_DIR entries are symlinks, so the walk follows them, but only to where the platform's own
entries point (the targets of the links in INPUT_DIR and in its port folders); a link further
down that resolves elsewhere is skipped. Large per-cell files are never read whole: labels.csv
is read for three columns, .h5ad files are ignored.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger("sc-report")

PORTS = ["metadata", "qc", "integration", "annotation", "markers", "compare", "atac", "regulome"]
MAX_JSON_BYTES = 20 * 1024 ** 2
MAX_CSV_BYTES = 2 * 1024 ** 3

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


def allowed_roots(root: Path) -> list[str]:
    roots = {os.path.realpath(root)}
    for top in root.iterdir():
        roots.add(os.path.realpath(top))
        if top.is_dir():
            for entry in top.iterdir():
                roots.add(os.path.realpath(entry))
    return sorted(roots)


def _inside(real: str, roots: list[str]) -> bool:
    return any(real == r or real.startswith(r.rstrip("/") + "/") for r in roots)


def walk(root: Path) -> tuple[list[Path], list[Path]]:
    """Every file under root (symlinks followed within the allowed roots), sorted; and the rejected paths."""
    roots = allowed_roots(root)
    found: list[Path] = []
    rejected: list[Path] = []
    seen: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        real = os.path.realpath(dirpath)
        if not _inside(real, roots):
            rejected.append(Path(dirpath))
            dirnames[:] = []
            continue
        if real in seen:
            dirnames[:] = []
            continue
        seen.add(real)
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for f in sorted(filenames):
            p = Path(dirpath) / f
            if f.startswith(".") or not p.is_file():
                continue
            (found if _inside(os.path.realpath(p), roots) else rejected).append(p)
    return found, rejected


def read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError) as exc:
        log.warning("cannot read %s: %s", path.name, exc)
        return None


def read_csv(path: Path | None, *cols: str, **kwargs) -> pd.DataFrame | None:
    """A CSV, or None when it is missing, too large, unreadable or lacks one of `cols`."""
    if path is None or not path.is_file() or path.stat().st_size > MAX_CSV_BYTES:
        return None
    try:
        df = pd.read_csv(path, **kwargs)
    except (OSError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        log.warning("cannot read %s: %s", path.name, exc)
        return None
    if any(c not in df.columns for c in cols):
        return None
    return df


@dataclass
class Run:
    """One upstream output folder."""
    port: str
    dir: Path
    app: str
    label: str = ""
    summary: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None

    def file(self, name: str) -> Path | None:
        p = self.dir / name
        return p if p.is_file() else None

    def csv(self, name: str, *cols: str, **kwargs) -> pd.DataFrame | None:
        return read_csv(self.file(name), *cols, **kwargs)

    def pngs(self) -> list[Path]:
        return sorted(p for p in self.dir.rglob("*.png") if p.is_file())

    def csvs(self) -> list[Path]:
        return sorted(p for p in self.dir.glob("*.csv") if p.is_file())


@dataclass
class Inputs:
    input_dir: Path
    files: list[Path] = field(default_factory=list)
    rejected: list[Path] = field(default_factory=list)
    runs: dict[str, list[Run]] = field(default_factory=dict)
    provenances: list[tuple[Path, dict[str, Any]]] = field(default_factory=list)
    samples: pd.DataFrame | None = None
    prep: dict[str, Any] | None = None
    labels_csv: Path | None = None

    def rel(self, path: Path | None) -> str | None:
        if path is None:
            return None
        try:
            return str(Path(path).relative_to(self.input_dir))
        except ValueError:
            return str(path)

    def one(self, port: str) -> Run | None:
        runs = self.runs.get(port) or []
        return runs[0] if runs else None

    def many(self, port: str) -> list[Run]:
        return list(self.runs.get(port) or [])

    @property
    def has_any(self) -> bool:
        return self.samples is not None or self.labels_csv is not None or any(self.runs.get(p) for p in PORTS)


def _label_of(run: Run) -> str:
    for v in ((run.summary or {}).get("label"), ((run.provenance or {}).get("parameters") or {}).get("LABEL")):
        if v:
            return str(v)
    return run.dir.name


def gather(input_dir: Path) -> Inputs:
    files, rejected = walk(input_dir)
    inp = Inputs(input_dir=input_dir, files=files, rejected=rejected)
    for f in rejected:
        log.warning("skipped %s: resolves outside INPUT_DIR", inp.rel(f))

    # Folders by the app that wrote them.
    folder_app: dict[Path, str] = {}
    for f in files:
        if f.name == "provenance.json":
            prov = read_json(f)
            if prov and prov.get("app"):
                inp.provenances.append((f, prov))
                folder_app[f.parent] = str(prov["app"])
    names = {f.parent: set() for f in files}
    for f in files:
        names[f.parent].add(f.name)
    for port, (app, marker_files) in APPS.items():
        dirs = [d for d, a in folder_app.items() if a == app]
        dirs += [d for d, ns in names.items() if d not in folder_app and any(m in ns for m in marker_files)]
        port_dir = input_dir / port
        if port_dir.is_dir():   # linked: prefer what arrived on the port
            on_port = [d for d in dirs if d == port_dir or port_dir in d.parents]
            dirs = on_port or dirs
        runs = []
        for d in sorted(set(dirs)):
            run = Run(port, d, app, summary=read_json(d / "summary.json"), provenance=read_json(d / "provenance.json"))
            run.label = _label_of(run)
            runs.append(run)
        if port == "integration":   # sc-integrate writes cells/, labels/ and integration/: the last one here
            runs = [r for r in runs if not r.file("labels.csv") and not any(r.dir.glob("*.h5ad"))] or runs[:1]
        if port == "annotation":
            runs = [r for r in runs if r.file("labels.csv")] or runs
        if len(runs) > 1 and port not in MULTI:
            log.warning("%s: %d folders (%s); using the first", port, len(runs), ", ".join(inp.rel(r.dir) for r in runs))
            runs = runs[:1]
        inp.runs[port] = runs

    for f in files:
        if f.name == "samples.csv" and inp.samples is None:
            df = read_csv(f, "sample_id", "n_obs", dtype={"sample_id": str})
            if df is not None:
                inp.samples = df
        elif f.name == "prep.json" and inp.prep is None:
            inp.prep = read_json(f)
    # labels.csv: sc-annotate's (cell_type) over sc-integrate's (cluster).
    candidates = [f for f in files if f.name == "labels.csv"]
    with_type = [f for f in candidates if "cell_type" in getattr(read_csv(f, nrows=0), "columns", [])]
    inp.labels_csv = (with_type or candidates or [None])[0]
    return inp
