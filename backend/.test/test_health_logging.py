import logging

import pytest

from logging_filters import HealthCheckAccessFilter


@pytest.mark.parametrize("root_path", ["", "/api", "/custom/prefix/"])
@pytest.mark.parametrize("status", [200, 204, 301, 404, 500, 503])
@pytest.mark.parametrize("query", ["", "?probe=docker"])
def test_health_access_log_filter(root_path, status, query):
    path = f"{root_path.rstrip('/')}/system/health-check{query}"
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1234", "GET", path, "1.1", status), None,
    )
    assert HealthCheckAccessFilter(root_path).filter(record) is (not 200 <= status < 300)


@pytest.mark.parametrize(
    "args",
    [
        ("local", "GET", "/inventory/", "1.1", 200),
        ("local", "POST", "/system/health-check", "1.1", 200),
        ("local", "GET", "/system/health-check-other", "1.1", 200),
        ("local", "GET", "/other/system/health-check", "1.1", 200),
        ("local", "GET", "/system/health-check", "1.1", "200"),
        (),
        ("unexpected",),
    ],
)
def test_non_health_and_unrecognized_records_remain_visible(args):
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "message", args, None)
    assert HealthCheckAccessFilter("/api").filter(record)


def test_filter_keeps_errors_in_actual_logger(caplog):
    logger = logging.getLogger("uvicorn.access")
    access_filter = HealthCheckAccessFilter("/api")
    logger.addFilter(access_filter)
    try:
        with caplog.at_level(logging.INFO, logger="uvicorn.access"):
            for path, status in [
                ("/api/system/health-check", 200),
                ("/system/health-check", 200),
                ("/api/system/health-check", 503),
                ("/inventory/", 200),
            ]:
                logger.info(
                    '%s - "%s %s HTTP/%s" %d',
                    "127.0.0.1:1234", "GET", path, "1.1", status,
                )
        assert [record.args[4] for record in caplog.records] == [503, 200]
    finally:
        logger.removeFilter(access_filter)
