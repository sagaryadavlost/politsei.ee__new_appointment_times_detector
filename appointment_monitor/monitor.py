from __future__ import annotations

import time
from datetime import datetime
from typing import Callable

import config
from appointment_monitor.api_client import AppointmentApiClient, AppointmentApiError
from appointment_monitor.database import Database
from appointment_monitor.models import CheckOutcome, OfficeResult


class AppointmentMonitor:
    def __init__(
        self,
        db: Database,
        api_client: AppointmentApiClient | None = None,
        request_delay_seconds: float = config.OFFICE_REQUEST_DELAY_SECONDS,
        progress_callback: Callable[[str], None] | None = None,
        target_date: datetime | date | None = None,
    ) -> None:
        self.db = db
        self.api_client = api_client or AppointmentApiClient()
        self.request_delay_seconds = request_delay_seconds
        self.progress_callback = progress_callback
        self.target_date = target_date if target_date is not None else config.TARGET_APPOINTMENT_DATE

    def run_check(self) -> CheckOutcome:
        checked_at = datetime.now()
        previous = self.db.latest_successful_state()
        office_rows = self.db.offices()
        results: list[OfficeResult] = []

        for index, office in enumerate(office_rows):
            self._progress(f"Sending request {index + 1} of {len(office_rows)}: {office['name']}")
            try:
                dates = self.api_client.fetch_dates(office["branch_id"])
                results.append(
                    OfficeResult(
                        office_id=office["id"],
                        name=office["name"],
                        address=office["address"],
                        success=True,
                        dates=dates,
                    )
                )
                self._progress(f"{office['name']} succeeded.")
            except AppointmentApiError as exc:
                results.append(
                    OfficeResult(
                        office_id=office["id"],
                        name=office["name"],
                        address=office["address"],
                        success=False,
                        dates=[],
                        error=str(exc),
                    )
                )
                self._progress(f"{office['name']} failed. Continuing with the next office.")
            if self.request_delay_seconds > 0 and index < len(office_rows) - 1:
                self._progress(f"Waiting {int(self.request_delay_seconds)} seconds before the next office request...")
                time.sleep(self.request_delay_seconds)

        last_success_by_office = {
            row["id"]: self.db.latest_success_snapshot_for_office(row["id"]) for row in office_rows
        }
        successful = [result for result in results if result.success]
        overall_date, overall_office_id = self._effective_overall(results, previous["office_dates"])
        if not successful:
            overall_date = previous["overall_date"]
            overall_office_id = previous["overall_office_id"]

        check_id = self.db.insert_check(checked_at, results, overall_date, overall_office_id)
        alarm = self._record_events(checked_at, previous, results, overall_date, overall_office_id, last_success_by_office)

        failures = [result for result in results if not result.success]
        if len(failures) == len(results):
            status = "All requests failed. Previous valid availability was preserved."
        elif failures:
            status = f"{len(failures)} office request failed. Other offices were processed."
        elif previous["check"] is None:
            status = "Initial availability loaded."
        else:
            status = "All systems operational."

        alert_title = None
        alert_message = None
        if alarm:
            office_name = next((row["name"] for row in office_rows if row["id"] == overall_office_id), "Unknown office")
            alert_title = "NEW EARLIER APPOINTMENT FOUND"
            alert_message = f"{office_name}\n{overall_date.strftime('%d %B %Y')}"

        return CheckOutcome(
            check_id=check_id,
            checked_at=checked_at,
            results=results,
            overall_earliest_date=overall_date,
            overall_earliest_office_id=overall_office_id,
            alarm_triggered=alarm,
            alert_title=alert_title,
            alert_message=alert_message,
            status_message=status,
        )

    def _overall_from_results(self, results: list[OfficeResult]) -> tuple[object, int | None]:
        candidates = [(result.earliest, result.office_id) for result in results if result.earliest is not None]
        if not candidates:
            return None, None
        return min(candidates, key=lambda item: item[0])

    def _effective_overall(self, results: list[OfficeResult], previous_dates_by_office) -> tuple[object, int | None]:
        candidates = []
        for result in results:
            if result.success:
                if result.earliest is not None:
                    candidates.append((result.earliest, result.office_id))
            else:
                previous_dates = previous_dates_by_office.get(result.office_id, set())
                if previous_dates:
                    candidates.append((min(previous_dates), result.office_id))
        if not candidates:
            return None, None
        return min(candidates, key=lambda item: item[0])

    def _record_events(self, checked_at, previous, results, overall_date, overall_office_id, last_success_by_office) -> bool:
        previous_check = previous["check"]
        previous_overall = previous["overall_date"]
        previous_dates_by_office = previous["office_dates"]
        alarm_triggered = False

        for result in results:
            if not result.success:
                self.db.insert_event(
                    "REQUEST_ERROR",
                    checked_at,
                    f"{result.name}: {result.error}",
                    office_id=result.office_id,
                )
            else:
                last_error = self.db.latest_event_for_office(result.office_id, "REQUEST_ERROR")
                last_success = last_success_by_office.get(result.office_id)
                if last_error and (last_success is None or last_error["created_at"] > last_success["checked_at"]):
                    self.db.insert_event(
                        "RECOVERY_AFTER_ERROR",
                        checked_at,
                        f"{result.name}: request succeeded after a previous error.",
                        office_id=result.office_id,
                    )

        if previous_check is None:
            return False

        successful_results = [result for result in results if result.success]
        if not successful_results:
            return False

        if overall_date is not None and (previous_overall is None or overall_date < previous_overall):
            office_name = next((r.name for r in results if r.office_id == overall_office_id), "Unknown office")
            should_alarm = self.target_date is None or overall_date < self.target_date
            self.db.insert_event(
                "NEW_EARLIER_OVERALL",
                checked_at,
                f"{office_name}: overall earliest improved from {previous_overall} to {overall_date}.",
                office_id=overall_office_id,
                old_overall_date=previous_overall,
                new_overall_date=overall_date,
                alarm_triggered=should_alarm,
            )
            alarm_triggered = should_alarm
        elif previous_overall is not None and (overall_date is None or overall_date > previous_overall):
            self.db.insert_event(
                "EARLIEST_DISAPPEARED",
                checked_at,
                f"Overall earliest moved from {previous_overall} to {overall_date or 'none'}.",
                office_id=previous["overall_office_id"],
                old_overall_date=previous_overall,
                new_overall_date=overall_date,
            )

        for result in successful_results:
            old_dates = previous_dates_by_office.get(result.office_id, set())
            new_dates = set(result.dates)
            old_earliest = min(old_dates) if old_dates else None
            new_earliest = result.earliest

            if old_earliest and new_earliest and new_earliest < old_earliest and not alarm_triggered:
                self.db.insert_event(
                    "OFFICE_EARLIER",
                    checked_at,
                    f"{result.name}: earliest improved from {old_earliest} to {new_earliest}.",
                    office_id=result.office_id,
                    old_date=old_earliest,
                    new_date=new_earliest,
                    old_overall_date=previous_overall,
                    new_overall_date=overall_date,
                )
            elif old_earliest and (new_earliest is None or new_earliest > old_earliest):
                self.db.insert_event(
                    "OFFICE_LATER",
                    checked_at,
                    f"{result.name}: earliest moved from {old_earliest} to {new_earliest or 'none'}.",
                    office_id=result.office_id,
                    old_date=old_earliest,
                    new_date=new_earliest,
                    old_overall_date=previous_overall,
                    new_overall_date=overall_date,
                )

            for added in sorted(new_dates - old_dates):
                self.db.insert_event("DATE_ADDED", checked_at, f"{result.name}: date added {added}.", result.office_id, new_date=added)
            for removed in sorted(old_dates - new_dates):
                self.db.insert_event("DATE_REMOVED", checked_at, f"{result.name}: date removed {removed}.", result.office_id, old_date=removed)

        return alarm_triggered

    def _progress(self, message: str) -> None:
        if self.progress_callback:
            self.progress_callback(message)
