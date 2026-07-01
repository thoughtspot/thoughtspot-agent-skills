import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from ts_cli.audit.test_fixtures import generate_test_data
from ts_cli.audit.report import compact_payload, render_report


def test_compact_payload_has_required_keys():
    data = generate_test_data()
    payload = compact_payload(data)
    assert "L" in payload
    assert "F" in payload
    assert "S" in payload


def test_compact_payload_with_corpus():
    data = generate_test_data(include_corpus=True)
    payload = compact_payload(data)
    assert "C" in payload
    assert "u" in payload["C"]  # cluster_url
    assert "m" in payload["C"]  # models


def test_compact_payload_without_corpus():
    data = generate_test_data(include_corpus=False)
    payload = compact_payload(data)
    assert "C" not in payload or payload["C"] is None


def test_compact_payload_findings_use_short_keys():
    data = generate_test_data(model_count=2, findings_per_model=3)
    payload = compact_payload(data)
    first = payload["F"][0]
    assert "ci" in first  # check_id
    assert "s" in first   # severity
    assert "d" in first   # detail


def test_compact_payload_deduplicates_models():
    data = generate_test_data(model_count=3, findings_per_model=5)
    payload = compact_payload(data)
    for f in payload["F"]:
        assert isinstance(f["mi"], int)  # model index into L


def test_render_report_replaces_placeholder():
    data = generate_test_data(model_count=2, findings_per_model=3)
    html = render_report(data)
    assert "{{AUDIT_DATA}}" not in html


def test_render_report_no_external_resources():
    data = generate_test_data()
    html = render_report(data)
    external_refs = re.findall(
        r'(?:src|href)\s*=\s*["\']https?://(?!demo\.thoughtspot\.cloud)',
        html,
    )
    assert external_refs == [], f"Found external refs: {external_refs}"


def test_render_report_contains_valid_json_payload():
    data = generate_test_data()
    html = render_report(data)
    match = re.search(
        r'<script[^>]*id="audit-data"[^>]*>(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match, "No <script id='audit-data'> found"
    parsed = json.loads(match.group(1))
    assert "F" in parsed


def test_render_report_size_under_1mb():
    data = generate_test_data(model_count=100, findings_per_model=10)
    html = render_report(data)
    size_bytes = len(html.encode("utf-8"))
    assert size_bytes < 1_048_576, f"Report is {size_bytes} bytes, exceeds 1MB"


def test_render_report_empty_findings():
    data = generate_test_data(model_count=1, findings_per_model=0)
    data["findings"] = []
    html = render_report(data)
    assert "{{AUDIT_DATA}}" not in html


def test_render_report_no_corpus_graceful():
    data = generate_test_data(include_corpus=False)
    html = render_report(data)
    assert "{{AUDIT_DATA}}" not in html


def test_report_cli_from_file():
    data = generate_test_data(model_count=2, findings_per_model=3)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(data, f)
        f.flush()
        input_path = f.name
    output_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as out:
            output_path = out.name
        result = subprocess.run(
            [sys.executable, "-m", "ts_cli.cli", "audit", "report", input_path,
             "-o", output_path],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent),
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        html = Path(output_path).read_text()
        assert "{{AUDIT_DATA}}" not in html
        assert len(html) > 100
    finally:
        os.unlink(input_path)
        if output_path and os.path.exists(output_path):
            os.unlink(output_path)
