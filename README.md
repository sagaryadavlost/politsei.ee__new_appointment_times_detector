# macOS Appointment Monitor

A Python 3 desktop application that monitors appointment availability at four Estonian Police and Border Guard Board service offices. It uses Tkinter for the interface, SQLite for history and state, and `requests.Session()` for the booking API.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

The database is created automatically as `appointment_monitor.sqlite3` on first launch.

## What It Monitors

The office and API settings are in `config.py`, including:

- Jõhvi Service Office, Rahu 38, Jõhvi
- Pärnu Service Office, A. H. Tammsaare pst 61, Pärnu
- Tallinn Service Office, A. H. Tammsaare tee 47, Tallinn
- Tartu Service Office, Riia mnt 132, Tartu

The default interval is 15 minutes. The app performs an immediate first check, then repeats automatically. Use **Send Requests Now** in the top bar to run the four office requests immediately and reset the countdown.

The app waits 5 seconds between office requests. This is configured as `OFFICE_REQUEST_DELAY_SECONDS` in `config.py`.

## Alarm Logic

The sound alarm only starts when the overall earliest available date becomes earlier than the previous saved overall earliest date:

```text
new_overall_earliest < previous_overall_earliest
```

The first successful run only establishes a baseline and never alarms. If the earliest date becomes later or disappears, the app records the event but does not alarm. If one office improves but the overall earliest date does not improve, the app records the office improvement but does not alarm. Repeated checks with the same earliest date do not create duplicate alarm events.

## SQLite History

SQLite stores:

- `offices`: configured offices and branch IDs.
- `checks`: every check attempt, including the overall earliest date.
- `availability_snapshots`: one row per office per check, including request status.
- `available_dates`: every date returned by each successful office request.
- `events`: meaningful changes such as earlier dates, disappeared dates, request errors, and alarms.

Request failures are never stored as empty availability. If all requests fail, the previous valid overall earliest appointment remains visible and available for the next comparison.

## macOS Notifications And Sound

On macOS, alarms use:

- `afplay /System/Library/Sounds/Glass.aiff` for sound.
- `osascript` notifications for Notification Center.

Use **Test Alarm** in the top bar to verify sound and notification behavior. Use **Stop Alarm** to silence the repeating alarm.

## Testing Without Waiting 15 Minutes

Use **Send Requests Now** for an immediate live check. The same button is available on the Dashboard and History tabs.

For automated logic tests:

```bash
python3 -m unittest discover -s tests
```

The tests simulate API responses and validate first-run behavior, improvements, disappeared dates, per-office changes, request failures, all-request failures, duplicate alarm prevention, empty successful responses, and restart recovery.

To temporarily shorten the app interval during manual testing, edit `DEFAULT_INTERVAL_SECONDS` in `config.py`.

## API Authentication Or Cookies

The app uses `requests.Session()` with browser-like JSON headers and a booking-site referrer. If the API starts requiring browser cookies or interactive session authentication, failed office requests will show as **Request failed** and will be recorded as `REQUEST_ERROR` events.

Do not paste private cookies into logs or screenshots. If cookie support is needed later, add it inside `AppointmentApiClient` in `appointment_monitor/api_client.py`, keeping secrets out of the database and event descriptions.

## SSL Certificate Errors

If History shows `SSL: CERTIFICATE_VERIFY_FAILED`, Python cannot verify the booking site's HTTPS certificate. The app logs this as `REQUEST_ERROR` and does not treat it as no appointments.

The app uses the `truststore` package so Python can use the macOS system trust store. `certifi` remains installed as a supporting certificate bundle.

First update the app dependencies:

```bash
source .venv/bin/activate
pip install --upgrade -r requirements.txt
```

If you installed Python from python.org on macOS, also run the bundled certificate installer. It is usually in `/Applications/Python 3.x/Install Certificates.command`.

If you use `pyenv` with Homebrew OpenSSL, also check that Homebrew certificates are installed:

```bash
brew reinstall ca-certificates openssl
pyenv uninstall 3.14.6
pyenv install 3.14.6
```

Do not disable HTTPS verification for normal use.

You can check which Python and certificate bundle the app is actually using with:

```bash
source .venv/bin/activate
python3 diagnose_ssl.py
```

## Package As A macOS App

Install PyInstaller, then build:

```bash
pip install pyinstaller
pyinstaller --windowed --name "Appointment Monitor" main.py
```

The app bundle will be under `dist/Appointment Monitor.app`.

## Launch Automatically At Login

Option 1: Open **System Settings → General → Login Items** and add the built `.app`.

Option 2: run from Terminal after packaging:

```bash
osascript -e 'tell application "System Events" to make login item at end with properties {path:"/absolute/path/to/dist/Appointment Monitor.app", hidden:false}'
```
