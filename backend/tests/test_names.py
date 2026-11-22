import pytest

from app.services.onboarding.names import (
    name_variants,
    normalize_name,
    round_names_firm,
    split_investors,
)


def test_split_and_normalize() -> None:
    assert split_investors("Accel, Angel Collective (lead); Tiger Global") == [
        "Accel", "Angel Collective (lead)", "Tiger Global",
    ]
    assert normalize_name("  Accel  (Lead) ") == "accel"
    assert normalize_name("Accel-KKR") == "accel-kkr"
    assert split_investors(None) == []


@pytest.mark.parametrize(
    ("round_investors", "expected"),
    [
        ("Lightspeed Venture Partners, Accel", "Accel"),
        ("Accel-KKR, Tiger Global Management", None),  # lookalike never matches
        ("Accel India, Elevation", None),  # a different investor record
        ("accel (lead) ,  Angel Collective", "accel (lead)"),
        ("", None),
    ],
)
def test_round_matching_is_exact(round_investors: str, expected: str | None) -> None:
    assert round_names_firm(round_investors, {"Accel"}) == expected


def test_rebrand_matches_either_confirmed_name() -> None:
    names = {"Peak XV Partners", "Sequoia Capital India"}
    assert round_names_firm("Sequoia Capital India, Blume Ventures", names)
    assert round_names_firm("Peak XV Partners", names)
    assert round_names_firm("Sequoia Capital", names) is None


def test_name_variants() -> None:
    assert name_variants("Blume Ventures", "blume.vc") == ["Blume Ventures", "blume"]
    assert name_variants("Accel", "https://www.accel.com") == ["Accel"]
    assert name_variants("Peak XV Partners") == ["Peak XV Partners", "peak xv"]
