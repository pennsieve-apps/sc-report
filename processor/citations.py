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
# Printed first in every report's Citations section, word for word (the DOI is made a link, the text is
# unchanged). The paper is in references.json (verified) but not in CITATION.cff: the app also runs
# outside Pennsieve.
PLATFORM_DOI = "10.1038/s41597-025-06075-5"
PLATFORM_STATEMENT = (
    "Citing Pennsieve. If you used Pennsieve to store, analyse, share or publish data reported in a publication, "
    "please cite: Goldblum Z, et al. Pennsieve: A Collaborative Platform for Translational Neuroscience and Beyond. "
    "Scientific Data 2025;12:1834. doi:10.1038/s41597-025-06075-5. Please also cite the datasets you used (their "
    "DOIs) and the methods listed below.")


def platform() -> dict[str, Any]:
    """The statement split around its DOI (so the page can link it), and the verified record."""
    before, after = PLATFORM_STATEMENT.split(f"doi:{PLATFORM_DOI}", 1)
    return {"statement": PLATFORM_STATEMENT, "before": before, "after": after, "doi": PLATFORM_DOI,
            "record": table()[PLATFORM_DOI]}


OWN_SHORT = [{"doi": "10.1038/s41576-023-00586-w", "pmid": "37002403", "text": "Heumos L et al. Nat Rev Genet 2023"},
             {"doi": "10.1109/MCSE.2007.55", "text": "Hunter JD. Comput Sci Eng 2007"}]
OWN = [c["doi"] for c in OWN_SHORT]

# Demo datasets, recognised by the sample paths and ids sc-prep recorded (the layouts of the Discover
# datasets: drg-c2 sub-*/sam-*-DRG?/count, the DRG atlas sub-*/sam-*/sam-*-<level>/count, the sympathetic
# ganglia multiome sam-hSG-lib-<n>). Contributors as the Discover API lists them.
DATASETS = [
    {"doi": "10.26275/cxuf-ftav", "match": re.compile(r"sub-UTD-CC\d+/sam-UTD-CC\d+-DRG[LR]/"),
     "paper": "10.1093/brain/awaf370", "credit": "Arendt-Tranholm A, Sankaranarayanan I, Price TJ"},
    {"doi": "10.26275/9qsp-i8dh", "match": re.compile(r"sub-UTD-[A-Z]{2}\d+/sam-UTD-[A-Z]{2}\d+/sam-UTD-[A-Z]{2}\d+-"),
     "paper": None, "credit": "Sankaranarayanan I, Price TJ"},
    {"doi": "10.26275/oqxx-si9h", "match": re.compile(r"sam-hSG-lib-\d+"), "paper": None, "credit": "Yang L, Gereau R"},
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


def datasets(samples: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """samples: (sample_id, source path) pairs."""
    out = []
    for ds in DATASETS:
        n = sum(1 for sid, path in samples if ds["match"].search(f"{path}/") or ds["match"].search(sid))
        if n:
            out.append({**ds, "n_samples": n, "record": table()[ds["doi"]], "paper_record": table().get(ds["paper"]) if ds["paper"] else None})
    return out
