# sample-input

sc-report consumes the *outputs* of the other single-cell steps (sc-prep, sc-qc, sc-integrate,
sc-annotate, sc-markers, st-compare, atac-prep, atac-regulome), so there is no public file to
download for it directly.

For a local run, generate the synthetic fixture: every port of both workflows, with summary
tables, small PNGs and a per-cell `labels.csv`, but no `.h5ad`.

```sh
make fixture PYTHON=.venv/bin/python               # data/fixture/{linked,flat}/, workflows A and B
make fixture WORKFLOW=a PYTHON=.venv/bin/python    # workflow A only
make run PYTHON=.venv/bin/python                   # the Docker image over data/fixture/linked/
```

For real data, give the report one folder per input port, each a copy of the linked upstream
output:

| sc-report input | Upstream output | Workflow |
|---|---|---|
| `metadata` | sc-prep `metadata` | A, B |
| `qc` | sc-qc's QC output | A |
| `integration` | sc-integrate `integration` | A |
| `annotation` | sc-annotate `labels` | A (and B for the cell types) |
| `markers` | sc-markers (whole output: `<LABEL>/` folders; several runs side by side) | A |
| `compare` | st-compare (whole output: `<LABEL>/`) | A |
| `atac` | atac-prep's QC output | B |
| `regulome` | atac-regulome (whole output: `<LABEL>/`) | B |

```sh
W=../workflow-single-cell/data/work/drg-c2
mkdir -p in && cp -R $W/prep/metadata in/metadata && cp -R $W/markers/markers in/markers   # ... one per port
INPUT_HOST=$PWD/in make run
```

Mount real copies, not symlinks to host paths (they do not resolve inside the container).
