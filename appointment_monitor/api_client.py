from __future__ import annotations

from datetime import date

import certifi
import requests
try:
    import truststore
except ImportError:
    truststore = None

import config


class AppointmentApiError(Exception):
    pass


class AppointmentApiClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        if truststore is not None:
            truststore.inject_into_ssl()
        else:
            self.session.verify = certifi.where()
        self.session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
                "Referer": config.BOOKING_URL,
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150 Safari/537.36"
                ),
            }
        )

    def dates_url(self, branch_id: str) -> str:
        return (
            f"{config.API_BASE_URL}/{branch_id}/dates;"
            f"servicePublicId={config.SERVICE_PUBLIC_ID};"
            f"customSlotLength={config.CUSTOM_SLOT_LENGTH}"
        )

    def fetch_dates(self, branch_id: str) -> list[date]:
        url = self.dates_url(branch_id)
        try:
            response = self.session.get(url, timeout=config.REQUEST_TIMEOUT_SECONDS)
            if response.status_code >= 400:
                body_preview = " ".join(response.text.split())[:300]
                detail = f"{response.status_code} HTTP error"
                if response.reason:
                    detail += f" ({response.reason})"
                if body_preview:
                    detail += f": {body_preview}"
                raise AppointmentApiError(detail)
            payload = response.json()
        except requests.exceptions.SSLError as exc:
            raise AppointmentApiError(
                "SSL certificate verification failed. Python could not build a trusted HTTPS "
                "certificate chain for the booking site even with the system trust store enabled."
            ) from exc
        except AppointmentApiError:
            raise
        except requests.RequestException as exc:
            raise AppointmentApiError(f"Request failed: {exc}") from exc
        except ValueError as exc:
            raise AppointmentApiError("Response was not valid JSON") from exc

        if not isinstance(payload, list):
            raise AppointmentApiError("Response JSON was not a list")

        parsed_dates: list[date] = []
        for item in payload:
            if not isinstance(item, dict) or "date" not in item:
                raise AppointmentApiError("Response contained an item without a date")
            try:
                parsed_dates.append(date.fromisoformat(str(item["date"])))
            except ValueError as exc:
                raise AppointmentApiError(f"Invalid date in response: {item['date']}") from exc
        return sorted(set(parsed_dates))
