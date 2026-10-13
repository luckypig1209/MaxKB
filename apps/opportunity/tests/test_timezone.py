from datetime import datetime, timedelta, timezone as datetime_timezone

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from opportunity.serializers.common import model_time
from opportunity.services.progress import ProgressTracker, _parse_started_at


@override_settings(TIME_ZONE='Asia/Shanghai', USE_TZ=True)
class OpportunityTimezoneTests(SimpleTestCase):
    def test_utc_time_serializes_with_shanghai_offset(self):
        value = datetime(2026, 10, 12, 8, 0, tzinfo=datetime_timezone.utc)
        self.assertEqual(model_time(value), '2026-10-12T16:00:00+08:00')

    def test_utc_evening_crosses_into_the_next_shanghai_day(self):
        value = datetime(2026, 10, 12, 16, 0, tzinfo=datetime_timezone.utc)
        self.assertEqual(model_time(value), '2026-10-13T00:00:00+08:00')

    def test_model_time_does_not_rewrite_the_input(self):
        value = datetime(2026, 10, 12, 8, 0, tzinfo=datetime_timezone.utc)
        original = value.isoformat()
        model_time(value)
        self.assertEqual(value.isoformat(), original)
        self.assertIsNone(model_time(None))

    def test_progress_elapsed_uses_the_instant_not_the_display_text(self):
        started = timezone.now() - timedelta(seconds=5)
        parsed = _parse_started_at(model_time(started))
        tracker = ProgressTracker.__new__(ProgressTracker)
        tracker.started_at = parsed
        elapsed = tracker.elapsed_ms()
        self.assertGreaterEqual(elapsed, 4000)
        self.assertLess(elapsed, 20000)
