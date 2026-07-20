from datetime import date

from metrics.ingestion.domain.watermarks import is_frozen, parse_watermark_date, snapshot_date_range


def test_parse_watermark_date():
    assert parse_watermark_date(None) is None
    assert parse_watermark_date("2026-06-05T12:00:00Z") == date(2026, 6, 5)


def test_snapshot_date_range_first_sync_uses_sprint_start():
    date_from, date_to = snapshot_date_range(
        date(2026, 6, 1), date(2026, 6, 14), None, date(2026, 6, 5)
    )
    assert (date_from, date_to) == (date(2026, 6, 1), date(2026, 6, 5))


def test_snapshot_date_range_incremental_starts_after_watermark():
    date_from, date_to = snapshot_date_range(
        date(2026, 6, 1), date(2026, 6, 14), date(2026, 6, 5), date(2026, 6, 8)
    )
    assert (date_from, date_to) == (date(2026, 6, 6), date(2026, 6, 8))


def test_snapshot_date_range_never_exceeds_sprint_end():
    date_from, date_to = snapshot_date_range(
        date(2026, 6, 1), date(2026, 6, 14), date(2026, 6, 13), date(2026, 7, 1)
    )
    assert (date_from, date_to) == (date(2026, 6, 14), date(2026, 6, 14))


def test_snapshot_date_range_watermark_past_end_clamps_to_end():
    date_from, date_to = snapshot_date_range(
        date(2026, 6, 1), date(2026, 6, 14), date(2026, 6, 14), date(2026, 6, 20)
    )
    assert date_from == date_to == date(2026, 6, 14)


def test_is_frozen_only_applies_to_past_sprints_after_grace():
    assert not is_frozen("current", date(2026, 6, 14), date(2026, 6, 20), grace_days=3)
    assert not is_frozen("past", None, date(2026, 6, 20), grace_days=3)
    assert not is_frozen("past", date(2026, 6, 14), date(2026, 6, 16), grace_days=3)
    assert is_frozen("past", date(2026, 6, 14), date(2026, 6, 18), grace_days=3)
