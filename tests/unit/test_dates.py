from datetime import datetime, timedelta, timezone

from src.dates import as_utc


def test_a_naive_datetime_is_taken_as_utc():
    result = as_utc(datetime(2026, 1, 1, 12, 0))
    assert result.tzinfo == timezone.utc
    assert result.hour == 12


def test_an_aware_datetime_is_converted_not_just_relabelled():
    plus_two = timezone(timedelta(hours=2))
    result = as_utc(datetime(2026, 1, 1, 12, 0, tzinfo=plus_two))
    assert result == datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
