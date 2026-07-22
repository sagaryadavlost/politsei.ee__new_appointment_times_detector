import ssl
import sys

import certifi
import requests
try:
    import truststore
except ImportError:
    truststore = None

from appointment_monitor.api_client import AppointmentApiClient
from config import OFFICES


def main() -> None:
    print(f"Python: {sys.executable}")
    print(f"Python version: {sys.version.split()[0]}")
    print(f"OpenSSL: {ssl.OPENSSL_VERSION}")
    print(f"certifi bundle: {certifi.where()}")
    print(f"requests: {requests.__version__}")
    print(f"truststore: {truststore.__version__ if truststore else 'not installed'}")
    print()

    client = AppointmentApiClient()
    office = next(office for office in OFFICES if office.key == "tartu")
    url = client.dates_url(office.branch_id)
    print(f"Testing: {office.name}")
    print(url)
    response = client.session.get(url, timeout=20)
    print(f"HTTP status: {response.status_code}")
    response.raise_for_status()
    print(f"Response preview: {response.text[:300]}")


if __name__ == "__main__":
    main()
