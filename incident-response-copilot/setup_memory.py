"""Create the Hindsight memory bank used by the incident response agent."""

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
    api_key = os.environ.get("HINDSIGHT_API_KEY")
    if not api_key:
        raise SystemExit("Set HINDSIGHT_API_KEY in .env before creating the memory bank.")

    client = Hindsight(
        base_url=os.getenv("HINDSIGHT_BASE_URL", "https://api.hindsight.vectorize.io"),
        api_key=api_key,
    )
    try:
        bank = client.create_bank(
            bank_id=BANK_ID,
            name="Incident Response Memory",
            background=(
                "Synthetic and operator-confirmed production incidents, their symptoms, "
                "causes, mitigations, and outcomes. Use this to retrieve precedent, not "
                "to treat historical fixes as automatically safe."
            ),
            disposition={"skepticism": 4, "literalism": 4, "empathy": 2},
        )
        print(f"Created Hindsight bank: {bank.bank_id}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
