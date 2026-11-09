"""Load the synthetic incident history used in the hackathon demo."""

import json
import os
from pathlib import Path

import certifi
from dotenv import load_dotenv
from hindsight_client import Hindsight


BANK_ID = "hh3-incident-response"


def main() -> None:
    load_dotenv()
    system_ca_bundle = "/etc/ssl/cert.pem"
    os.environ.setdefault(
        "SSL_CERT_FILE",
        system_ca_bundle if Path(system_ca_bundle).is_file() else certifi.where(),
    )
    api_key = os.getenv("HINDSIGHT_API_KEY")
    if not api_key:
        raise SystemExit("Set HINDSIGHT_API_KEY in .env before seeding demo memories.")

    incidents = json.loads(Path("demo_incidents.json").read_text())
    client = Hindsight(
        base_url=os.getenv("HINDSIGHT_BASE_URL", "https://api.hindsight.vectorize.io"),
        api_key=api_key,
    )
    try:
        for incident in incidents:
            content = "\n".join(
                f"{key.replace('_', ' ').title()}: {value}"
                for key, value in incident.items()
            )
            client.retain(
                bank_id=BANK_ID,
                content=content,
                context="Synthetic incident postmortem for demonstration",
                metadata={
                    "incident_id": incident["incident_id"],
                    "service": incident["service"],
                    "severity": incident["severity"],
                    "source": "synthetic-demo-data",
                },
            )
        print(f"Seeded {len(incidents)} synthetic incidents into {BANK_ID}.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
