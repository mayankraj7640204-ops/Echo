"""Load the synthetic incident history used in the hackathon demo."""

import json
import os
import re
from pathlib import Path

import certifi
from dotenv import load_dotenv


BANK_ID = "hh3-incident-response"


def main() -> None:
    load_dotenv()
    system_ca_bundle = "/etc/ssl/cert.pem"
    os.environ.setdefault(
        "SSL_CERT_FILE",
        system_ca_bundle if Path(system_ca_bundle).is_file() else certifi.where(),
    )
    from hindsight_client import Hindsight

    api_key = os.getenv("HINDSIGHT_API_KEY")
    if not api_key:
        raise SystemExit("Set HINDSIGHT_API_KEY in .env before seeding demo memories.")

    incidents = json.loads(Path("demo_incidents.json").read_text())
    client = Hindsight(
        base_url=os.getenv("HINDSIGHT_BASE_URL", "https://api.hindsight.vectorize.io"),
        api_key=api_key,
    )
    try:
        existing_ids = set()
        offset = 0
        while True:
            page = client.list_memories(bank_id="hh3-incident-response", limit=200, offset=offset)
            for memory in page.items:
                metadata = memory.metadata or {}
                incident_id = metadata.get("incident_id")
                if not incident_id:
                    match = re.search(r"\bIncident ID:\s*([A-Z0-9][A-Z0-9._/-]{1,79})", memory.text or "", re.IGNORECASE)
                    incident_id = match.group(1) if match else None
                if incident_id:
                    existing_ids.add(str(incident_id).upper())
            offset += len(page.items)
            if not page.items or offset >= page.total:
                break
        for incident in incidents:
            if incident["incident_id"].upper() in existing_ids:
                continue
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
            existing_ids.add(incident["incident_id"].upper())
        print(f"Demo bank ready with {len(existing_ids)} identified incident(s): {BANK_ID}.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
