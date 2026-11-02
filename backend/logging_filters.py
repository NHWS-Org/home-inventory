import logging


class HealthCheckAccessFilter(logging.Filter):
    def __init__(self, root_path: str = ""):
        super().__init__()
        path = "/system/health-check"
        self.paths = {path, f"{root_path.rstrip('/')}{path}"}

    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn passes client, method, path, HTTP version and status separately.
        if not isinstance(record.args, tuple) or len(record.args) != 5:
            return True
        _, method, path, _, status = record.args
        return not (
            method == "GET"
            and isinstance(path, str)
            and path.split("?", 1)[0] in self.paths
            and isinstance(status, int)
            and 200 <= status < 300
        )
