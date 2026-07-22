import tempfile
import unittest
from datetime import date
from pathlib import Path

import config
from appointment_monitor.api_client import AppointmentApiError
from appointment_monitor.database import Database
from appointment_monitor.monitor import AppointmentMonitor


class FakeApi:
    def __init__(self, batches):
        self.batches = list(batches)
        self.current = None
        self.calls = []

    def fetch_dates(self, branch_id):
        if self.current is None:
            self.current = self.batches.pop(0)
        self.calls.append(branch_id)
        value = self.current[branch_id]
        if isinstance(value, Exception):
            raise value
        return [date.fromisoformat(item) for item in value]


def run_batch(api, db):
    monitor = AppointmentMonitor(db, api, request_delay_seconds=0)
    api.current = None
    return monitor.run_check()


def branch_ids(db):
    return {row["key"]: row["branch_id"] for row in db.offices()}


def dates_for(ids, johvi, parnu, tallinn, tartu):
    return {
        ids["johvi"]: johvi,
        ids["parnu"]: parnu,
        ids["tallinn"]: tallinn,
        ids["tartu"]: tartu,
    }


def event_types(db):
    return [row["event_type"] for row in db.recent_events(limit=100)]


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tempdir.name) / "test.sqlite3"
        self.db = Database(self.db_path)
        self.ids = branch_ids(self.db)

    def tearDown(self):
        self.db.conn.close()
        self.tempdir.cleanup()

    def test_first_run_sets_baseline_without_alarm(self):
        api = FakeApi([dates_for(self.ids, ["2026-09-21"], ["2026-09-18"], ["2026-09-25"], ["2026-09-20"])])
        outcome = run_batch(api, self.db)
        self.assertEqual(outcome.overall_earliest_date, date(2026, 9, 18))
        self.assertFalse(outcome.alarm_triggered)
        self.assertEqual(event_types(self.db), [])

    def test_tallinn_branch_id_matches_browser_request(self):
        self.assertEqual(
            self.ids["tallinn"],
            "89f89ac30f7f6329397e447102ce1ed13e5459eaa5a630c071d0577bdae6600a",
        )
        self.assertEqual(
            next(office.branch_id for office in config.OFFICES if office.key == "tallinn"),
            self.ids["tallinn"],
        )

    def test_overall_improves_triggers_one_alarm_no_duplicate(self):
        api = FakeApi([
            dates_for(self.ids, ["2026-09-21"], ["2026-09-18"], ["2026-09-25"], ["2026-09-20"]),
            dates_for(self.ids, ["2026-09-21"], ["2026-09-12"], ["2026-09-25"], ["2026-09-20"]),
            dates_for(self.ids, ["2026-09-21"], ["2026-09-12"], ["2026-09-25"], ["2026-09-20"]),
        ])
        run_batch(api, self.db)
        improved = run_batch(api, self.db)
        same = run_batch(api, self.db)
        self.assertTrue(improved.alarm_triggered)
        self.assertFalse(same.alarm_triggered)
        self.assertEqual(event_types(self.db).count("NEW_EARLIER_OVERALL"), 1)

    def test_overall_later_logs_without_alarm(self):
        api = FakeApi([
            dates_for(self.ids, ["2026-09-21"], ["2026-09-18"], ["2026-09-25"], ["2026-09-20"]),
            dates_for(self.ids, ["2026-09-21"], ["2026-09-28"], ["2026-09-25"], ["2026-09-20"]),
        ])
        run_batch(api, self.db)
        later = run_batch(api, self.db)
        self.assertFalse(later.alarm_triggered)
        self.assertIn("EARLIEST_DISAPPEARED", event_types(self.db))

    def test_office_improves_but_overall_unchanged_no_alarm(self):
        api = FakeApi([
            dates_for(self.ids, ["2026-09-21"], ["2026-09-18"], ["2026-09-25"], ["2026-09-20"]),
            dates_for(self.ids, ["2026-09-19"], ["2026-09-18"], ["2026-09-25"], ["2026-09-20"]),
        ])
        run_batch(api, self.db)
        outcome = run_batch(api, self.db)
        self.assertFalse(outcome.alarm_triggered)
        self.assertIn("OFFICE_EARLIER", event_types(self.db))

    def test_one_request_fails_is_not_empty_and_others_continue(self):
        api = FakeApi([
            dates_for(self.ids, ["2026-09-21"], ["2026-09-18"], ["2026-09-25"], ["2026-09-20"]),
            dates_for(self.ids, ["2026-09-21"], ["2026-09-18"], AppointmentApiError("timeout"), ["2026-09-20"]),
        ])
        run_batch(api, self.db)
        outcome = run_batch(api, self.db)
        self.assertEqual(outcome.overall_earliest_date, date(2026, 9, 18))
        self.assertTrue(any(not result.success and result.name == "Tallinn Service Office" for result in outcome.results))
        self.assertIn("REQUEST_ERROR", event_types(self.db))
        self.assertEqual(api.calls[-4:], [self.ids["johvi"], self.ids["parnu"], self.ids["tallinn"], self.ids["tartu"]])

    def test_failed_office_with_previous_earliest_is_preserved(self):
        api = FakeApi([
            dates_for(self.ids, ["2026-09-21"], ["2026-09-18"], ["2026-09-12"], ["2026-09-20"]),
            dates_for(self.ids, ["2026-09-21"], ["2026-09-18"], AppointmentApiError("timeout"), ["2026-09-20"]),
        ])
        run_batch(api, self.db)
        outcome = run_batch(api, self.db)
        self.assertEqual(outcome.overall_earliest_date, date(2026, 9, 12))
        self.assertFalse(outcome.alarm_triggered)
        self.assertNotIn("EARLIEST_DISAPPEARED", event_types(self.db))

    def test_all_requests_fail_preserves_previous_overall(self):
        error_batch = {branch_id: AppointmentApiError("down") for branch_id in self.ids.values()}
        api = FakeApi([
            dates_for(self.ids, ["2026-09-21"], ["2026-09-18"], ["2026-09-25"], ["2026-09-20"]),
            error_batch,
        ])
        run_batch(api, self.db)
        outcome = run_batch(api, self.db)
        self.assertEqual(outcome.overall_earliest_date, date(2026, 9, 18))
        self.assertFalse(outcome.alarm_triggered)
        self.assertTrue(outcome.status_message.startswith("All requests failed"))

    def test_empty_successful_result_means_no_appointments_not_error(self):
        api = FakeApi([dates_for(self.ids, [], ["2026-09-18"], [], [])])
        outcome = run_batch(api, self.db)
        self.assertTrue(any(result.success and result.status == "No available appointments" for result in outcome.results))
        self.assertEqual(outcome.overall_earliest_date, date(2026, 9, 18))

    def test_restart_uses_saved_state_for_alarm(self):
        api1 = FakeApi([dates_for(self.ids, ["2026-09-21"], ["2026-09-18"], ["2026-09-25"], ["2026-09-20"])])
        run_batch(api1, self.db)
        self.db.conn.close()
        db2 = Database(self.db_path)
        api2 = FakeApi([dates_for(self.ids, ["2026-09-21"], ["2026-09-12"], ["2026-09-25"], ["2026-09-20"])])
        outcome = run_batch(api2, db2)
        db2.conn.close()
        self.assertTrue(outcome.alarm_triggered)


if __name__ == "__main__":
    unittest.main()
