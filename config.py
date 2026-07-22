from dataclasses import dataclass
from datetime import date
import os


APP_NAME = "Appointment Monitor"
DEFAULT_INTERVAL_SECONDS = 15 * 60
REQUEST_TIMEOUT_SECONDS = 20
OFFICE_REQUEST_DELAY_SECONDS = 5

# Target booked appointment date. Alarm only triggers if a date earlier than this is found.
TARGET_APPOINTMENT_DATE = date(2026, 8, 4)

SERVICE_PUBLIC_ID = "3af778a300a86b1d0cb5556f993ab98adfa1a9debaac3c231026c5cb8425fce2"
CUSTOM_SLOT_LENGTH = 120
BOOKING_URL = "https://broneering.politsei.ee/qmaticwebbooking/"
API_BASE_URL = "https://broneering.politsei.ee/qmaticwebbooking/rest/schedule/branches"

# Alarm sound configuration
# Path to custom sound file (relative to project root or absolute)
ALARM_SOUND_FILE = os.path.join(os.path.dirname(__file__), "sounds", "appointment_available.mp3")
ALARM_REPEAT_COUNT = 300
ALARM_REPEAT_INTERVAL_SECONDS = 10


@dataclass(frozen=True)
class Office:
    key: str
    name: str
    address: str
    branch_id: str


OFFICES = [
    Office(
        key="johvi",
        name="Jõhvi Service Office",
        address="Rahu 38, Jõhvi",
        branch_id="a109dfb325ff0fb78d217aa76de53a6722a572fac190f3e4f3ab6ca64c886ba7",
    ),
    Office(
        key="parnu",
        name="Pärnu Service Office",
        address="A. H. Tammsaare pst 61, Pärnu",
        branch_id="bdfdc72ede1f3a9aafa54ac48ddbdd0658ca07677d34b3e0665ba69baab406d8",
    ),
    Office(
        key="tallinn",
        name="Tallinn Service Office",
        address="A. H. Tammsaare tee 47, Tallinn",
        branch_id="89f89ac30f7f6329397e447102ce1ed13e5459eaa5a630c071d0577bdae6600a",
    ),
    Office(
        key="tartu",
        name="Tartu Service Office",
        address="Riia mnt 132, Tartu",
        branch_id="7eddbbbfe3cacf5100f4fcf0c8c7b156ca80749142abefb3e7909873bd396011",
    ),
]
