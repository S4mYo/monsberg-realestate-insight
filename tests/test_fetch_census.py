import pandas as pd
from scripts.db import derive_zillow_style_name

def test_simple_two_word_metro():
    """A metro name with no hyphens should pass through unchanged."""
    result = derive_zillow_style_name(pd.Series(["Albany, NY"]))
    assert result.iloc[0] == "Albany, NY"
    
def test_hyphenated_metro_name():
    """Multi-city metro name collapse to just the principal city."""
    result = derive_zillow_style_name(pd.Series(["Albany-Schenectady-Troy, NY"]))
    assert result.iloc[0] == "Albany, NY"

def test_hyphenated_state_code():
    """A hyphenated multi-state code (e.g. cross-border metros) keeps
    only the first state."""
    result = derive_zillow_style_name(pd.Series(["Chicago-Naperville-Elgin, IL-IN-WI"]))
    assert result.iloc[0] == "Chicago, IL"

def test_slash_separator_normalized_to_hyphen():
    """Louisville's slash separator is handled the same as a hyphen."""
    result = derive_zillow_style_name(pd.Series(["Louisville/Jefferson County, KY-IN"]))
    assert result.iloc[0] == "Louisville, KY"

def test_multiple_rows_processed_independently():
    """Each row in the Series is transformed independently."""
    input_names = pd.Series([
        "Albany-Schenectady-Troy, NY",
        "Austin-Round Rock-San Marcos, TX",
    ])
    result = derive_zillow_style_name(input_names)
    assert result.tolist() == ["Albany, NY", "Austin, TX"]