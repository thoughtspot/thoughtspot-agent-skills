"""M1: corpus readers, manifest, data dir, literal oracle, redaction and the leak scanner.

Every spreadsheet here is SYNTHETIC — authored in this file — so no third-party data is in
the repo, even as a test fixture. No network.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import zipfile

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "tools" / "ts-cli"))

from fidelity import literal as L  # noqa: E402
from fidelity import redact as RD  # noqa: E402
from fidelity import sources as S  # noqa: E402
from fidelity.cases import check_fixture  # noqa: E402

NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
      'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
      'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
      'xmlns:calcext="urn:org:documentfoundation:names:experimental:calc:xmlns:calcext:1.0"')


def _c(formula=None, vt=None, value=None, text=None, err=False):
    attrs = []
    if formula:
        attrs.append(f'table:formula="{formula}"')
    if vt == "float":
        attrs.append(f'office:value-type="float" office:value="{value}"')
    elif vt == "date":
        attrs.append(f'office:value-type="date" office:date-value="{value}"')
    elif vt == "boolean":
        attrs.append(f'office:value-type="boolean" office:boolean-value="{value}"')
    elif vt == "string":
        attrs.append('office:value-type="string"')
    if err:
        attrs.append('calcext:value-type="error"')
    body = f"<text:p>{text}</text:p>" if text is not None else ""
    return f"<table:table-cell {' '.join(attrs)}>{body}</table:table-cell>"


def _fods(rows: list[list[str]]) -> str:
    trs = "".join(f"<table:table-row>{''.join(r)}</table:table-row>" for r in rows)
    return (f'<?xml version="1.0"?><office:document {NS}><office:body><office:spreadsheet>'
            f'<table:table table:name="Sheet2">{trs}</table:table>'
            "</office:spreadsheet></office:body></office:document>")


HEADER = [_c(vt="string", text="Function"), _c(vt="string", text="Expected"),
          _c(vt="string", text="Correct")]


@pytest.fixture()
def corpus(tmp_path):
    """A synthetic data dir: one fods, one xlsx."""
    rows = [HEADER,
            # r2: literal-only formula
            [_c("of:=SUMTHING(1;2)", "float", "3"), _c(vt="float", value="3"),
             _c("of:=[.A2]=[.B2]", "boolean", "true")],
            # r3: two input cells (K3 number, L3 date) and a ROUND check -> abs tolerance
            [_c("of:=FOO([.K3];[.L3])", "float", "7"), _c(vt="float", value="7"),
             _c("of:=ROUND([.A3];6)=[.B3]", "boolean", "true"),
             "<table:table-cell table:number-columns-repeated=\"7\"/>",
             _c(vt="float", value="2.5"), _c(vt="date", value="2020-01-15")],
            # r4: a range -> skipped
            [_c("of:=SUM([.K3:.K9])", "float", "1"), _c(vt="float", value="1")],
            # r5: expected computed in-sheet -> skipped
            [_c("of:=BAR(1)", "float", "1"), _c("of:=1", "float", "1")],
            # r6: error result, error expected
            [_c("of:=1/0", "string", text="#DIV/0!", err=True), _c(vt="string", text="#DIV/0!")],
            # r7: blank input cell M7
            [_c("of:=[.M7]+1", "float", "1"), _c(vt="float", value="1")],
            # r8: ODF CEILING (not Excel's) -> skipped; r9 the Excel one is kept
            [_c("of:=CEILING(2.5;1)", "float", "3"), _c(vt="float", value="3")],
            [_c("of:=COM.MICROSOFT.CEILING(2.5;1)", "float", "3"), _c(vt="float", value="3")],
            # r10: a named expression -> skipped
            [_c("of:=YEAR(datum)", "float", "1"), _c(vt="float", value="1")],
            # r11: LibreOffice-only error code -> skipped
            [_c("of:=CEIL(1)", "string", text="Err:511", err=True), _c(vt="string", text="Err:511")]]
    lo = tmp_path / "libreoffice" / "mathematical"
    lo.mkdir(parents=True)
    (lo / "synthetic.fods").write_text(_fods(rows))
    poi = tmp_path / "poi"
    poi.mkdir()
    _xlsx(poi / "synthetic.xlsx")
    return tmp_path


def _xlsx(path: pathlib.Path) -> None:
    X = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet = (f'<worksheet xmlns="{X}"><sheetData>'
             '<row r="1"><c r="A1"><v>4</v></c><c r="B1" t="s"><v>0</v></c>'
             '<c r="C1" s="1"><v>43831</v></c></row>'
             '<row r="2"><c r="A2"><f>A1*2</f><v>8</v></c>'
             '<c r="B2" t="str"><f>UPPER(B1)</f><v>ABC</v></c>'
             '<c r="C2" s="1"><f>DATE(2020,1,2)</f><v>43832</v></c>'
             '<c r="D2" t="e"><f>1/0</f><v>#DIV/0!</v></c>'
             '<c r="E2" t="b"><f>A1&gt;3</f><v>1</v></c>'
             '<c r="F2"><f>SUM(A1:A9)</f><v>4</v></c></row></sheetData></worksheet>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{X}" xmlns:r="http://schemas.openxml'
                   'formats.org/officeDocument/2006/relationships"><sheets><sheet name="S1" '
                   'sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" '
                   'Type="x"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/sharedStrings.xml", f'<sst xmlns="{X}"><si><t>abc</t></si></sst>')
        z.writestr("xl/styles.xml", f'<styleSheet xmlns="{X}"><cellXfs><xf numFmtId="0"/>'
                   '<xf numFmtId="14"/></cellXfs></styleSheet>')


def _lo(corpus, row):
    return S.lo_case(S.read_fods(corpus / "libreoffice/mathematical/synthetic.fods"), "Sheet2", row)


# -- sources ----------------------------------------------------------------------------

class TestOpenFormula:
    def test_literal_formula(self, corpus):
        c = _lo(corpus, 2)
        assert c["formula"] == "=SUMTHING(1,2)" and c["inputs"] == []
        assert c["expected"] == {"t": "num", "v": "3"} and c["tolerance"] == {"rel": 1e-12}

    def test_inputs_renamed_to_row_one_and_typed(self, corpus):
        c = _lo(corpus, 3)
        assert c["formula"] == "=FOO(A1,B1)"
        assert [(i["letter"], i["cell"], i["kind"], i["value"]) for i in c["inputs"]] == [
            ("A", "K3", "num", 2.5), ("B", "L3", "date", "2020-01-15")]

    def test_round_check_sets_absolute_tolerance(self, corpus):
        assert _lo(corpus, 3)["tolerance"] == {"abs": 5e-07, "rel": 1e-12}

    @pytest.mark.parametrize("row,reason", [
        (4, "range"), (5, "computed in-sheet"), (8, "ODF semantics"),
        (10, "named expression"), (11, "LibreOffice-specific error")])
    def test_refusals_are_named(self, corpus, row, reason):
        assert reason in _lo(corpus, row)["skip"]

    def test_error_expected(self, corpus):
        c = _lo(corpus, 6)
        assert c["expected"] == {"t": "error", "v": "#DIV/0!"} and "error-expected" in c["flags"]

    def test_blank_input_flagged(self, corpus):
        c = _lo(corpus, 7)
        assert c["inputs"][0]["kind"] == "blank" and "blank-input" in c["flags"]

    def test_excel_ceiling_kept_under_its_excel_name(self, corpus):
        c = _lo(corpus, 9)
        assert c["formula"] == "=CEILING(2.5,1)" and c["functions"] == ["CEILING"]

    def test_case_rows(self, corpus):
        sheets = S.read_fods(corpus / "libreoffice/mathematical/synthetic.fods")
        assert S.lo_case_rows(sheets["Sheet2"]) == list(range(2, 12))

    def test_semicolons_inside_strings_survive(self):
        toks = S.of_tokens('of:=CONCAT("a;b";[.K2])')
        assert S.render(toks, {"K2": "A"}) == '=CONCAT("a;b",A1)'


class TestXlsx:
    def test_cached_values_and_types(self, corpus):
        sheets = S.read_xlsx(corpus / "poi/synthetic.xlsx")
        assert S.xlsx_case(sheets, "S1", "A2")["expected"] == {"t": "num", "v": "8"}
        b2 = S.xlsx_case(sheets, "S1", "B2")
        assert b2["expected"] == {"t": "str", "v": "ABC"} and b2["inputs"][0]["value"] == "abc"
        assert S.xlsx_case(sheets, "S1", "C2")["expected"] == {"t": "date", "v": "2020-01-02"}
        assert S.xlsx_case(sheets, "S1", "D2")["expected"] == {"t": "error", "v": "#DIV/0!"}
        assert S.xlsx_case(sheets, "S1", "E2")["expected"] == {"t": "bool", "v": True}

    def test_range_is_refused(self, corpus):
        sheets = S.read_xlsx(corpus / "poi/synthetic.xlsx")
        assert "range" in S.xlsx_case(sheets, "S1", "F2")["skip"]

    def test_date_styled_input_is_a_date(self, corpus):
        sheets = S.read_xlsx(corpus / "poi/synthetic.xlsx")
        assert S.canon_cell(sheets["S1"]["C1"]) == {"t": "date", "v": "2020-01-01"}

    def test_serials_before_march_1900_are_not_dates(self):
        assert S.serial_to_date(60) is None and S.serial_to_date(61).isoformat() == "1900-03-01"


# -- data dir and manifest -------------------------------------------------------------------

def _entry(corpus, **over):
    p = "libreoffice/mathematical/synthetic.fods"
    e = {"id": "lo-x-r3", "source": "libreoffice", "path": p,
         "sha256": L.sha256(corpus / p), "locator": {"sheet": "Sheet2", "row": 3},
         "functions": ["FOO"], "crosscheck": "agree", "flags": []}
    e.update(over)
    return e


class TestDataDir:
    def test_refuses_a_dir_inside_the_repo(self):
        with pytest.raises(L.DataError, match="inside the repo"):
            L.resolve_data_dir(str(HERE), REPO)

    def test_env_var(self, corpus, monkeypatch):
        monkeypatch.setenv(L.DATA_DIR_ENV, str(corpus))
        assert L.resolve_data_dir(None, REPO) == corpus.resolve()

    def test_missing(self, monkeypatch):
        monkeypatch.delenv(L.DATA_DIR_ENV, raising=False)
        with pytest.raises(L.DataError, match="no data dir"):
            L.resolve_data_dir(None, REPO)


class TestManifest:
    def test_round_trip(self, corpus):
        line = L.manifest_line(_entry(corpus))
        assert L.parse_manifest(line)[0]["id"] == "lo-x-r3"

    @pytest.mark.parametrize("over,msg", [
        ({"path": "/etc/passwd"}, "relative"), ({"path": "../x.fods"}, "relative"),
        ({"source": "excel-docs"}, "unknown source"), ({"locator": {"sheet": "S"}}, "locator"),
        ({"crosscheck": "maybe"}, "crosscheck"), ({"sha256": "abc"}, "sha256")])
    def test_rejects(self, corpus, over, msg):
        with pytest.raises(L.DataError, match=msg):
            L.parse_manifest(json.dumps(_entry(corpus, **over)))

    def test_duplicate_id(self, corpus):
        line = json.dumps(_entry(corpus))
        with pytest.raises(L.DataError, match="duplicate"):
            L.parse_manifest(line + "\n" + line)

    def test_sha_mismatch_is_loud(self, corpus):
        cache = L.SourceCache(corpus.resolve())
        with pytest.raises(L.DataError, match="does not match"):
            L.extract(_entry(corpus, sha256="0" * 64), cache)


class TestMaterialise:
    def test_cases_fixture_and_oracle(self, corpus):
        cache = L.SourceCache(corpus.resolve())
        entries = [_entry(corpus), _entry(corpus, id="lo-x-r7", locator={"sheet": "Sheet2", "row": 7}),
                   _entry(corpus, id="lo-x-r4", locator={"sheet": "Sheet2", "row": 4})]
        cases, fx, broken = L.materialise(entries, cache)
        check_fixture(fx)
        assert [b["id"] for b in broken] == ["lo-x-r4"]
        c3, c7 = cases
        assert c3["source_formula"] == "=FOO(A1,B1)" and c3["inputs"] == {"A": "X1", "B": "X2"}
        assert fx["rows"] == [{"ROW_ID": 1, "X_BLANK": None, "X1": 2.5, "X2": "2020-01-15"}]
        assert c7["inputs"] == {"A": "X_BLANK"}
        assert c7["known_divergence"]["tag"] == "excel-blank-vs-null"
        assert L.literal_oracle(c3)["values"] == {"1": {"t": "num", "v": "7"}}
        ctx = L.column_context(c3, fx, "T")
        assert [(c["source"], c["column"], c["data_type"]) for c in ctx] == [
            ("ROW_ID", "ROW_ID", "INT64"), ("A", "X1", "DOUBLE"), ("B", "X2", "DATE")]

    def test_shared_input_cell_shares_a_column(self, corpus):
        cache = L.SourceCache(corpus.resolve())
        cases, fx, _ = L.materialise([_entry(corpus), _entry(corpus, id="dup")], cache)
        assert cases[0]["inputs"] == cases[1]["inputs"] and len(fx["columns"]) == 4


# -- redaction, classes, leak scanning --------------------------------------------------------

def _full(results):
    return {"run": {"date": "d", "cleanup": {"ts_confirmed_absent": True, "remaining": []}},
            "cases": [{"id": i, "translation": {"status": s, "formula": "secret ( 'x' )"},
                       "oracle": {"values": {"1": {"t": "str", "v": "secret value here"}}},
                       "result": r} for i, s, r in results]}


class TestRedact:
    def test_classes(self):
        mm = {"verdict": "MISMATCH", "mismatch_kinds": ["VALUE_DIFF"], "warned": False}
        assert RD.classify_m1(mm, {}) == RD.SILENT_WRONG
        assert RD.classify_m1({**mm, "warned": True}, {}) == RD.WARNED_WRONG
        assert RD.classify_m1(mm, {"flags": ["blank-input"]}) == RD.DIVERGENCE_BLANK
        assert RD.classify_m1({**mm, "mismatch_kinds": ["ERROR_VS_VALUE"]}, {}) == RD.DIVERGENCE_ERROR
        assert RD.classify_m1({"verdict": "MATCH"}, {}) == "MATCH"

    def test_redacted_run_has_no_formula_or_value(self):
        full = _full([("a", "TRANSLATED", {"verdict": "IMPORT_FAILED", "detail":
                       "Formula addition failed. Formula: f_a, Error: bad 'x' (error_code 14516)"})])
        red = RD.redact_run(full, [{"id": "a", "source": "poi", "functions": ["ROUND"]}],
                            [{"id": "b", "source": "poi"}])
        text = json.dumps(red)
        assert "secret" not in text and "f_a" not in text and "'x'" not in text
        assert "code 14516" in red["cases"][0]["detail"]
        assert red["run"]["summary"]["oracle_disputed"] == 1
        assert RD.scan_committed(text, is_json=True) == []

    def test_report_merge_keeps_hand_written_head(self):
        red = RD.redact_run(_full([("a", "TRANSLATED", {"verdict": "MATCH"})]),
                            [{"id": "a", "source": "poi", "functions": ["ROUND"]}], [])
        gen = RD.build_report(red)
        merged = RD.merge_report("# Title\n\nhand text\n\n" + RD.MARKER + "\nold", gen)
        assert merged.startswith("# Title\n\nhand text") and "old" not in merged
        assert RD.scan_committed(merged) == []


class TestLeakScanner:
    @pytest.mark.parametrize("text", [
        '=CONCATENATE("Quarterly total for ",A2)', "ROUND(1234.5678, 2)",
        "substr ( [T::X_A] , 1 , 8 )", "MID(K2,2,3)", "=" + "IF(" * 3 + "1,2,3)))"])
    def test_flags_copied_formula_text(self, text):
        assert RD.suspicious_calls(text)

    @pytest.mark.parametrize("text", [
        "ROUND with negative digits on a negative half value", "round ( x , 10 )",
        "`floor ( x / s ) * s`", "MID(text, start, n)", "BL-346 (open)"])
    def test_passes_own_words(self, text):
        assert RD.suspicious_calls(text) == []

    def test_forbidden_keys(self):
        assert RD.scan_committed('{"id": "a", "source_formula": "x"}', is_json=True)

    def test_exact_corpus_scan(self):
        cases = [{"id": "a", "source_formula": "=LEFT(A1,25)+1234",
                  "expected": {"values": {"1": {"t": "str", "v": "Purple Walrus Inc"}}}}]
        assert len(RD.leaks_against_corpus("x LEFT(A1,25)+1234 Purple Walrus Inc", cases)) == 2


# -- what is committed ---------------------------------------------------------------------

COMMITTED = sorted([*HERE.glob("cases/excel/*"), *HERE.glob("runs/*excel*"),
                    *(REPO / "docs" / "reviews").glob("*fidelity-m1*")])


@pytest.mark.parametrize("path", COMMITTED, ids=lambda p: p.name)
def test_committed_m1_files_carry_no_corpus_text(path):
    """The repo's M1 files must hold ids, locators, statuses and our own words only."""
    text = path.read_text(encoding="utf-8")
    findings = RD.scan_committed(text, is_json=path.suffix in (".json", ".jsonl"))
    assert findings == [], f"{path.name}: {findings[:5]}"


def test_committed_files_exist():
    names = {p.name for p in COMMITTED}
    assert "m1-manifest.jsonl" in names and any(n.endswith(".md") for n in names)


@pytest.mark.parametrize("path", [
    "formula-fidelity-data/libreoffice/x.fods", "tools/formula-fidelity/data/a.fods",
    "tools/formula-fidelity/data/poi/a.xls", "tools/formula-fidelity/data/poi/a.xlsx",
    "tools/formula-fidelity/runs/2026-10-06-excel-m1-full.json",
    "tools/formula-fidelity/extracted/candidates.jsonl"])
def test_gitignore_guards_the_corpus(path):
    r = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", path])
    if r.returncode == 128:
        pytest.skip("not a git checkout")
    assert r.returncode == 0, f"{path} is not git-ignored"


def test_default_oracle_is_still_the_warehouse():
    import run as m0
    from fidelity import live

    assert m0.Deps(validator=object, warehouse=object).oracle is live.run_oracle
