import pytest

from capmkt_data_platform.db import connect
from capmkt_data_platform.settings import get_settings

TEST_DB = "capmkt_test"


@pytest.fixture(scope="session")
def test_settings():
    return get_settings().model_copy(update={"pgdatabase": TEST_DB})


@pytest.fixture
def db(test_settings):
    try:
        conn = connect(test_settings)
    except Exception(conn) as exc:  # database not running, or capmkt_test not created
        pytest.skip(f"test database unavailable: {exc}")
    with conn:
        name = conn.execute("select current_database()").fetchone()[0]
        assert name == TEST_DB, f"refusing to run against {name}"
        conn.execute("TRUNCATE raw.bhavcopy_cm, raw.sim_trades")
        conn.execute("DELETE FROM audit.ingestion_log")
        conn.commit()
        yield conn
