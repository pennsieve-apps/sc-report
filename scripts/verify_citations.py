#!/usr/bin/env python3
"""
Development tool (not run by the processor, needs network): fetches every work the app cites
from its source and rewrites the `references:` of CITATION.cff from what came back, so no
reference is written from memory.

  papers    Crossref (title, full author list in order, journal, year, volume, issue, pages),
            then PubMed E-utilities: esearch by DOI, esummary; title, first author and year
            must match, else no PMID is written and a warning is printed.
  datasets  DataCite (title, creators, year, publisher, licence) and the Pennsieve Discover API
            (contributors with ORCID, licence, version).

  python scripts/verify_citations.py           # print the check, write processor/references.json
  python scripts/verify_citations.py --cff     # also rewrite CITATION.cff's references

processor/references.json (keyed by DOI, lower case) is what the report looks a step's cited DOI
up in, offline; a DOI it does not hold is shown as the step gave it.
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PAPERS = {
    # the platform: printed first in every report's citation section (not in CITATION.cff: the app also
    # runs outside Pennsieve)
    "pennsieve": "10.1038/s41597-025-06075-5",
    # the report's own
    "heumos": "10.1038/s41576-023-00586-w",
    "matplotlib": "10.1109/MCSE.2007.55",
    # shared
    "scanpy": "10.1186/s13059-017-1382-0",
    "anndata": "10.21105/joss.04371",
    "bh": "10.1111/j.2517-6161.1995.tb02031.x",
    "scipy": "10.1038/s41592-019-0686-2",
    # sc-integrate
    "seurat_v3": "10.1016/j.cell.2019.05.031",
    "harmony": "10.1038/s41592-019-0619-0",
    "scvi": "10.1038/s41592-018-0229-2",
    "scvi_tools": "10.1038/s41587-021-01206-w",
    "leiden": "10.1038/s41598-019-41695-z",
    "umap": "10.21105/joss.00861",
    "scib": "10.1038/s41592-021-01336-8",
    "silhouette": "10.1016/0377-0427(87)90125-7",
    # sc-markers
    "wilcoxon": "10.2307/3001968",
    "mann_whitney": "10.1214/aoms/1177730491",
    "pullin": "10.1186/s13059-024-03183-0",
    "squair": "10.1038/s41467-021-25960-2",
    "zimmerman": "10.1038/s41467-021-21038-1",
    "zhang": "10.1016/j.cels.2019.07.012",
    # st-compare
    "deseq2": "10.1186/s13059-014-0550-8",
    "pydeseq2": "10.1093/bioinformatics/btad547",
    "sccoda": "10.1038/s41467-021-27150-6",
    "aitchison": "10.1111/j.2517-6161.1982.tb01195.x",
    # demo data
    "drg_c2_paper": "10.1093/brain/awaf370",
    # cited by the other single-cell apps (their CITATION.cff and provenance.json), so they render verified
    "fastp_1": "10.1002/imt2.70078",
    "scrublet": "10.1016/j.cels.2018.11.005",
    "seurat_2015": "10.1038/nbt.3192",
    "cellranger_2017": "10.1038/ncomms14049",
    "numpy": "10.1038/s41586-020-2649-2",
    "adipose_atlas": "10.1038/s41586-022-04518-2",
    "scarches": "10.1038/s41587-021-01001-7",
    "cell2location": "10.1038/s41587-021-01139-4",
    "seurat_v5": "10.1038/s41587-023-01767-y",
    "ldsc_seg": "10.1038/s41588-018-0081-4",
    "archr": "10.1038/s41588-021-00790-6",
    "synovium_ra": "10.1038/s41590-019-0378-1",
    "cellbender": "10.1038/s41592-023-01943-7",
    "snapatac2": "10.1038/s41592-023-02139-9",
    "synovium_oa_cartilage": "10.1038/s41598-020-67730-y",
    "panglaodb": "10.1093/database/baz046",
    "gencode_2023": "10.1093/nar/gkac1071",
    "jaspar_2026": "10.1093/nar/gkaf1209",
    "sgc_pain_2022": "10.1097/j.pain.0000000000002628",
    "sparc_sds": "10.1101/2021.02.10.430563",
    "ganglia_multiome_preprint": "10.1101/2025.09.18.677119",
    "trigeminal_drg_atlas": "10.1126/sciadv.adj9173",
    "melanoma_2016": "10.1126/science.aad0501",
    "celltypist": "10.1126/science.abl5197",
    "drg_spatial_2022": "10.1126/scitranslmed.abj8186",
    "oa_chondrocytes": "10.1136/annrheumdis-2017-212863",
    "macs": "10.1186/gb-2008-9-9-r137",
    "pipecomp": "10.1186/s13059-020-02136-7",
    "scanvi": "10.15252/msb.20209620",
    "rdata": "10.21105/joss.07540",
    "pandas_2010": "10.25080/majora-92bf1922-00a",
    "sklearn_arxiv": "10.48550/arxiv.1201.0490",
    "pytorch_arxiv": "10.48550/arxiv.1912.01703",
    "scikit_image": "10.7717/peerj.453",
}
# In references.json but not in CITATION.cff: the platform paper (the app also runs outside Pennsieve).
NOT_IN_CFF = {"10.1038/s41597-025-06075-5"}
# Demo data: DOI -> Discover dataset id.
DATASETS = {"10.26275/cxuf-ftav": 475, "10.26275/9qsp-i8dh": 480, "10.26275/oqxx-si9h": 465}


def get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "pennsieve-apps citation check (mailto:support@pennsieve.io)"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as fh:
                return json.load(fh)
        except Exception:  # noqa: BLE001
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"cannot fetch {url}")


def plain(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", "", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", plain(text)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", text)


def paper(doi: str) -> dict:
    """Crossref; DataCite for DOIs Crossref does not register (arXiv)."""
    if doi.lower().startswith("10.48550/"):
        a = get("https://api.datacite.org/dois/" + urllib.parse.quote(doi))["data"]["attributes"]
        authors = [{"family": c["familyName"], "given": c.get("givenName", "")} if c.get("familyName")
                   else {"name": c.get("name")} for c in a.get("creators", [])]
        pub = a.get("publisher")
        return {"doi": doi, "type": "article", "title": plain(a["titles"][0]["title"]), "authors": authors,
                "journal": "arXiv" if "arxiv" in doi.lower() else (pub if isinstance(pub, str) else (pub or {}).get("name", "")),
                "year": a.get("publicationYear"), "volume": "", "issue": "", "pages": "", "source": "datacite"}
    return crossref(doi)


def crossref(doi: str) -> dict:
    m = get("https://api.crossref.org/works/" + urllib.parse.quote(doi))["message"]
    authors = []
    for a in m.get("author", []):
        if a.get("family"):
            authors.append({"family": plain(a["family"]), "given": plain(a.get("given", ""))})
        elif a.get("name"):
            authors.append({"name": plain(a["name"])})
    year = None
    for k in ("published-print", "issued", "published-online"):
        dp = (m.get(k) or {}).get("date-parts")
        if dp and dp[0] and dp[0][0]:
            year = dp[0][0]
            break
    journal = plain((m.get("container-title") or [""])[0]) or plain(((m.get("institution") or [{}])[0]).get("name", "")) \
        or plain(m.get("publisher", ""))
    return {"doi": doi, "type": "article", "title": plain((m.get("title") or [""])[0]), "authors": authors,
            "journal": journal, "year": year, "volume": m.get("volume", ""),
            "issue": m.get("issue", ""), "pages": m.get("page") or m.get("article-number") or ""}


def pubmed(ref: dict) -> str:
    q = urllib.parse.quote(f"{ref['doi']}[doi]")
    for attempt in range(5):   # E-utilities answers an error body without idlist when rate-limited
        res = get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={q}&retmode=json")
        time.sleep(0.6 * (attempt + 1))
        if "idlist" in res.get("esearchresult", {}):
            break
    else:
        raise RuntimeError(f"PubMed esearch failed for {ref['doi']}")
    ids = res["esearchresult"]["idlist"]
    if len(ids) != 1:
        return ""
    s = get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={ids[0]}&retmode=json")["result"][ids[0]]
    time.sleep(0.4)
    title_ok = norm(s.get("title", ""))[:60] == norm(ref["title"])[:60]
    years = {str(ref["year"]), str(ref["year"] - 1)}
    year_ok = any(y in s.get("pubdate", "") + s.get("epubdate", "") for y in years)
    # First personal author: Crossref may list a consortium first; PubMed writes "Family Initials".
    first = next((a for a in ref["authors"] if a.get("family")), ref["authors"][0])
    first_name = first.get("family") or first.get("name") or ""
    pm_names = [a.get("name", "") for a in (s.get("authors") or [])]
    pm_families = [n.rsplit(" ", 1)[0] if " " in n else n for n in pm_names[:3]]
    pm_first = pm_names[0] if pm_names else ""
    author_ok = any(norm(first_name) == norm(f) for f in pm_families)
    n_ok = len(s.get("authors") or []) == len(ref["authors"])
    if not (title_ok and year_ok and author_ok):
        print(f"  PubMed {ids[0]} does not match {ref['doi']}: title {title_ok}, year {year_ok}, first author "
              f"{author_ok} ({pm_first!r} vs {first_name!r})", file=sys.stderr)
        return ""
    if not n_ok:
        print(f"  note: PubMed lists {len(s.get('authors') or [])} authors for {ref['doi']}, Crossref "
              f"{len(ref['authors'])} (consortium members are counted differently)", file=sys.stderr)
    return ids[0]


def dataset(doi: str, discover_id: int) -> dict:
    a = get("https://api.datacite.org/dois/" + urllib.parse.quote(doi))["data"]["attributes"]
    d = get(f"https://api.pennsieve.io/discover/datasets/{discover_id}")
    if d.get("doi", "").lower() != doi.lower():
        raise RuntimeError(f"Discover {discover_id} has DOI {d.get('doi')}, not {doi}")
    authors = [{"family": c["lastName"], "given": " ".join(x for x in (c.get("firstName"), c.get("middleInitial")) if x),
                "orcid": c.get("orcid") or ""} for c in d.get("contributors", [])]
    creators = [c.get("name") for c in a.get("creators", [])]
    if len(creators) != len(authors):
        print(f"  {doi}: DataCite has {len(creators)} creators, Discover {len(authors)} contributors", file=sys.stderr)
    lic = [r.get("rightsIdentifier", "") for r in a.get("rightsList", [])]
    pub = a.get("publisher")
    return {"doi": doi, "type": "data", "title": plain(a["titles"][0]["title"]), "authors": authors,
            "publisher": pub if isinstance(pub, str) else (pub or {}).get("name", ""), "year": a.get("publicationYear"),
            "license": "CC-BY-4.0" if "cc-by-4.0" in lic else ";".join(lic), "version": str(d.get("version", "")),
            "url": f"https://doi.org/{doi}", "discover": discover_id}


def q(s) -> str:
    return json.dumps(str(s), ensure_ascii=False)


def cff_refs(refs: list[dict]) -> str:
    lines = ["references:"]
    for r in refs:
        lines += [f"  - type: {r['type']}", f"    title: {q(r['title'])}", "    authors:"]
        for a in r["authors"]:
            if a.get("name"):
                lines.append(f"      - name: {q(a['name'])}")
                continue
            lines.append(f"      - family-names: {q(a['family'])}")
            if a.get("given"):
                lines.append(f"        given-names: {q(a['given'])}")
            if a.get("orcid"):
                lines.append(f"        orcid: {q('https://orcid.org/' + a['orcid'])}")
        if r["type"] == "data":
            lines += [f"    publisher:\n      name: {q(r['publisher'])}", f"    year: {r['year']}",
                      f"    version: {q(r['version'])}", f"    license: {r['license']}", f"    url: {q(r['url'])}",
                      f"    doi: {r['doi']}", f"    notes: {q('Demo data; Pennsieve Discover dataset ' + str(r['discover']))}"]
            continue
        lines += [f"    journal: {q(r['journal'])}", f"    year: {r['year']}"]
        for k in ("volume", "issue"):
            if r.get(k):
                lines.append(f"    {k}: {q(r[k])}")
        if r.get("pages"):
            p = str(r["pages"]).split("-", 1)
            lines.append(f"    start: {q(p[0])}")
            if len(p) > 1:
                lines.append(f"    end: {q(p[1])}")
        lines.append(f"    doi: {r['doi']}")
        if r.get("pmid"):
            lines.append(f"    notes: {q('PMID ' + r['pmid'])}")
    return "\n".join(lines) + "\n"


def verify() -> list[dict]:
    refs = []
    for key, doi in PAPERS.items():
        r = paper(doi)
        r["pmid"] = pubmed(r) if r.get("source") != "datacite" else ""
        refs.append(r)
        print(f"{key:14} {r['year']} {len(r['authors']):3} authors  PMID {r['pmid'] or '-':9} {r['journal'][:28]:28} "
              f"{r['volume']}({r['issue']}):{r['pages']}  {r['title'][:60]}")
    for doi, did in DATASETS.items():
        r = dataset(doi, did)
        refs.append(r)
        print(f"{'data':14} {r['year']} {len(r['authors']):3} authors  Discover {did} v{r['version']} {r['license']}  "
              f"{r['title'][:60]}")
    return refs


def short_authors(authors: list[dict]) -> str:
    def one(a):
        if a.get("name"):
            return a["name"]
        initials = "".join(p[0] for p in re.split(r"[\s\-.]+", a.get("given", "")) if p)
        return f"{a['family']} {initials}".strip()
    names = [one(a) for a in authors]
    return ", ".join(names) if len(names) <= 6 else ", ".join(names[:3]) + ", et al."


def text(r: dict) -> str:
    if r["type"] == "data":
        return f"{short_authors(r['authors']).rstrip('.')}. {r['title']}. {r['publisher']} ({r['year']}), version {r['version']}."
    where = str(r.get("volume") or "") + (f"({r['issue']})" if r.get("issue") else "") + (f":{r['pages']}" if r.get("pages") else "")
    return f"{short_authors(r['authors']).rstrip('.')}. {r['title'].rstrip('.')}. {r['journal']} {r['year']}" + (f";{where}" if where else "") + "."


if __name__ == "__main__":
    refs = verify()
    table = {r["doi"].lower(): {"doi": r["doi"], "type": r["type"], "text": text(r), "pmid": r.get("pmid", ""),
                                "year": r["year"], "checked": time.strftime("%Y-%m-%d"),
                                **({"license": r["license"], "discover": r["discover"]} if r["type"] == "data" else {})}
             for r in refs}
    out = ROOT / "processor" / "references.json"
    out.write_text(json.dumps(table, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {out}")
    if "--cff" in sys.argv:
        cff = ROOT / "CITATION.cff"
        head = cff.read_text().split("references:")[0]
        cff.write_text(head + cff_refs([r for r in refs if r["doi"] not in NOT_IN_CFF]))
        print(f"wrote {cff}")
