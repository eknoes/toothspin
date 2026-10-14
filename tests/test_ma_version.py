from toothspin.ma import parse_version, too_old


def test_parses_releases_betas_and_dev_builds() -> None:
    assert parse_version("2.10.6") == (2, 10, 6)
    assert parse_version("2.11.0b5") == (2, 11, 0)
    assert parse_version("2.11.0.dev2026101403") == (2, 11, 0)
    assert parse_version("unknown") is None


def test_too_old_below_2_10_2_only() -> None:
    assert too_old("2.9.9") and too_old("2.10.1")
    assert not too_old("2.10.2") and not too_old("2.10.6") and not too_old("2.11.0b5")
    assert not too_old(None)  # unknown: don't nag
