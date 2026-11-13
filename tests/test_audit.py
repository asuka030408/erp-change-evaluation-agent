from erp_change_agent.audit import AuditLog, report_hash


def test_audit_appends_events_without_overwrite(tmp_path):
    log = AuditLog(tmp_path / "audit.sqlite")
    try:
        log.append("run-1", "TENANT-XH", "assessment_started", {"model": "deepseek-flash"})
        log.append("run-1", "TENANT-XH", "report_ready", {"report_sha256": report_hash("report")})
        assert [item["event_type"] for item in log.events("run-1")] == ["assessment_started", "report_ready"]
        assert log.events("other") == []
    finally:
        log.close()
