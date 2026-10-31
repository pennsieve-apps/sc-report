# sc-report

The last step of both single-cell workflows, and the only one whose output is written for a
person:

- **A. Single-nucleus Atlas Mapping & Condition Comparison:**
  `sc-prep → sc-qc → sc-integrate → sc-annotate → {sc-markers, st-compare} → sc-report`
- **B. Multiome Gene Regulation:** `atac-prep → atac-regulome (+ labels from sc-annotate) → sc-report`

It reads whatever upstream outputs it is given and writes **one self-contained HTML page** and
the tables behind it. **Every input is optional**: the report detects what it has and renders
the matching sections, so the same app closes both workflows and any mix of them. The page is a
single file: styles and figures are inline (PNG as `data:` URIs), there are no scripts, and
nothing is loaded from the network, so it can be opened offline, attached to an email or stored
with a dataset.

**For a biologist.** One place to read what the workflow found:

- which samples and conditions went in, and how many nuclei each sample lost to QC (and why);
- which clusters were found, and whether one appears in a single donor only;
- which cell types make up each sample, and how their shares differ between conditions;
- the marker genes of each type, which cell types change in abundance, and which genes change
  within a cell type (pseudobulk);
- the ATAC QC and regulatory results for multiome data.

Each finding is a plain sentence with its numbers ("Neuron 5.4% of cells in control vs 15% in
pain"), followed by the caveats that come with the method: few donors per group, marker p-values
that are not evidence, nuclei sampling some cell types unevenly. It describes the data; it does
not advise. The Methods and Citations sections say which tool did what, at which version, with
which parameters, and whose work to cite.

**For a computational analyst.** The report fits nothing. It reads each step's summary tables,
`summary.json` and `provenance.json`, plus `labels.csv` (in chunks of 500,000 rows, three
columns) to count cells per sample and label. It never reads `.h5ad` files or `samples_full.csv`.

Upstream folders are recognised by the `app` of their `provenance.json` (every single-cell app
writes one per output folder), else by a file only that app writes. So the report works whether
or not the workflow links each output to its own port, and it does not depend on file names
beyond the contract. Formats known from `conventions.md` and from the apps (samples.csv,
labels.csv, sc-integrate, sc-markers, st-compare) get dedicated sentences. For everything else a
step writes, the section shows the headline numbers of its `summary.json`, its per-sample status
from `provenance.json`, its CSV tables (first rows) and its figures, so a new column or table
shows up without a code change.

## Sections

| Section | Shown when | What it says |
|---|---|---|
| Samples and metadata | `metadata` | samples, nuclei, genes, organism, input format, chemistry (prep.json); conditions and samples per level; columns that group the samples like the condition (identical, or donor/batch nested in it); sc-prep warnings, skipped and ignored entries |
| Quality control | `qc` | nuclei before/after per sample, removed per reason (`n_removed_*` columns), samples that lost much more than the median; sc-qc's tables, status and figures |
| Integration, clusters and UMAP | `integration` | clusters, cells, samples, method; clusters present (>= 20 cells) in one sample only; UMAPs, cluster table, metrics |
| Cell types and composition | `annotation` (labels.csv) | types and shares, types below 1%, low-confidence calls (`cell_type_score` < 0.5), types in one sample only; composition per sample (the report's own stacked-bar figure) and mean share per condition, with the largest differences between two conditions (descriptive) |
| Marker genes | `markers` (one block per `<LABEL>/`) | per label: cells, samples, markers, hits dropped as inconsistent, top five; dot plot and heatmap; the p-value caveat |
| Condition comparison | `compare` (one block per `<LABEL>/`) | composition tests (at the report's `FDR`, and when nothing is significant, the smallest p the rank test can reach); pseudobulk DE results, top genes and labels not tested; st-compare's figures |
| ATAC QC | `atac` | cells removed by ATAC QC (per reason and sample, from `atac_qc.csv`), atac-prep's summary, tables and figures |
| Gene regulation | `regulome` (one block per `<LABEL>/`) | atac-regulome's summary, tables and figures |
| Methods | any `provenance.json` | per step: version, tools, parameters, method as run, citation numbers |
| Citations | always | gathered from every step's `provenance.json` `citations`, deduplicated, numbered in pipeline order, plus the report's own |
| Input data | `metadata` | the samples; a data credit (dataset, contributors, licence, Discover id, describing paper) when a demo dataset is recognised from sc-prep's sample paths |

A section whose inputs are present but unreadable is reported at the top of the page and in
`provenance.json` (`sectionErrors`); the rest is still rendered.

### Citations

A step's `provenance.json` may cite a bare DOI (as `conventions.md` describes) or an object
`{doi, pmid, text}` (as sc-integrate and sc-markers write). Each DOI is looked up in
`processor/references.json`, which `scripts/verify_citations.py` wrote from Crossref, PubMed,
DataCite and the Discover API. The page shows the verified record, marked ✓. A DOI the table
does not hold is shown with the step's own text, marked "as given by the step". st-compare
(reused unchanged from the spatial suite) writes no citations, so its methods papers come from
`processor/citations.py`. When an upstream app adds a reference, re-run
`scripts/verify_citations.py` with its DOI added, so the report shows it verified.

## Ports

Inputs, all `placement: subfolder` and none required: `metadata`, `qc`, `integration`,
`annotation`, `markers`, `compare`, `atac`, `regulome` (see `sample-input/README.md` for which
upstream output goes where). `markers`, `compare` and `regulome` may each receive several links,
one `<LABEL>/` folder each. Symlinks are followed only to where the platform's own entries point;
a deeper link that resolves outside `INPUT_DIR` is skipped and listed in `provenance.json`.
Untrusted content is handled as data:

- every value is HTML-escaped by Jinja2's autoescape;
- a figure is inlined only if it starts with the PNG signature and is at most 8 MB;
- JSON files over 20 MB and CSV files over 2 GB are not read.

Outputs (two, so each in `OUTPUT_DIR/<name>/`):

| Output | Files |
|---|---|
| `report` | `index.html` (self-contained), `provenance.json` |
| `tables` | the CSVs below (each only when its section has inputs), `summary.json`, `provenance.json` |

| Table | Columns |
|---|---|
| `samples.csv` | sc-prep's `samples.csv` as read, without `path` |
| `qc.csv` | sc-qc's per-sample table |
| `clusters.csv` | sc-integrate's `cluster_summary.csv` |
| `composition.csv` | `sample_id, <label column>, n_cells, fraction, condition` |
| `composition_by_condition.csv` | `condition, <label column>, mean_fraction` |
| `markers_top.csv` | `label_set, label, n_cells, n_samples, n_markers, dropped_inconsistent, top markers` |
| `composition_tests.csv`, `de_summary.csv`, `de_top_genes.csv` | st-compare's rows + `label_set`; significance at the report's `FDR` |
| `atac_qc.csv` | `sample_id, n_removed` |
| `methods.csv`, `citations.csv` | per step run: `app, step, version, tools, parameters, citations`; per reference: `number, text, doi, pmid, verified_by_report` |
| `summary.json` | per section: observations, caveats, headline numbers; workflows detected; citations; data credit |

Exit codes: `0` success; `1` none of the inputs found; `2` bad parameter.

## Parameters

| Name | Default | What it does |
|---|---|---|
| `REPORT_TITLE` | `Single-cell Report` | Title of the page (escaped; at most 200 characters). |
| `FDR` | `0.05` | Threshold the report applies to st-compare's adjusted p-values when it counts and lists significant composition changes and DE genes. Display only. |
| `MAX_ITEMS` | `20` | Rows per top-N table and per table preview. |
| `MAX_FIGURES` | `12` | Figures inlined per section (per `<LABEL>` for markers, comparisons and regulation); the page says how many more the upstream output holds. |

## Results on the demo data

Run on what existed of drg-c2 when this was written (Discover 475): sc-prep's `metadata`
output, plus an sc-markers run on sc-prep's cells with stand-in k-means clusters (see
sc-markers' README). sc-qc, sc-integrate and sc-annotate outputs did not exist yet, so the QC,
cluster, cell-type and comparison sections were exercised on the synthetic fixture only.

- **Samples:** 12 samples, 20,415 nuclei (186–3,000 per sample; sc-prep capped at 3,000),
  18,082–18,099 genes, human, Cell Ranger Flex. Conditions from `subject_experimental_group`:
  acute (7) and chronic (5). sc-prep ignored one input entry.
- **Data credit** recognised for all 12 samples: Arendt-Tranholm A, Sankaranarayanan I, Price TJ,
  doi:10.26275/cxuf-ftav, CC BY 4.0, described in *Brain* 2026 (doi:10.1093/brain/awaf370).
- **Markers:** 8 labels, 50 markers each, with dot plot and heatmap inlined (the page is 413 KB).

## Runtime

`cpu: 1024`, `memory: 2048`, `computeTypes: [standard, lambda]` (the image serves both; see
`processor/entry.py` and `processor/handler.py`), timeout 10 min. Measured with `docker run
--memory 3g --cpus 1 --network none --read-only --tmpfs /tmp` under **amd64 emulation on an
M-series Mac**:

| Inputs | Sections | Peak RSS | cgroup peak | Wall time (incl. container start) |
|---|---|---|---|---|
| drg-c2: sc-prep metadata + sc-markers (12 samples, 8 labels) | 2 | 107 MB | 118 MB | 3 s |
| Synthetic fixture, both workflows (labels.csv of 11,820 cells) | 8 | 111 MB (local) | | < 1 s (local) |

Memory does not grow with the number of cells beyond one 500,000-row chunk of three
`labels.csv` columns. Image: 540 MB (`python:3.12.16-slim-bookworm` + pandas, matplotlib,
jinja2, awslambdaric). The page's size is mostly its inlined figures: about 50–300 KB each at
150 dpi, at most `MAX_FIGURES` per section.

## Running it

```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
make test PYTHON=.venv/bin/python           # synthetic fixture: both workflows, each alone, each port alone, none
make run PYTHON=.venv/bin/python            # Docker over data/fixture/linked/ -> data/output/
INPUT_HOST=/path/to/inputs make run         # Docker over your own folder (one subfolder per port)
make validate PYTHON=.venv/bin/python       # app.yml against the manifest schema (+ CITATION.cff with cffconvert)
```

`tests/make_fixture.py` writes contract-following upstream outputs for every port, with planted
findings: a sample losing 45% to QC, a cluster in one sample only, neurons 5% → 15% between
conditions, a significant composition test, a DOI the reference table does not hold, and
st-compare's provenance without citations. The tests also cover:

- the flat layout (upstream folders with uninformative names);
- broken inputs: invalid JSON, a non-PNG `.png`, and HTML/script in a metadata value (escaped,
  never executed);
- a symlink escaping `INPUT_DIR`;
- `MAX_FIGURES`, bad parameters, no inputs, and the Lambda handler.

## Limitations

- **Only as good as the upstream outputs.** The report re-thresholds and cross-references; it
  takes every statistic as the steps wrote it. A caveat on the page restates an app's own
  limitation; it is not a new test.
- **Descriptive composition.** Shares per condition are means over samples; the test of a
  change is st-compare's, shown in the comparison section.
- **Unknown formats are shown generically.** sc-qc, sc-annotate, atac-prep and atac-regulome were
  being built at the same time as this app. Their sections show summary numbers, status, tables
  and figures, with dedicated sentences only where the contract fixes the format (QC counts are
  read from `n_<cells|obs|nuclei>_before/after` and `n_removed_<reason>` columns).
- **Demo-dataset credit** is recognised from sc-prep's sample paths, and only for drg-c2 today
  (`sub-UTD-CC…`). drg-atlas (Discover 480) and the sympathetic multiome (Discover 465) are
  verified in `references.json`, but their sample paths are not matched yet. Other data get no
  credit line: cite your data yourself.
- Static PNG figures, light theme, English only.
- **Shared template with st-report.** The two reports share the page's CSS, the
  methods/citations machinery and `verify_citations.py`. A shared package would be simpler once
  a third report exists; for now each is self-contained, and changes to one should be copied to
  the other.

## Licences

Our code: Apache-2.0 (`LICENSE`). Bundled components and their licences: `THIRD_PARTY.md` (all
permissive; no GPL code in the image).

## Credits

The report shows other people's work: each step's methods (cited per step on the page) and the
data. Its own dependencies:

- **Heumos et al.** and the Single-cell Best Practices Consortium wrote the guide whose caveats
  the report restates.
- **Matplotlib** (Hunter) draws the composition figure; **pandas** and **Jinja2** (Pallets) build
  the tables and the page.
- Demo data: **Arendt-Tranholm A, Sankaranarayanan I and Price TJ** shared the drg-c2 single-nucleus data (Discover 475, CC BY 4.0).
- **Sankaranarayanan I and Price TJ** shared the DRG atlas (Discover 480, CC BY 4.0).
- **Yang L and Gereau RW** shared the sympathetic ganglia
  multiome atlas (Discover 465, CC BY 4.0).

## Citations

`scripts/verify_citations.py` fetched every DOI the report can cite on 2026-10-31:

- **Papers:** Crossref for the title, the full author list in order, journal, year, volume,
  issue and pages; then PubMed (esearch by DOI, then esummary), where title, first author and
  year must match and the PMID is taken from the result.
- **Datasets:** DataCite (title, creators, year, licence) and the Discover API (DOI,
  contributors with ORCID, version, licence).

All 26 papers and 3 datasets are in `CITATION.cff` with author lists as Crossref and Discover
give them, and in `processor/references.json`. The report's own:

- Heumos L, Schaar AC, Lance C, et al. Best practices for single-cell analysis across
  modalities. *Nat Rev Genet* 24(8):550-572 (2023). doi:10.1038/s41576-023-00586-w. PMID 37002403.
- Hunter JD. Matplotlib: A 2D Graphics Environment. *Comput Sci Eng* 9(3):90-95 (2007).
  doi:10.1109/MCSE.2007.55. (Crossref; not in PubMed)

Per step (shown when that step's provenance is among the inputs):

- sc-prep, shared: scanpy (PMID 29409532), anndata (doi:10.21105/joss.04371).
- sc-integrate: Stuart 2019 (PMID 31178118), Harmony (PMID 31740819), scVI (PMID 30504886),
  scvi-tools (PMID 35132262), Leiden (PMID 30914743), UMAP (doi:10.21105/joss.00861), scIB
  (PMID 34949812), Rousseeuw 1987 (doi:10.1016/0377-0427(87)90125-7).
- sc-markers: Wilcoxon 1945 (doi:10.2307/3001968), Mann & Whitney 1947
  (doi:10.1214/aoms/1177730491), Benjamini & Hochberg 1995
  (doi:10.1111/j.2517-6161.1995.tb02031.x), Pullin & McCarthy 2024 (PMID 38409056), Squair 2021
  (PMID 34584091), Zimmerman 2021 (PMID 33531494), Zhang 2019 (PMID 31521605).
- st-compare: PyDESeq2 (PMID 37669147), DESeq2 (PMID 25516281), scCODA (PMID 34824236),
  Aitchison 1982 (doi:10.1111/j.2517-6161.1982.tb01195.x), SciPy (PMID 32015543).

Demo data:

- Arendt-Tranholm A, Sankaranarayanan I, Price TJ. Single nucleus sequencing of human C2 dorsal
  root ganglia tissue from fusion surgeries. Discover 475 v1 (2025). doi:10.26275/cxuf-ftav.
  CC BY 4.0. Described in Arendt-Tranholm A, et al. Transcriptome of the human C2 dorsal root
  ganglia in C1–2 arthrodesis surgery: insight for neck pain. *Brain* 149(4):1349-1364 (2026).
  doi:10.1093/brain/awaf370. PMID 41032656.
- Sankaranarayanan I, Price TJ. Single nucleus sequencing atlas of human dorsal root ganglion.
  Discover 480 v1 (2025). doi:10.26275/9qsp-i8dh. CC BY 4.0.
- Yang L, Gereau R. A single-cell multi-omic atlas of human sympathetic ganglia. Discover 465 v1
  (2025). doi:10.26275/oqxx-si9h. CC BY 4.0.
