from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class OfficeResult:
    office_id: int
    name: str
    address: str
    success: bool
    dates: list[date]
    error: str | None = None

    @property
    def earliest(self) -> date | None:
        return min(self.dates) if self.success and self.dates else None

    @property
    def status(self) -> str:
        if not self.success:
            return "Request failed"
        return "Available" if self.dates else "No available appointments"


@dataclass(frozen=True)
class CheckOutcome:
    check_id: int
    checked_at: datetime
    results: list[OfficeResult]
    overall_earliest_date: date | None
    overall_earliest_office_id: int | None
    alarm_triggered: bool
    alert_title: str | None
    alert_message: str | None
    status_message: str

