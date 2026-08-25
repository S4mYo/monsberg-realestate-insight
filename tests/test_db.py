import pandas as pd
from scripts.db import get_new_rows


def test_returns_only_rows_not_in_existing():
    """Rows already present (matching on key_columns) are excluded."""
    incoming = pd.DataFrame({
        "metro_id": [1, 1, 2],
        "date": ["2026-06-30", "2026-07-31", "2026-07-31"],
        "value": [100, 101, 200],
    })
    existing = pd.DataFrame({
        "metro_id": [1],
        "date": ["2026-06-30"],
    })

    result = get_new_rows(incoming, existing, key_columns=["metro_id", "date"])

    assert len(result) == 2
    assert set(result["date"]) == {"2026-07-31"}


def test_returns_everything_when_existing_is_empty():
    """A first-ever run (empty existing table) should insert all rows."""
    incoming = pd.DataFrame({
        "metro_id": [1, 2],
        "date": ["2026-07-31", "2026-07-31"],
        "value": [100, 200],
    })
    existing = pd.DataFrame({"metro_id": [], "date": []})

    result = get_new_rows(incoming, existing, key_columns=["metro_id", "date"])

    assert len(result) == 2


def test_returns_nothing_when_all_rows_already_exist():
    """A re-run with no new data should insert zero rows."""
    incoming = pd.DataFrame({
        "metro_id": [1],
        "date": ["2026-06-30"],
        "value": [100],
    })
    existing = pd.DataFrame({
        "metro_id": [1],
        "date": ["2026-06-30"],
    })

    result = get_new_rows(incoming, existing, key_columns=["metro_id", "date"])

    assert len(result) == 0