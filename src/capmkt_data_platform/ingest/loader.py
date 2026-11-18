from dataclasses import dataclass


@dataclass(frozen=True)
class LoadResult:
    load_id: int
    status: str  # SUCCESS | FAILED | NO_FILE
    rows_loaded: int | None
    error: str | None


def load_day(audit_conn, data_conn, dataset, cfg, download_result) -> LoadResult: ...
def record_no_file(audit_conn, dataset, download_result) -> LoadResult: ...
