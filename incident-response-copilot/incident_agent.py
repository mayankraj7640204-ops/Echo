"""Band.ai incident response agent backed by Hindsight memory."""

import asyncio
import os
import re
from pathlib import Path

import certifi
from dotenv import load_dotenv

load_dotenv()
system_ca_bundle = "/etc/ssl/cert.pem"
os.environ.setdefault(
    "SSL_CERT_FILE",
    system_ca_bundle if Path(system_ca_bundle).is_file() else certifi.where(),
)

from hindsight_client import Hindsight
from pydantic import BaseModel, Field

from band import Agent, LogSettings
from band.adapters.codex import CodexAdapter, CodexAdapterConfig
from band.core.types import Emit


BANK_ID = "hh3-incident-response"
LIVE_BANK_ID = "echo-live-incidents"


class RecallIncidentsInput(BaseModel):
    """Search Hindsight for prior incidents related to the current symptoms."""

    query: str = Field(description="Service, symptoms, error text, and recent change")


class ReflectMitigationInput(BaseModel):
    """Synthesize a cautious mitigation from the current incident and memories."""

    service: str = Field(description="Affected service or system")
    symptoms: str = Field(description="Observed symptoms and impact")
    recent_changes: str = Field(description="Recent deploys or infrastructure changes")
    constraints: str = Field(description="Known safety, rollback, or access constraints")


class RecordIncidentInput(BaseModel):
    """Save a resolved incident and its verified outcome to long-term memory."""

    incident_id: str = Field(description="Unique incident identifier")
    service: str = Field(description="Affected service")
    severity: str = Field(description="Severity, such as SEV-1, SEV-2, or SEV-3")
    symptoms: str = Field(description="Observed symptoms and customer impact")
    root_cause: str = Field(description="Confirmed root cause, or 'unknown'")
    resolution: str = Field(description="Actions taken and verified outcome")
    prevention: str = Field(description="Follow-up action that reduces recurrence")


api_key = os.getenv("HINDSIGHT_API_KEY")
if not api_key:
    raise RuntimeError("Set HINDSIGHT_API_KEY in .env before starting the agent.")

hindsight = Hindsight(
    base_url=os.getenv("HINDSIGHT_BASE_URL", "https://api.hindsight.vectorize.io"),
    api_key=api_key,
)


def recall_incidents(args: RecallIncidentsInput, bank_id: str = BANK_ID) -> str:
    """Return at most two distinct incident examples, not every extracted fact."""
    result = hindsight.recall(
        bank_id=bank_id,
        query=args.query,
        budget="mid",
        max_tokens=1200,
    )
    return format_incident_memories(result.results)


async def arecall_incidents(args: RecallIncidentsInput, bank_id: str = BANK_ID) -> str:
    """Async version for web requests sharing FastAPI's event loop."""
    result = await hindsight.arecall(
        bank_id=bank_id,
        query=args.query,
        budget="mid",
        max_tokens=1200,
    )
    return format_incident_memories(result.results)


def format_incident_memories(results) -> str:
    """Group small Hindsight facts into no more than two distinct cases."""
    if not results:
        return "No relevant incident memories found. Treat this as a new incident."
    examples: dict[str, list[str]] = {}
    anonymous: list[str] = []
    seen: set[str] = set()
    for memory in results:
        # Hindsight can return several extracted facts as one multi-line item.
        # Keep each fact separate so a loose summary cannot be mislabeled as part
        # of whichever incident happens to appear later in the same result.
        for fragment in re.split(r"\n+", memory.text or ""):
            text = " ".join(fragment.split())
            text = re.sub(r"\s*\|\s*(?:When|Where|Involving):\s*[^|]+", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*\|\s*", " ", text).strip()
            normalized = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
            if not text or normalized in seen:
                continue
            seen.add(normalized)
            incident_ids = re.findall(
                r"\bIncident ID:\s*([A-Z0-9][A-Z0-9._/-]{1,79})",
                text,
                flags=re.IGNORECASE,
            )
            if not incident_ids:
                incident_ids = re.findall(r"\bIncident\s+([A-Z0-9][A-Z0-9._/-]{1,79})\b", text, flags=re.IGNORECASE)
            if not incident_ids:
                incident_ids = re.findall(r"\bINC-[A-Z0-9][A-Z0-9._/-]{1,79}\b", text, flags=re.IGNORECASE)
            if not incident_ids:
                if len(anonymous) < 2:
                    anonymous.append(text[:400].rstrip())
                continue
            incident_id = incident_ids[0].upper()
            examples.setdefault(incident_id, [])
            if len(examples[incident_id]) < 3:
                examples[incident_id].append(text[:400].rstrip())
    if not examples:
        if not anonymous:
            return "No clearly identified past incident matched. Treat this as a new incident."
        return "\n\n".join(f"Saved team memory: {summary}" for summary in anonymous)
    # When a case ID is available, keep loose facts out of the case cards so
    # responders can tell which details belong to which incident.
    formatted = [f"{incident_id}: " + " ".join(facts) for incident_id, facts in list(examples.items())[:2]]
    return "\n\n".join(formatted)


def reflect_mitigation(args: ReflectMitigationInput) -> str:
    """Ask Hindsight to reason over relevant incident history and current facts."""
    response = hindsight.reflect(
        bank_id=BANK_ID,
        query=(
            "Help an on-call team understand this incident in plain, everyday language. "
            "Use at most 120 words. Use these short sections: 'What we know', "
            "'What may be happening', 'What to check next' (at most 3 safe checks), "
            "and 'Avoid for now'. Clearly label guesses; cite no more than two matching "
            "incident IDs. Explain unavoidable technical terms briefly. Do not dump "
            "individual memory facts or repeat the entire history."
        ),
        context=(
            f"Service: {args.service}\nSymptoms and impact: {args.symptoms}\n"
            f"Recent changes: {args.recent_changes}\n"
            f"Constraints: {args.constraints}"
        ),
        budget="mid",
    )
    return response.text


async def areflect_mitigation(args: ReflectMitigationInput) -> str:
    """Async version for web requests sharing FastAPI's event loop."""
    response = await hindsight.areflect(
        bank_id=BANK_ID,
        query=(
            "Help an on-call team understand this incident in plain, everyday language. "
            "Use at most 120 words. Use these short sections: 'What we know', "
            "'What may be happening', 'What to check next' (at most 3 safe checks), "
            "and 'Avoid for now'. Clearly label guesses; cite no more than two matching "
            "incident IDs. Explain unavoidable technical terms briefly. Do not dump "
            "individual memory facts or repeat the entire history."
        ),
        context=(
            f"Service: {args.service}\nSymptoms and impact: {args.symptoms}\n"
            f"Recent changes: {args.recent_changes}\n"
            f"Constraints: {args.constraints}"
        ),
        budget="mid",
    )
    return response.text


def record_incident(args: RecordIncidentInput, bank_id: str = BANK_ID) -> str:
    """Store a resolved incident so later responders can learn from it."""
    content = (
        f"Incident ID: {args.incident_id}\nService: {args.service}\n"
        f"Severity: {args.severity}\nSymptoms and impact: {args.symptoms}\n"
        f"Confirmed root cause: {args.root_cause}\n"
        f"Resolution and outcome: {args.resolution}\n"
        f"Prevention follow-up: {args.prevention}"
    )
    hindsight.retain(
        bank_id=bank_id,
        content=content,
        context="Verified incident postmortem",
        metadata={
            "incident_id": args.incident_id,
            "service": args.service,
            "severity": args.severity,
            "source": "operator-confirmed",
        },
    )
    return f"Saved {args.incident_id} to Hindsight for future incident recall."


async def arecord_incident(args: RecordIncidentInput, bank_id: str = BANK_ID) -> str:
    """Async version for web requests sharing FastAPI's event loop."""
    content = (
        f"Incident ID: {args.incident_id}\nService: {args.service}\n"
        f"Severity: {args.severity}\nSymptoms and impact: {args.symptoms}\n"
        f"Confirmed root cause: {args.root_cause}\n"
        f"Resolution and outcome: {args.resolution}\n"
        f"Prevention follow-up: {args.prevention}"
    )
    await hindsight.aretain(
        bank_id=bank_id,
        content=content,
        context="Verified incident postmortem",
        metadata={
            "incident_id": args.incident_id,
            "service": args.service,
            "severity": args.severity,
            "source": "operator-confirmed",
        },
    )
    return f"Saved {args.incident_id} to Hindsight for future incident recall."


async def main() -> None:
    LogSettings().for_application().configure()
    adapter = CodexAdapter(
        config=CodexAdapterConfig(
            transport="stdio",
            personality="pragmatic",
            sandbox="read-only",
            approval_policy="never",
            custom_section=(
                "You are an incident response copilot. Use Hindsight to search prior "
                "incidents before suggesting mitigations. For every new incident, call "
                "recall_incidents first, then call reflect_mitigation before answering. "
                "Clearly label facts, hypotheses, and unknowns. Cite incident IDs from "
                "retrieved memories. Historical fixes are precedent, not proof that the "
                "same action is safe now. Recommend diagnostics only; this agent cannot "
                "change production systems. "
                "After the operator confirms resolution, use record_incident to save the "
                "verified outcome and prevention follow-up."
            ),
            include_base_instructions=True,
        ),
        additional_tools=[
            (RecallIncidentsInput, recall_incidents),
            (ReflectMitigationInput, reflect_mitigation),
            (RecordIncidentInput, record_incident),
        ],
        emit={Emit.TASK_EVENTS, Emit.TOOL_CALLS},
    )
    async with Agent.from_config("incident_agent", adapter=adapter) as agent:
        await agent.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
