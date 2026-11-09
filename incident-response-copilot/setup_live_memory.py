"""Create the empty Hindsight bank used by the live Echo workspace."""

import os
from pathlib import Path

import certifi
from dotenv import load_dotenv


BANK_ID = "echo-live-incidents"


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
        raise SystemExit("Set HINDSIGHT_API_KEY in .env before creating the live memory bank.")

    client = Hindsight(
        base_url=os.getenv("HINDSIGHT_BASE_URL", "https://api.hindsight.vectorize.io"),
        api_key=api_key,
    )
    try:
        try:
            client.get_bank_config(BANK_ID)
            print(f"Live Hindsight bank already ready: {BANK_ID}")
            return
        except Exception as exc:
            if getattr(exc, "status", None) != 404 and getattr(exc, "status_code", None) != 404:
                raise
        bank = client.create_bank(
            bank_id=BANK_ID,
            name="Echo Team Incident Memory",
            background=(
                "Only operator-confirmed real incident reports, causes, verified recoveries, "
                "and prevention follow-ups. Historical actions are clues, not automatic authorization."
            ),
            disposition={"skepticism": 4, "literalism": 4, "empathy": 2},
        )
        print(f"Created empty live Hindsight bank: {bank.bank_id}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
