"""End-to-end tests on synthetic upstream outputs (tests/make_fixture.py), no Docker."""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pandas as pd
import pytest

from tests.make_fixture import UNKNOWN_DOI, make_fixture

PARAMS = ("REPORT_TITLE", "FDR", "MAX_ITEMS", "MAX_FIGURES")


@pytest.fixture(scope="session")
def fixtures(tmp_path_factory):
    out = {}
    for wf in ("ab", "a", "b"):
        root = tmp_path_factory.mktemp(f"fixture-{wf}")
        out[wf] = make_fixture(root, "both", wf)
    return out


def run(input_dir: Path, output_dir: Path, monkeypatch, **params) -> int:
    for k in PARAMS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("INPUT_DIR", str(input_dir))
    monkeypatch.setenv("OUTPUT_DIR", str(output_dir))
    for k, v in params.items():
        monkeypatch.setenv(k, str(v))
    from processor.main import main

    return main()


def page(out: Path) -> str:
    return (out / "report" / "index.html").read_text()


@pytest.mark.parametrize("layout", ["linked", "flat"])
def test_both_workflows(fixtures, tmp_path, monkeypatch, layout):
    assert run(fixtures["ab"][layout], tmp_path, monkeypatch) == 0
    html = page(tmp_path)
    for anchor in ("samples", "qc", "clusters", "celltypes", "markers", "compare", "atac", "regulome", "methods",
                   "citations", "data"):
        assert f'id="{anchor}"' in html, anchor
    # Self-contained: no scripts, nothing loaded from elsewhere; links to doi.org are plain anchors.
    assert "<script" not in html.lower()
    assert not re.search(r'(src|href)="(?!data:image/png;base64,|#|https://doi\.org/)', html)
    assert html.count('src="data:image/png;base64,') >= 8
    s = json.loads((tmp_path / "tables" / "summary.json").read_text())
    assert s["workflows"] == ["Single-nucleus Atlas Mapping & Condition Comparison", "Multiome Gene Regulation"]
    assert not s["sectionErrors"]
    qc = " ".join(s["qc"]["observations"])
    assert "s3 lost more than the others" in qc and "doublet" in qc
    assert any("C05" in o for o in s["clusters"]["observations"])
    assert any("Neuron 5.4% in control vs 15% in pain" in o for o in s["cellTypes"]["observations"])
    assert any("Neuron (adj. p 0.01)" in o for o in s["comparison"][0]["observations"])
    assert any("80 cells" in o for o in s["atac"]["observations"])
    assert s["regulome"][0]["observations"] == ["atac-regulome: one label had too few cells"]
    # Citations: gathered from every provenance, deduplicated, st-compare's from the fallback list.
    cites = {c["doi"]: c for c in s["citations"]}
    assert len(cites) == len(s["citations"])
    assert cites["10.1186/s13059-017-1382-0"]["verifiedByReport"]          # cited by three steps, listed once
    assert cites["10.1093/bioinformatics/btad547"]["verifiedByReport"]      # st-compare (no citations in provenance)
    assert not cites[UNKNOWN_DOI]["verifiedByReport"] and "Doe J" in cites[UNKNOWN_DOI]["text"]
    assert "10.1038/s41576-023-00586-w" in cites                           # the report's own
    assert s["inputData"][0]["doi"] == "10.26275/cxuf-ftav" and s["inputData"][0]["n_samples"] == 5
    tables = sorted(p.name for p in (tmp_path / "tables").glob("*.csv"))
    assert tables == ["atac_qc.csv", "citations.csv", "clusters.csv", "composition.csv", "composition_by_condition.csv",
                      "composition_tests.csv", "de_summary.csv", "de_top_genes.csv", "markers_top.csv", "methods.csv",
                      "qc.csv", "samples.csv"]
    comp = pd.read_csv(tmp_path / "tables" / "composition.csv")
    assert (comp.groupby("sample_id")["fraction"].sum() - 1).abs().max() < 1e-4
    assert {"sc-prep", "sc-qc", "sc-integrate", "sc-annotate", "sc-markers", "st-compare", "atac-prep", "atac-regulome",
            "sc-report"} == set(pd.read_csv(tmp_path / "tables" / "methods.csv")["app"])


def test_workflow_a_only(fixtures, tmp_path, monkeypatch):
    assert run(fixtures["a"]["linked"], tmp_path, monkeypatch) == 0
    html = page(tmp_path)
    assert 'id="markers"' in html and 'id="atac"' not in html and 'id="regulome"' not in html
    s = json.loads((tmp_path / "tables" / "summary.json").read_text())
    assert s["workflows"] == ["Single-nucleus Atlas Mapping & Condition Comparison"]


def test_workflow_b_only(fixtures, tmp_path, monkeypatch):
    assert run(fixtures["b"]["linked"], tmp_path, monkeypatch) == 0
    html = page(tmp_path)
    assert 'id="atac"' in html and 'id="regulome"' in html and 'id="markers"' not in html


def test_each_port_alone(fixtures, tmp_path, monkeypatch):
    src = fixtures["ab"]["linked"]
    for port in ("metadata", "qc", "integration", "annotation", "markers", "compare", "atac", "regulome"):
        inp = tmp_path / port / "in"
        shutil.copytree(src / port, inp / port)
        assert run(inp, tmp_path / port / "out", monkeypatch) == 0, port
        s = json.loads((tmp_path / port / "out" / "tables" / "summary.json").read_text())
        assert not s["sectionErrors"], port


def test_broken_inputs_do_not_sink_the_report(fixtures, tmp_path, monkeypatch):
    inp = tmp_path / "in"
    shutil.copytree(fixtures["ab"]["linked"], inp)
    (inp / "integration" / "summary.json").write_text("{not json")
    (inp / "integration" / "umap_cluster.png").write_text("<svg onload=alert(1)>")      # not a PNG: not inlined
    (inp / "qc" / "qc_summary.csv").write_text('sample_id,n_cells_before\n"s1,<b>x</b>",3\n')
    md = inp / "metadata" / "samples.csv"
    df = pd.read_csv(md)
    df.loc[0, "sex"] = "<script>alert(1)</script>"
    df.to_csv(md, index=False)
    assert run(inp, tmp_path / "out", monkeypatch) == 0
    html = page(tmp_path / "out")
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "onload" not in html


def test_symlink_escaping_input_is_skipped(fixtures, tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    shutil.copytree(fixtures["ab"]["linked"] / "markers", outside)
    inp = tmp_path / "in"
    shutil.copytree(fixtures["a"]["linked"] / "metadata", inp / "metadata")
    (inp / "metadata" / "deep").mkdir()
    os.symlink(outside, inp / "metadata" / "deep" / "link")
    assert run(inp, tmp_path / "out", monkeypatch) == 0
    prov = json.loads((tmp_path / "out" / "report" / "provenance.json").read_text())
    assert prov["inputs"]["markers"] == [] and prov["inputs"]["skipped"]


def test_nothing_found_and_bad_parameters(fixtures, tmp_path, monkeypatch):
    (tmp_path / "empty").mkdir()
    assert run(tmp_path / "empty", tmp_path / "out", monkeypatch) == 1
    src = fixtures["ab"]["linked"]
    assert run(src, tmp_path / "out", monkeypatch, FDR="2") == 2
    assert run(src, tmp_path / "out", monkeypatch, MAX_ITEMS="0") == 2
    assert run(src, tmp_path / "out", monkeypatch, MAX_FIGURES="x") == 2


def test_max_figures(fixtures, tmp_path, monkeypatch):
    assert run(fixtures["ab"]["linked"], tmp_path, monkeypatch, MAX_FIGURES=1, REPORT_TITLE="DRG <C2>") == 0
    html = page(tmp_path)
    assert "more figure(s) not shown" in html and "<title>DRG &lt;C2&gt;</title>" in html


def test_handler(fixtures, tmp_path, monkeypatch):
    for k in PARAMS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FDR", "0.5")          # must be cleared by the handler
    from processor.handler import handler

    r = handler({"inputDir": str(fixtures["a"]["linked"]), "outputDir": str(tmp_path), "MAX_ITEMS": 5}, None)
    assert r["status"] == "ok"
    s = json.loads((tmp_path / "tables" / "summary.json").read_text())
    assert s["parameters"]["FDR"] == 0.05 and s["parameters"]["MAX_ITEMS"] == 5
    with pytest.raises(RuntimeError):
        handler({"inputDir": str(fixtures["a"]["linked"]), "outputDir": str(tmp_path), "FDR": "nope"}, None)
