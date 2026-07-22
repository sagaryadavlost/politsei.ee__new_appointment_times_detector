from __future__ import annotations

import queue
import threading
import webbrowser
from datetime import datetime, timedelta
from tkinter import BOTH, LEFT, RIGHT, VERTICAL, X, Y, Canvas, StringVar, Tk, ttk, messagebox

import config
from appointment_monitor.alarm import AlarmManager
from appointment_monitor.database import Database
from appointment_monitor.monitor import AppointmentMonitor


class AppointmentApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title(config.APP_NAME)
        self.root.geometry("980x720")
        self.root.minsize(840, 620)

        self.db = Database()
        self.monitor = AppointmentMonitor(self.db, progress_callback=self._post_progress)
        self.alarm = AlarmManager()
        self.queue: queue.Queue = queue.Queue()
        self.interval_seconds = config.DEFAULT_INTERVAL_SECONDS
        self.paused = False
        self.checking = False
        self.next_check_at: datetime | None = None

        self.status_var = StringVar(value="Starting")
        self.last_checked_var = StringVar(value="Not checked yet")
        self.countdown_var = StringVar(value="--:--")
        self.monitoring_var = StringVar(value="● ACTIVE")
        self.overall_var = StringVar(value="Loading...")
        self.overall_office_var = StringVar(value="")
        self.alert_var = StringVar(value="")

        self.office_vars: dict[int, dict[str, StringVar]] = {}
        self.history_filter_var = StringVar(value="All")

        self._styles()
        self._build()
        self._load_previous_state()
        self.check_now()
        self.root.after(250, self._poll_queue)
        self.root.after(1000, self._tick)

    def _styles(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f5f7fb")
        style.configure("Card.TFrame", background="#ffffff", relief="flat")
        style.configure("Title.TLabel", background="#f5f7fb", foreground="#172033", font=("Helvetica", 22, "bold"))
        style.configure("Body.TLabel", background="#ffffff", foreground="#263243", font=("Helvetica", 12))
        style.configure("Muted.TLabel", background="#ffffff", foreground="#677489", font=("Helvetica", 11))
        style.configure("Overall.TLabel", background="#ffffff", foreground="#0b6b57", font=("Helvetica", 30, "bold"))
        style.configure("Alert.TLabel", background="#fff1f1", foreground="#a31621", font=("Helvetica", 14, "bold"))
        style.configure("TButton", font=("Helvetica", 12), padding=8)

    def _build(self) -> None:
        container = ttk.Frame(self.root, padding=18)
        container.pack(fill=BOTH, expand=True)

        header = ttk.Frame(container)
        header.pack(fill=X)
        ttk.Label(header, text="APPOINTMENT MONITOR", style="Title.TLabel").pack(side=LEFT)
        ttk.Button(header, text="Send Requests Now", command=self.check_now).pack(side=RIGHT)
        ttk.Button(header, text="Pause / Resume", command=self.toggle_pause).pack(side=RIGHT, padx=8)
        ttk.Button(header, text="Test Alarm", command=self.test_alarm).pack(side=RIGHT)
        ttk.Button(header, text="Stop Alarm", command=self.stop_alarm).pack(side=RIGHT, padx=8)

        tabs = ttk.Notebook(container)
        tabs.pack(fill=BOTH, expand=True, pady=(14, 0))

        dashboard_outer = ttk.Frame(tabs)
        dashboard = self._scrollable_frame(dashboard_outer)
        history = ttk.Frame(tabs, padding=8)
        tabs.add(dashboard_outer, text="Dashboard")
        tabs.add(history, text="History")

        top = ttk.Frame(dashboard, style="Card.TFrame", padding=16)
        top.pack(fill=X)
        ttk.Label(top, text="Monitoring status:", style="Muted.TLabel").pack(side=LEFT)
        ttk.Label(top, textvariable=self.monitoring_var, style="Body.TLabel").pack(side=LEFT, padx=(8, 24))
        ttk.Label(top, text="Last checked:", style="Muted.TLabel").pack(side=LEFT)
        ttk.Label(top, textvariable=self.last_checked_var, style="Body.TLabel").pack(side=LEFT, padx=(8, 24))
        ttk.Label(top, text="Next automatic check:", style="Muted.TLabel").pack(side=LEFT)
        ttk.Label(top, textvariable=self.countdown_var, style="Body.TLabel").pack(side=LEFT, padx=(8, 0))

        overall = ttk.Frame(dashboard, style="Card.TFrame", padding=18)
        overall.pack(fill=X, pady=14)
        ttk.Label(overall, text="OVERALL EARLIEST APPOINTMENT", style="Muted.TLabel").pack(anchor="w")
        ttk.Label(overall, textvariable=self.overall_var, style="Overall.TLabel").pack(anchor="w", pady=(8, 0))
        ttk.Label(overall, textvariable=self.overall_office_var, style="Body.TLabel").pack(anchor="w")
        target_str = config.TARGET_APPOINTMENT_DATE.strftime("%d %B %Y")
        ttk.Label(overall, text=f"Alarm condition: Only alerts for dates earlier than {target_str}", style="Muted.TLabel").pack(anchor="w", pady=(4, 0))
        self.alert_label = ttk.Label(overall, textvariable=self.alert_var, style="Alert.TLabel", padding=10)

        offices_frame = ttk.Frame(dashboard)
        offices_frame.pack(fill=BOTH, expand=True)
        for row in self.db.offices():
            card = ttk.Frame(offices_frame, style="Card.TFrame", padding=14)
            card.pack(fill=X, pady=6)
            values = {
                "earliest": StringVar(value="Earliest available: Loading..."),
                "status": StringVar(value="Status: Checking"),
            }
            self.office_vars[row["id"]] = values
            ttk.Label(card, text=row["name"], style="Body.TLabel", font=("Helvetica", 14, "bold")).pack(anchor="w")
            ttk.Label(card, text=row["address"], style="Muted.TLabel").pack(anchor="w")
            ttk.Label(card, textvariable=values["earliest"], style="Body.TLabel").pack(anchor="w", pady=(6, 0))
            ttk.Label(card, textvariable=values["status"], style="Muted.TLabel").pack(anchor="w")

        buttons = ttk.Frame(dashboard)
        buttons.pack(fill=X, pady=(10, 0))
        ttk.Button(buttons, text="Open Booking Website", command=lambda: webbrowser.open(config.BOOKING_URL)).pack(side=RIGHT)
        ttk.Label(dashboard, textvariable=self.status_var, style="Title.TLabel", font=("Helvetica", 12)).pack(anchor="w", pady=(12, 0))

        filters = ttk.Frame(history)
        filters.pack(fill=X)
        filter_values = ["All", "Alarm events", "Earlier dates", "Dates disappeared", "Errors", "Jõhvi", "Pärnu", "Tallinn", "Tartu"]
        ttk.OptionMenu(filters, self.history_filter_var, "All", *filter_values, command=lambda _: self.refresh_history()).pack(side=LEFT)
        ttk.Button(filters, text="Refresh", command=self.refresh_history).pack(side=LEFT, padx=8)
        ttk.Button(filters, text="Copy Selected", command=self.copy_selected_history).pack(side=LEFT)
        ttk.Button(filters, text="Send Requests Now", command=self.check_now).pack(side=LEFT, padx=8)
        self.history_tree = ttk.Treeview(history, columns=("time", "event", "office", "description", "alarm"), show="headings", height=18)
        for col, title, width in [
            ("time", "Time", 150),
            ("event", "Event", 165),
            ("office", "Office", 180),
            ("description", "Description", 390),
            ("alarm", "Alarm", 70),
        ]:
            self.history_tree.heading(col, text=title)
            self.history_tree.column(col, width=width, anchor="w")
        self.history_tree.pack(fill=BOTH, expand=True, pady=(10, 0))
        self.history_tree.bind("<Command-c>", self.copy_selected_history)
        self.history_tree.bind("<Control-c>", self.copy_selected_history)
        self.refresh_history()

    def _scrollable_frame(self, parent: ttk.Frame) -> ttk.Frame:
        canvas = Canvas(parent, background="#f5f7fb", highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient=VERTICAL, command=canvas.yview)
        content = ttk.Frame(canvas, padding=8)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")

        def update_scroll_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def match_canvas_width(event) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        def on_mousewheel(event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        content.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", match_canvas_width)
        canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", on_mousewheel))
        canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))

        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)
        return content

    def _load_previous_state(self) -> None:
        state = self.db.latest_successful_state()
        if state["overall_date"]:
            self.overall_var.set(self._format_date(state["overall_date"]))
            office = next((o for o in self.db.offices() if o["id"] == state["overall_office_id"]), None)
            self.overall_office_var.set(office["name"] if office else "")

    def check_now(self) -> None:
        if self.checking:
            self.status_var.set("A request check is already running.")
            return
        self.checking = True
        self.status_var.set("Checking appointment availability...")
        self.monitoring_var.set("● CHECKING")
        threading.Thread(target=lambda: self.queue.put(self.monitor.run_check()), daemon=True).start()

    def _post_progress(self, message: str) -> None:
        self.queue.put(("progress", message))

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.monitoring_var.set("● PAUSED" if self.paused else "● ACTIVE")
        if not self.paused:
            self.next_check_at = datetime.now() + timedelta(seconds=self.interval_seconds)

    def test_alarm(self) -> None:
        self.alert_var.set("Test alarm is active")
        self.alert_label.pack(fill=X, pady=(12, 0))
        self.alarm.notify(config.APP_NAME, "Test alarm")
        self.alarm.test()

    def stop_alarm(self) -> None:
        self.alarm.stop()
        self.alert_var.set("")
        self.alert_label.pack_forget()

    def _poll_queue(self) -> None:
        try:
            item = self.queue.get_nowait()
        except queue.Empty:
            self.root.after(250, self._poll_queue)
            return

        if isinstance(item, tuple) and item[0] == "progress":
            self.status_var.set(item[1])
            self.root.after(250, self._poll_queue)
            return

        outcome = item

        self.checking = False
        self.last_checked_var.set(outcome.checked_at.strftime("%d %B %Y %H:%M:%S"))
        self.next_check_at = datetime.now() + timedelta(seconds=self.interval_seconds)
        self.monitoring_var.set("● PAUSED" if self.paused else "● ACTIVE")
        self.status_var.set(outcome.status_message)

        for result in outcome.results:
            values = self.office_vars[result.office_id]
            values["earliest"].set(f"Earliest available: {self._format_date(result.earliest) if result.earliest else 'None'}")
            values["status"].set(f"Status: {result.status}")

        if outcome.overall_earliest_date:
            self.overall_var.set(self._format_date(outcome.overall_earliest_date))
            office = next((r for r in outcome.results if r.office_id == outcome.overall_earliest_office_id), None)
            self.overall_office_var.set(office.name if office else "")
        else:
            self.overall_var.set("No available appointments")
            self.overall_office_var.set("")

        if outcome.alarm_triggered:
            self.alert_var.set(f"{outcome.alert_title}\n{outcome.alert_message}")
            self.alert_label.pack(fill=X, pady=(12, 0))
            self.alarm.notify(config.APP_NAME, outcome.alert_message or "New earlier appointment")
            self.alarm.start()

        self.refresh_history()
        self.root.after(250, self._poll_queue)

    def _tick(self) -> None:
        if not self.paused and not self.checking and self.next_check_at and datetime.now() >= self.next_check_at:
            self.check_now()
        if self.paused:
            self.countdown_var.set("Paused")
        elif self.next_check_at:
            remaining = max(0, int((self.next_check_at - datetime.now()).total_seconds()))
            self.countdown_var.set(f"{remaining // 60:02d}:{remaining % 60:02d}")
        self.root.after(1000, self._tick)

    def refresh_history(self) -> None:
        selected = self.history_filter_var.get()
        office_id = None
        event_types = None
        if selected == "Alarm events":
            event_types = {"NEW_EARLIER_OVERALL"}
        elif selected == "Earlier dates":
            event_types = {"NEW_EARLIER_OVERALL", "OFFICE_EARLIER", "DATE_ADDED"}
        elif selected == "Dates disappeared":
            event_types = {"EARLIEST_DISAPPEARED", "OFFICE_LATER", "DATE_REMOVED"}
        elif selected == "Errors":
            event_types = {"REQUEST_ERROR", "RECOVERY_AFTER_ERROR"}
        elif selected in {"Jõhvi", "Pärnu", "Tallinn", "Tartu"}:
            key = {"Jõhvi": "johvi", "Pärnu": "parnu", "Tallinn": "tallinn", "Tartu": "tartu"}[selected]
            office_id = self.db.office_by_key(key)["id"]

        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        for event in self.db.recent_events(office_id=office_id, event_types=event_types):
            self.history_tree.insert(
                "",
                "end",
                values=(
                    event["created_at"].replace("T", " "),
                    event["event_type"],
                    event["office_name"] or "",
                    event["description"],
                    "Yes" if event["alarm_triggered"] else "No",
                ),
            )

    def copy_selected_history(self, event=None) -> str:
        selected_items = self.history_tree.selection()
        if not selected_items:
            self.status_var.set("Select one or more history rows to copy.")
            return "break"

        lines = []
        for item in selected_items:
            time_text, event_type, office, description, alarm = self.history_tree.item(item, "values")
            parts = [
                f"Time: {time_text}",
                f"Event: {event_type}",
            ]
            if office:
                parts.append(f"Office: {office}")
            parts.extend(
                [
                    f"Description: {description}",
                    f"Alarm triggered: {alarm}",
                ]
            )
            lines.append("\n".join(parts))

        self.root.clipboard_clear()
        self.root.clipboard_append("\n\n".join(lines))
        self.status_var.set(f"Copied {len(selected_items)} history event{'s' if len(selected_items) != 1 else ''}.")
        return "break"

    def _format_date(self, value) -> str:
        return value.strftime("%d %B %Y")


def main() -> None:
    root = Tk()
    try:
        app = AppointmentApp(root)
        root.mainloop()
    except Exception as exc:
        messagebox.showerror(config.APP_NAME, str(exc))
        raise
