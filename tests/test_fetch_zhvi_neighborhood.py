import pandas as pd
from scripts.fetch_zhvi_neighborhood import keep_primary_region_per_name


def test_keeps_lowest_size_rank_when_names_duplicate():
    """When two RegionIDs share the same (RegionName, City, State),
    only the one with the lowest SizeRank should survive."""
    df = pd.DataFrame({
        "RegionID": [114074, 396554],
        "RegionName": ["Cambrian Park", "Cambrian Park"],
        "City": ["San Jose", "San Jose"],
        "State": ["CA", "CA"],
        "SizeRank": [182, 6135],
    })

    result = keep_primary_region_per_name(df)

    assert len(result) == 1
    assert result["RegionID"].iloc[0] == 114074


def test_leaves_unique_names_untouched():
    """Rows with no naming conflict should pass through unchanged."""
    df = pd.DataFrame({
        "RegionID": [1, 2],
        "RegionName": ["Tremont", "Ohio City"],
        "City": ["Cleveland", "Cleveland"],
        "State": ["OH", "OH"],
        "SizeRank": [50, 60],
    })

    result = keep_primary_region_per_name(df)

    assert len(result) == 2