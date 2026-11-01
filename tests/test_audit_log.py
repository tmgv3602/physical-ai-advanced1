import json

import pytest

import audit_log


def _write(path, n=3):
    log = audit_log.AuditLog(str(path))
    for i in range(n):
        log.append({"i": i})
    return path


def _lines(path):
    return path.read_text(encoding="utf-8").splitlines()


@pytest.mark.req("REQ-DAT-001")
def test_intact_chain_verifies(tmp_path):
    p = _write(tmp_path / "log.jsonl")
    assert audit_log.verify(str(p)) == (True, None)


@pytest.mark.req("REQ-DAT-001")
def test_edited_record_is_detected(tmp_path):
    p = _write(tmp_path / "log.jsonl")
    lines = _lines(p)
    rec = json.loads(lines[1]); rec["body"]["i"] = 99; lines[1] = json.dumps(rec)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert audit_log.verify(str(p)) == (False, 1)


@pytest.mark.req("REQ-DAT-001")
def test_deleted_record_is_detected(tmp_path):
    p = _write(tmp_path / "log.jsonl")
    lines = _lines(p)
    del lines[1]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert audit_log.verify(str(p))[0] is False


@pytest.mark.req("REQ-DAT-001")
def test_reopened_log_continues_the_chain(tmp_path):
    p = _write(tmp_path / "log.jsonl", n=2)
    audit_log.AuditLog(str(p)).append({"i": "after-restart"})
    assert audit_log.verify(str(p)) == (True, None)
