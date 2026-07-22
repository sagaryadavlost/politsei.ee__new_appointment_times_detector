from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import config
from appointment_monitor.models import OfficeResult


DB_PATH = Path("appointment_monitor.sqlite3")
TS_FORMAT = "%Y-%m-%dT%H:%M:%S"


def encode_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


def decode_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def encode_ts(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


class Database:
    def __init__(self, path: str | Path = DB_PATH) -> None:
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.initialize()

    def initialize(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS offices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                branch_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                address TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checked_at TEXT NOT NULL,
                overall_earliest_date TEXT,
                overall_earliest_office_id INTEGER REFERENCES offices(id),
                success INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS availability_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_id INTEGER NOT NULL REFERENCES checks(id) ON DELETE CASCADE,
                office_id INTEGER NOT NULL REFERENCES offices(id),
                earliest_date TEXT,
                status TEXT NOT NULL,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS available_dates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                check_id INTEGER NOT NULL REFERENCES checks(id) ON DELETE CASCADE,
                office_id INTEGER NOT NULL REFERENCES offices(id),
                available_date TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                event_type TEXT NOT NULL,
                office_id INTEGER REFERENCES offices(id),
                old_date TEXT,
                new_date TEXT,
                old_overall_date TEXT,
                new_overall_date TEXT,
                description TEXT NOT NULL,
                alarm_triggered INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_checks_checked_at ON checks(checked_at);
            CREATE INDEX IF NOT EXISTS idx_dates_office_date ON available_dates(office_id, available_date);
            CREATE INDEX IF NOT EXISTS idx_events_type_created ON events(event_type, created_at);
            """
        )
        for office in config.OFFICES:
            self.conn.execute(
                """
                INSERT INTO offices (key, branch_id, name, address)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    branch_id=excluded.branch_id,
                    name=excluded.name,
                    address=excluded.address
                """,
                (office.key, office.branch_id, office.name, office.address),
            )
        self.conn.commit()

    def offices(self) -> list[sqlite3.Row]:
        rows = list(self.conn.execute("SELECT * FROM offices"))
        by_key = {row["key"]: row for row in rows}
        return [by_key[office.key] for office in config.OFFICES if office.key in by_key]

    def office_by_key(self, key: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM offices WHERE key = ?", (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        return row

    def latest_successful_state(self) -> dict:
        check = self.conn.execute(
            """
            SELECT * FROM checks
            WHERE success = 1
            ORDER BY checked_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        if check is None:
            return {"check": None, "office_dates": {}, "overall_date": None, "overall_office_id": None}

        rows = self.conn.execute(
            "SELECT office_id, available_date FROM available_dates WHERE check_id = ?",
            (check["id"],),
        ).fetchall()
        office_dates: dict[int, set[date]] = {}
        for row in rows:
            office_dates.setdefault(row["office_id"], set()).add(date.fromisoformat(row["available_date"]))
        return {
            "check": check,
            "office_dates": office_dates,
            "overall_date": decode_date(check["overall_earliest_date"]),
            "overall_office_id": check["overall_earliest_office_id"],
        }

    def insert_check(
        self,
        checked_at: datetime,
        results: Iterable[OfficeResult],
        overall_date: date | None,
        overall_office_id: int | None,
    ) -> int:
        results = list(results)
        success = any(result.success for result in results)
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO checks (checked_at, overall_earliest_date, overall_earliest_office_id, success)
                VALUES (?, ?, ?, ?)
                """,
                (encode_ts(checked_at), encode_date(overall_date), overall_office_id, int(success)),
            )
            check_id = int(cur.lastrowid)
            for result in results:
                self.conn.execute(
                    """
                    INSERT INTO availability_snapshots
                    (check_id, office_id, earliest_date, status, error_message)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (check_id, result.office_id, encode_date(result.earliest), result.status, result.error),
                )
                if result.success:
                    for available in result.dates:
                        self.conn.execute(
                            """
                            INSERT INTO available_dates (check_id, office_id, available_date)
                            VALUES (?, ?, ?)
                            """,
                            (check_id, result.office_id, available.isoformat()),
                        )
        return check_id

    def insert_event(
        self,
        event_type: str,
        created_at: datetime,
        description: str,
        office_id: int | None = None,
        old_date: date | None = None,
        new_date: date | None = None,
        old_overall_date: date | None = None,
        new_overall_date: date | None = None,
        alarm_triggered: bool = False,
    ) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO events
                (created_at, event_type, office_id, old_date, new_date,
                 old_overall_date, new_overall_date, description, alarm_triggered)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    encode_ts(created_at),
                    event_type,
                    office_id,
                    encode_date(old_date),
                    encode_date(new_date),
                    encode_date(old_overall_date),
                    encode_date(new_overall_date),
                    description,
                    int(alarm_triggered),
                ),
            )

    def recent_events(self, limit: int = 200, office_id: int | None = None, event_types: set[str] | None = None) -> list[sqlite3.Row]:
        clauses = []
        params: list[object] = []
        if office_id is not None:
            clauses.append("office_id = ?")
            params.append(office_id)
        if event_types:
            placeholders = ",".join("?" for _ in event_types)
            clauses.append(f"event_type IN ({placeholders})")
            params.extend(sorted(event_types))
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        return list(
            self.conn.execute(
                f"""
                SELECT events.*, offices.name AS office_name
                FROM events
                LEFT JOIN offices ON offices.id = events.office_id
                {where}
                ORDER BY created_at DESC, events.id DESC
                LIMIT ?
                """,
                (*params, limit),
            )
        )

    def latest_event_for_office(self, office_id: int, event_type: str) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT * FROM events
            WHERE office_id = ? AND event_type = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (office_id, event_type),
        ).fetchone()

    def latest_success_snapshot_for_office(self, office_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT availability_snapshots.*, checks.checked_at AS checked_at
            FROM availability_snapshots
            JOIN checks ON checks.id = availability_snapshots.check_id
            WHERE availability_snapshots.office_id = ?
              AND availability_snapshots.status != 'Request failed'
            ORDER BY checks.checked_at DESC, checks.id DESC
            LIMIT 1
            """,
            (office_id,),
        ).fetchone()
