"""Small web API for the Echo incident response demo."""

from __future__ import annotations

import logging
import os
import re
import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal
from incident_sources import IncidentSourceError, lookup_github_issue
from band_bridge import BandBridge, BandReviewError


PROJECT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = PROJECT_DIR.parent
SITE_DIR = WORKSPACE_DIR / "outputs" / "halden-port-ops"
load_dotenv(PROJECT_DIR / ".env")

if not os.getenv("HINDSIGHT_API_KEY"):
    raise RuntimeError("Set HINDSIGHT_API_KEY in incident-response-copilot/.env first.")

from incident_agent import (  # noqa: E402
    LIVE_BANK_ID,
    RecallIncidentsInput,
    ReflectMitigationInput,
    RecordIncidentInput,
    arecall_incidents,
    arecord_incident,
    areflect_mitigation,
    hindsight,
)


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("echo.web")
AGENTS_DIR = WORKSPACE_DIR / "rock-salt-agents"
band_bridge = BandBridge()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    agent_tasks: list[asyncio.Task[None]] = []
    agent_config = AGENTS_DIR / "agent_config.yaml"
    if band_bridge.configured and agent_config.exists():
        # macOS Python does not automatically use the OS Keychain certificate
        # roots. Keep certificate verification enabled using its system bundle.
        system_ca_bundle = Path("/etc/ssl/cert.pem")
        if not os.getenv("SSL_CERT_FILE") and system_ca_bundle.exists():
            os.environ["SSL_CERT_FILE"] = str(system_ca_bundle)
        if str(AGENTS_DIR) not in sys.path:
            sys.path.insert(0, str(AGENTS_DIR))
        try:
            import rock_agent  # noqa: PLC0415
            import salt_agent  # noqa: PLC0415

            agent_tasks = [
                asyncio.create_task(rock_agent.main(), name="echo-band-rock"),
                asyncio.create_task(salt_agent.main(), name="echo-band-salt"),
            ]
            await asyncio.sleep(2)
            logger.info("Rock and Salt Band runtimes started with Echo.")
        except Exception:
            logger.exception("Could not start the Band agent runtimes.")
    else:
        logger.warning("Band live reviews are not configured; Rock and Salt will remain offline.")

    try:
        yield
    finally:
        for task in agent_tasks:
            task.cancel()
        if agent_tasks:
            await asyncio.gather(*agent_tasks, return_exceptions=True)
        await hindsight.aclose()


app = FastAPI(title="Echo Incident Response", version="0.3.0", lifespan=lifespan)


class AnalyzeRequest(BaseModel):
    service: str = Field(min_length=1, max_length=160)
    symptoms: str = Field(min_length=8, max_length=4000)
    recent_changes: str = Field(default="Not provided", max_length=2000)
    constraints: str = Field(default="None provided", max_length=2000)


class RecordRequest(BaseModel):
    incident_id: str = Field(min_length=3, max_length=80)
    service: str = Field(min_length=1, max_length=160)
    severity: str = Field(min_length=2, max_length=30)
    symptoms: str = Field(min_length=8, max_length=4000)
    root_cause: str = Field(min_length=2, max_length=2000)
    resolution: str = Field(min_length=8, max_length=4000)
    prevention: str = Field(min_length=4, max_length=2000)
    operator_confirmed: bool = False


class LiveAnalyzeRequest(BaseModel):
    case_mode: Literal["new", "existing"] = "new"
    incident_id: str = Field(default="", max_length=80)
    service: str = Field(default="", max_length=160)
    symptoms: str = Field(default="", max_length=4000)
    recent_changes: str = Field(default="Not provided", max_length=2000)
    constraints: str = Field(default="None provided", max_length=2000)


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


class ApprovedHistoryRequest(BaseModel):
    incident_id: str = Field(min_length=3, max_length=80)
    service: str = Field(min_length=1, max_length=160)
    severity: str = Field(min_length=2, max_length=30)
    symptoms: str = Field(min_length=8, max_length=4000)
    root_cause: str = Field(min_length=2, max_length=2000)
    resolution: str = Field(min_length=8, max_length=4000)
    prevention: str = Field(min_length=4, max_length=2000)
    operator_approved: bool = False


class LiveRecordRequest(LiveAnalyzeRequest):
    incident_id: str = Field(min_length=3, max_length=80)
    service: str = Field(min_length=1, max_length=160)
    symptoms: str = Field(min_length=8, max_length=4000)
    severity: str = Field(min_length=2, max_length=30)
    root_cause: str = Field(min_length=2, max_length=2000)
    resolution: str = Field(min_length=8, max_length=4000)
    prevention: str = Field(min_length=4, max_length=2000)
    operator_confirmed: bool = False


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ready", "service": "echo-incident-demo"}


async def list_live_memory_items(limit: int = 5000) -> tuple[list[object], int, bool]:
    """Page through live-bank clues while bounding dashboard work."""
    items: list[object] = []
    offset = 0
    total = 0
    while offset < limit:
        page = await hindsight.alist_memories(
            bank_id=LIVE_BANK_ID,
            limit=min(200, limit - offset),
            offset=offset,
        )
        total = page.total
        if not page.items:
            break
        items.extend(page.items)
        offset += len(page.items)
        if offset >= total:
            return items, total, True
    return items, total, total <= len(items)


def extract_incident_id(memory) -> str | None:
    metadata = memory.metadata or {}
    found = metadata.get("incident_id") or metadata.get("Incident ID")
    if not found:
        match = re.search(
            r"\bIncident ID:\s*([A-Z0-9][A-Z0-9._/-]{1,79})",
            memory.text or "",
            re.IGNORECASE,
        )
        found = match.group(1) if match else None
    return str(found).strip().upper() if found else None


def saved_incident_ids(items: list[object]) -> set[str]:
    return {incident_id for item in items if (incident_id := extract_incident_id(item))}


async def find_live_incident_facts(incident_id: str) -> list[str]:
    """Find saved facts by the exact incident ID recorded in Hindsight metadata."""
    items, _, _ = await list_live_memory_items()
    facts: list[str] = []
    seen: set[str] = set()
    for item in items:
        if extract_incident_id(item) != incident_id.strip().upper():
            continue
        fact = " ".join((item.text or "").split())
        if fact and fact not in seen:
            seen.add(fact)
            facts.append(fact[:900])
    return facts[:5]


@app.get("/api/live/dashboard")
async def live_dashboard_summary() -> dict[str, object]:
    """Show real, minimal counts from the separate operator-confirmed bank."""
    try:
        items, total, count_complete = await list_live_memory_items()
        cases: dict[str, dict[str, str]] = {}
        for item in items:
            metadata = item.metadata or {}
            incident_id = extract_incident_id(item)
            if not incident_id:
                continue
            cases.setdefault(
                incident_id,
                {
                    "incident_id": incident_id,
                    "service": str(metadata.get("service") or "Service details saved"),
                    "severity": str(metadata.get("severity") or "Verified outcome"),
                    "updated_at": str(item.updated_at or item.var_date or ""),
                },
            )
        return {
            "bank_status": "ready",
            "searchable_memory_facts": total,
            "verified_case_count": len(cases),
            "case_count_complete": count_complete,
            "recent_cases": sorted(cases.values(), key=lambda case: case["updated_at"], reverse=True)[:5],
            "history_is_empty": total == 0,
        }
    except Exception as exc:
        logger.exception("Loading live dashboard summary failed")
        raise HTTPException(
            status_code=502,
            detail="Echo could not load your team memory right now. Please refresh and try again.",
        ) from exc


@app.post("/api/live/memory/search")
async def search_live_memory(payload: MemorySearchRequest) -> dict[str, object]:
    """Search only the real, operator-confirmed incident bank."""
    try:
        query = payload.query.strip()
        # Incident references are often numeric or unlike natural-language text.
        # Check saved metadata first so an exact ID still works when Hindsight's
        # semantic recall does not return the incident as a labeled sentence.
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,79}", query):
            exact_facts = await find_live_incident_facts(query)
            if exact_facts:
                return {
                    "matches": exact_facts[:5],
                    "message": f"Found saved details for {query}. Check that this is the same incident before using them.",
                }
        result = await arecall_incidents(
            RecallIncidentsInput(query=query),
            bank_id=LIVE_BANK_ID,
        )
        if result.startswith("No relevant") or result.startswith("No clearly"):
            matches: list[str] = []
        else:
            matches = [item.split(": ", 1)[1] for item in result.split("\n\n") if ": " in item]
        return {
            "matches": matches[:2],
            "message": (
                "These saved cases may help. Check that their details match the incident you are handling."
                if matches else "No confirmed team case matched that search. Try another service name, symptom, or incident reference."
            ),
        }
    except Exception as exc:
        logger.exception("Searching live incident memory failed")
        raise HTTPException(
            status_code=502,
            detail="Echo could not search team memory right now. Please try again.",
        ) from exc


@app.post("/api/live/memory/add")
async def add_approved_history(payload: ApprovedHistoryRequest) -> dict[str, str]:
    """Add one sanitized past case only after an operator approves it for reuse."""
    if not payload.operator_approved:
        raise HTTPException(
            status_code=400,
            detail="Confirm this sanitized past incident is approved for Hindsight before saving it.",
        )
    try:
        existing_items, _, _ = await list_live_memory_items()
        if payload.incident_id.strip().upper() in saved_incident_ids(existing_items):
            raise HTTPException(
                status_code=409,
                detail="That incident reference is already in team memory. Search before adding it again.",
            )
        content = (
            f"Incident ID: {payload.incident_id}\nService: {payload.service}\n"
            f"Severity: {payload.severity}\nSymptoms and impact: {payload.symptoms}\n"
            f"Confirmed root cause: {payload.root_cause}\n"
            f"Resolution and outcome: {payload.resolution}\n"
            f"Prevention follow-up: {payload.prevention}"
        )
        await hindsight.aretain(
            bank_id=LIVE_BANK_ID,
            content=content,
            context="Operator-approved historical incident report",
            metadata={
                "incident_id": payload.incident_id,
                "service": payload.service,
                "severity": payload.severity,
                "source": "operator-approved-history",
            },
        )
        return {"message": f"Added {payload.incident_id} to team memory for future incident searches."}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Adding approved incident history failed")
        raise HTTPException(
            status_code=502,
            detail="Echo could not add this history right now. Please try again.",
        ) from exc


@app.post("/api/incident/analyze")
async def analyze_incident(payload: AnalyzeRequest) -> dict[str, str]:
    """Recall matching incidents and prepare a cautious, evidence-aware brief."""
    try:
        memories = await arecall_incidents(
            RecallIncidentsInput(
                query=(
                    f"Incident reference: {payload.incident_id or 'not provided'}\n"
                    f"Service: {payload.service}\nSymptoms: {payload.symptoms}\n"
                    f"Recent changes: {payload.recent_changes}"
                )
            )
        )
        brief = await areflect_mitigation(
            ReflectMitigationInput(
                service=payload.service,
                symptoms=payload.symptoms,
                recent_changes=payload.recent_changes,
                constraints=payload.constraints,
            )
        )
        return {"memories": memories, "brief": brief}
    except Exception as exc:
        logger.exception("Incident analysis failed")
        raise HTTPException(
            status_code=502,
            detail="Echo could not reach incident memory right now. Please try again.",
        ) from exc


@app.post("/api/live/analyze")
async def analyze_live_incident(payload: LiveAnalyzeRequest) -> dict[str, object]:
    """Run an isolated, current incident review against operator-approved history."""
    try:
        incident_id = payload.incident_id.strip()
        service = payload.service.strip()
        symptoms = payload.symptoms.strip()
        recent_changes = payload.recent_changes.strip() or "Not provided"
        issue_source: dict[str, str] | None = None
        source_note = ""
        id_only = bool(incident_id) and not service and not symptoms
        exact_facts = await find_live_incident_facts(incident_id) if incident_id and payload.case_mode == "existing" else []
        if exact_facts:
            memories = "\n\n".join(f"{incident_id.upper()}: {fact}" for fact in exact_facts)
        else:
            if payload.case_mode == "existing" and incident_id and (not service or not symptoms):
                try:
                    issue_source = await lookup_github_issue(incident_id)
                except IncidentSourceError as exc:
                    source_note = str(exc)
                if not issue_source and not source_note and incident_id.lstrip("#").isdigit():
                    source_note = (
                        "No GitHub issue matched that number in the configured repository. "
                        "Check the repository settings, add a read-only GitHub token if it is private, "
                        "or enter the affected service and symptoms."
                    )
                if issue_source:
                    service = service or f"{issue_source['repository']} issue"
                    issue_details = "\n\n".join(
                        part for part in (issue_source["title"], issue_source["body"]) if part
                    )
                    symptoms = symptoms or issue_details
                    labels = issue_source["labels"] or "none"
                    if recent_changes == "Not provided":
                        recent_changes = f"GitHub issue state: {issue_source['state']}; labels: {labels}"
            if payload.case_mode == "existing" and id_only and not issue_source:
                memories = "No relevant incident memories found. Treat this as a new incident."
            else:
                recall_prompt = (
                    "Find the most relevant previously saved team cases by shared symptoms, service, and outcome. "
                    "The current case may be new and have a different ID; do not require an ID match. "
                    f"Service: {service or 'not provided'}\nSymptoms: {symptoms or 'not provided'}\n"
                    f"Recent changes: {recent_changes}"
                    if payload.case_mode == "new"
                    else (
                        f"Existing incident reference: {incident_id or 'not provided'}\n"
                        f"Service: {service or 'not provided'}\nSymptoms: {symptoms or 'not provided'}\n"
                        f"Recent changes: {recent_changes}"
                    )
                )
                memories = await arecall_incidents(
                    RecallIncidentsInput(query=recall_prompt),
                    bank_id=LIVE_BANK_ID,
                )
        if memories.startswith("No relevant") or memories.startswith("No clearly"):
            matches: list[str] = []
        else:
            matches = [item.split(": ", 1)[1] for item in memories.split("\n\n") if ": " in item]

        context = (
            f"Incident reference: {incident_id or 'not provided'}\n"
            f"Affected service: {service or 'not provided'}\nObserved symptoms: {symptoms or 'not provided'}\n"
            f"Recent changes: {recent_changes}\nDo-not-cross constraints: {payload.constraints}\n"
            f"Relevant operator-confirmed history, if any: {memories}"
        )
        history_for_agents = "\n\n".join(matches[:3]) if matches else "No relevant saved team case was found."
        band_context = (
            f"Incident reference: {incident_id or 'not provided'}\n"
            f"Affected service: {service or 'not provided'}\n"
            f"What people are experiencing: {symptoms or 'not provided'}\n"
            f"What changed recently: {recent_changes}\n"
            f"What must not be changed: {payload.constraints}\n\n"
            f"Relevant operator-confirmed past cases from Hindsight:\n{history_for_agents}"
        )
        try:
            agent_reviews = await band_bridge.review(
                incident_context=band_context,
                room_title=f"Echo incident review {incident_id or service or 'new case'}",
            )
        except BandReviewError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        investigation = str(agent_reviews["investigation"])
        safety_review = str(agent_reviews["safety_review"])
        if matches:
            history_summary = (
                "Echo found possible matches in your team’s saved history. Compare the shared details; "
                "a similar case may have a different cause."
            )
        elif payload.case_mode == "new":
            history_summary = "No closely related saved case surfaced. Echo’s checks are based on the details you provided."
        elif issue_source:
            history_summary = f"Loaded {incident_id} from GitHub. No related saved team case matched yet."
        elif incident_id and source_note.startswith("No GitHub issue matched"):
            history_summary = f"No issue or saved case matched {incident_id}. The ID alone does not reveal live incident details."
        elif incident_id:
            history_summary = f"No saved team case matched {incident_id}. The ID alone does not reveal live incident details."
        else:
            history_summary = "No team incidents have been saved yet. This review uses only the details you entered."
        return {
            "matches": matches[:2],
            "match_count": len(matches[:2]),
            "history_summary": history_summary,
            "incident_source": (
                {
                    "name": "GitHub Issues",
                    "repository": issue_source["repository"],
                    "title": issue_source["title"],
                    "state": issue_source["state"],
                    "labels": issue_source["labels"],
                    "url": issue_source["url"],
                }
                if issue_source else None
            ),
            "source_note": source_note,
            "resolved_incident": {
                "incident_id": incident_id,
                "service": service,
                "symptoms": symptoms,
                "recent_changes": recent_changes,
                "constraints": payload.constraints,
            },
            "investigation": investigation,
            "safety_review": safety_review,
            "band_room_id": agent_reviews["band_room_id"],
            "band_room_title": agent_reviews["band_room_title"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Live incident analysis failed")
        raise HTTPException(
            status_code=502,
            detail="Echo could not reach incident memory right now. Please try again.",
        ) from exc


@app.post("/api/incident/record")
async def save_incident(payload: RecordRequest) -> dict[str, str]:
    """Record an outcome only after explicit operator confirmation."""
    if not payload.operator_confirmed:
        raise HTTPException(
            status_code=400,
            detail="Confirm the resolution before saving it to incident memory.",
        )
    try:
        message = await arecord_incident(
            RecordIncidentInput(
                incident_id=payload.incident_id,
                service=payload.service,
                severity=payload.severity,
                symptoms=payload.symptoms,
                root_cause=payload.root_cause,
                resolution=payload.resolution,
                prevention=payload.prevention,
            )
        )
        return {"message": message}
    except Exception as exc:
        logger.exception("Saving confirmed incident failed")
        raise HTTPException(
            status_code=502,
            detail="Echo could not save the incident memory right now. Please try again.",
        ) from exc


@app.post("/api/live/record")
async def save_live_incident(payload: LiveRecordRequest) -> dict[str, str]:
    """Store only a resolution explicitly approved by the incident operator."""
    if not payload.operator_confirmed:
        raise HTTPException(
            status_code=400,
            detail="Confirm that the incident team verified and approved this outcome before saving it.",
        )
    try:
        existing_items, _, _ = await list_live_memory_items()
        if payload.incident_id.strip().upper() in saved_incident_ids(existing_items):
            raise HTTPException(
                status_code=409,
                detail="That incident reference is already saved. Search team memory before adding it again.",
            )
        message = await arecord_incident(
            RecordIncidentInput(
                incident_id=payload.incident_id,
                service=payload.service,
                severity=payload.severity,
                symptoms=payload.symptoms,
                root_cause=payload.root_cause,
                resolution=payload.resolution,
                prevention=payload.prevention,
            ),
            bank_id=LIVE_BANK_ID,
        )
        return {"message": message}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Saving live incident outcome failed")
        raise HTTPException(
            status_code=502,
            detail="Echo could not save this lesson right now. Please try again.",
        ) from exc


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(SITE_DIR / "index.html")


@app.get("/workspace.html", include_in_schema=False)
def workspace() -> FileResponse:
    return FileResponse(SITE_DIR / "workspace.html")


@app.get("/dashboard.html", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(SITE_DIR / "dashboard.html")


app.mount("/", StaticFiles(directory=SITE_DIR), name="site")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("web_api:app", host="127.0.0.1", port=8000, reload=False)
