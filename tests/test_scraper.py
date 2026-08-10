from temu_delisting.scraper import month_before


def test_month_before_normal():
    assert month_before(2026, 8) == (2026, 7)


def test_month_before_january_rolls_back_a_year():
    assert month_before(2026, 1) == (2025, 12)
