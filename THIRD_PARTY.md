# Third-party components

Our code (`processor/`, `tests/`, `scripts/`) is Apache-2.0 (`LICENSE`). The Docker image bundles:

| Component | Version | Licence |
|---|---|---|
| Debian (bookworm, via `python:3.12.16-slim-bookworm`) | 12 | various free licences (per package, `/usr/share/doc/*/copyright`) |
| CPython | 3.12.16 | PSF License |
| pandas | 3.1.0 | BSD-3-Clause |
| NumPy | 2.5.4 | BSD-3-Clause (bundled OpenBLAS: BSD-3-Clause) |
| Matplotlib | 3.11.2 | Matplotlib License (PSF-based, BSD-compatible); bundles DejaVu fonts (Bitstream Vera / public domain) |
| Jinja2 | 3.1.6 | BSD-3-Clause |
| MarkupSafe | 3.0.4 | BSD-3-Clause |
| contourpy | 1.4.0 | BSD-3-Clause |
| cycler | 0.12.1 | BSD-3-Clause |
| fonttools | 4.68.0 | MIT |
| kiwisolver | 1.5.1 | BSD-3-Clause |
| packaging | 26.3 | Apache-2.0 or BSD-2-Clause |
| Pillow | 13.0.0 | MIT-CMU (HPND) |
| pyparsing | 3.3.3 | MIT |
| python-dateutil | 3.0.0 | Apache-2.0 or BSD-3-Clause |
| six | 1.17.0 | MIT |
| tzdata | 2026.6 | Apache-2.0 |
| awslambdaric | 4.2.3 | Apache-2.0 |
| simplejson (awslambdaric dependency) | 4.2.0 | MIT or AFL-2.1 |
| snapshot-restore-py (awslambdaric dependency) | 1.0.0 | Apache-2.0 |

No GPL code is in the image: the report never imports scanpy, scvi-tools, igraph, leidenalg or
snapatac2; it reads the tables, labels.csv and figures the upstream apps wrote. The PNG figures it inlines
from upstream outputs are data, under the licence of the dataset they show.

`processor/references.json` holds bibliographic metadata (titles, author lists, journals, DOIs,
PMIDs) retrieved from Crossref, DataCite, PubMed and the Pennsieve Discover API by `scripts/verify_citations.py`; such
metadata are facts, not covered by copyright (Crossref and DataCite release their metadata under
CC0).
