"""
The citations section: gathered from the `citations` of every provenance.json among the inputs,
deduplicated by DOI, numbered in pipeline order, plus the report's own.

A step may cite a bare DOI (as conventions.md describes) or an object {doi, pmid, text} (as
sc-integrate and sc-markers write). Each DOI is looked up in references.json, written and checked
against Crossref / PubMed / DataCite / Discover by scripts/verify_citations.py, so the page shows
the verified record; a DOI the table does not hold is shown with the step's own text and marked as
not checked by the report. st-compare (reused unchanged from the spatial suite) writes no
citations, so its methods papers are listed here.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

REFERENCES = Path(__file__).parent / "references.json"
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")

ORDER = ["sc-prep", "sc-qc", "sc-integrate", "sc-annotate", "sc-markers", "st-compare", "atac-prep", "atac-regulome",
         "sc-report"]
STEPS = {
    "sc-prep": "Import and sample metadata", "sc-qc": "Quality control, ambient RNA, doublets, normalization",
    "sc-integrate": "Integration, clustering and UMAP", "sc-annotate": "Cell-type annotation",
    "sc-markers": "Marker genes", "st-compare": "Composition and pseudobulk differential expression",
    "atac-prep": "ATAC import and QC", "atac-regulome": "Gene regulation (ATAC)", "sc-report": "This report",
}
# Apps whose provenance.json carries no citations: their methods papers (st-compare's own CITATION.cff).
FALLBACK = {"st-compare": ["10.1093/bioinformatics/btad547", "10.1186/s13059-014-0550-8", "10.1038/s41467-021-25960-2",
                           "10.1038/s41467-021-27150-6", "10.1111/j.2517-6161.1982.tb01195.x",
                           "10.1111/j.2517-6161.1995.tb02031.x", "10.1038/s41592-019-0686-2", "10.21105/joss.04371"]}
OWN = ["10.1038/s41576-023-00586-w", "10.1109/MCSE.2007.55"]

# Demo datasets, recognised by the sample paths sc-prep recorded.
DATASETS = [
    {"doi": "10.26275/cxuf-ftav", "match": re.compile(r"sub-UTD-CC\d+"), "paper": "10.1093/brain/awaf370",
     "credit": "Arendt-Tranholm A, Sankaranarayanan I, Price TJ"},
]


@lru_cache(maxsize=1)
def table() -> dict[str, dict[str, Any]]:
    return json.loads(REFERENCES.read_text(encoding="utf-8"))


def _entry(c: Any) -> dict[str, Any] | None:
    if isinstance(c, str):
        c = {"doi": c}
    if not isinstance(c, dict):
        return None
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", str(c.get("doi") or "").strip(), flags=re.I)
    if not DOI_RE.match(doi):
        return None
    known = table().get(doi.lower())
    if known:
        return {**known, "verified": True}
    text = str(c.get("text") or "").strip()
    return {"doi": doi, "text": text or f"doi:{doi}", "pmid": str(c.get("pmid") or ""), "verified": False}


def gather(provenances: list[tuple[Path, dict[str, Any]]]) -> tuple[list[dict[str, Any]], dict[str, list[int]]]:
    """(numbered references, app -> its reference numbers)."""
    per_app: dict[str, list[dict[str, Any]]] = {}
    for _, prov in provenances:
        app = str(prov.get("app"))
        given = prov.get("citations") if isinstance(prov.get("citations"), list) else FALLBACK.get(app, [])
        for c in given:
            e = _entry(c)
            if e and e["doi"].lower() not in {x["doi"].lower() for x in per_app.setdefault(app, [])}:
                per_app[app].append(e)
    per_app["sc-report"] = [_entry(d) for d in OWN]
    refs: list[dict[str, Any]] = []
    numbers: dict[str, list[int]] = {}
    index: dict[str, int] = {}
    for app in sorted(per_app, key=lambda a: (ORDER.index(a) if a in ORDER else 99, a)):
        for e in per_app[app]:
            key = e["doi"].lower()
            if key not in index:
                refs.append(e)
                index[key] = len(refs)
            numbers.setdefault(app, []).append(index[key])
    return refs, numbers


def datasets(paths: list[str]) -> list[dict[str, Any]]:
    out = []
    for ds in DATASETS:
        n = sum(1 for p in paths if ds["match"].search(p))
        if n:
            out.append({**ds, "n_samples": n, "record": table()[ds["doi"]], "paper_record": table().get(ds["paper"])})
    return out
