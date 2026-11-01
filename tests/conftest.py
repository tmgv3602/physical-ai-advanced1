"""Collect requirement IDs from @pytest.mark.req and write results/ci/unit_tests.json.

The matrix builder reads that file, so each unit test is traceable to the
requirements it verifies.
"""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_records = []


def pytest_configure(config):
    config.addinivalue_line("markers", "req(*ids): requirement IDs verified by this test")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.skipped:
        return
    if rep.when == "call" or (rep.when == "setup" and rep.failed):
        reqs = [a for m in item.iter_markers("req") for a in m.args]
        _records.append({
            "kind": "unit",
            "test_id": item.nodeid,
            "req": reqs,
            "passed": rep.passed,
            "detail": "" if rep.passed else str(rep.longrepr).splitlines()[-1][:300],
        })


def pytest_sessionfinish(session, exitstatus):
    out = ROOT / "results" / "ci" / "unit_tests.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"source": "pytest", "meta": {}, "records": _records},
                              ensure_ascii=False, indent=1), encoding="utf-8")
