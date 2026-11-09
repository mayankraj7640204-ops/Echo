"""Small web API for the Echo incident response demo."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


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
    hindsight,
    recall_incidents,
    reflect_mitigation,
    record_incident,
)


logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("echo.web")
app = FastAPI(title="Echo Incident Response", version="0.2.0")


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
    service: str = Field(min_length=1, max_length=160)
    symptoms: str = Field(min_length=8, max_length=4000)
    recent_changes: str = Field(default="Not provided", max_length=2000)
    constraints: str = Field(default="None provided", max_length=2000)


class LiveRecordRequest(LiveAnalyzeRequest):
    incident_id: str = Field(min_length=3, max_length=80)
    severity: str = Field(min_length=2, max_length=30)
    root_cause: str = Field(min_length=2, max_length=2000)
    resolution: str = Field(min_length=8, max_length=4000)
    prevention: str = Field(min_length=4, max_length=2000)
    operator_confirmed: bool = False


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ready", "service": "echo-incident-demo"}


@app.get("/api/live/dashboard")
def live_dashboard_summary() -> dict[str, object]:
    """Show real, minimal counts from the separate operator-confirmed bank."""
    try:
        page = hindsight.list_memories(bank_id=LIVE_BANK_ID, limit=200, offset=0)
        cases: dict[str, dict[str, str]] = {}
        for item in page.items:
            metadata = item.metadata or {}
            text = item.text or ""
            found = metadata.get("incident_id") or metadata.get("Incident ID")
            if not found:
                match = re.search(r"\bIncident ID:\s*([A-Z0-9][A-Z0-9._/-]{1,79})", text, re.IGNORECASE)
                found = match.group(1) if match else None
            if not found:
                continue
            key = str(found).strip().upper()
            cases.setdefault(
                key,
                {
                    "incident_id": key,
                    "service": str(metadata.get("service") or "Service details saved"),
                    "severity": str(metadata.get("severity") or "Verified outcome"),
                    "updated_at": str(item.updated_at or item.var_date or ""),
                },
            )
        return {
            "bank_status": "ready",
            "searchable_memory_facts": page.total,
            "verified_case_count": len(cases),
            "recent_cases": sorted(cases.values(), key=lambda case: case["updated_at"], reverse=True)[:5],
            "history_is_empty": page.total == 0,
        }
    except Exception as exc:
        logger.exception("Loading live dashboard summary failed")
        raise HTTPException(
            status_code=502,
            detail="Echo could not load your team memory right now. Please refresh and try again.",
        ) from exc


@app.post("/api/incident/analyze")
def analyze_incident(payload: AnalyzeRequest) -> dict[str, str]:
    """Recall matching incidents and prepare a cautious, evidence-aware brief."""
    try:
        memories = recall_incidents(
            RecallIncidentsInput(
                query=(
                    f"Service: {payload.service}\nSymptoms: {payload.symptoms}\n"
                    f"Recent changes: {payload.recent_changes}"
                )
            )
        )
        brief = reflect_mitigation(
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
def analyze_live_incident(payload: LiveAnalyzeRequest) -> dict[str, object]:
    """Run an isolated, current incident review against operator-approved history."""
    try:
        memories = recall_incidents(
            RecallIncidentsInput(
                query=(
                    f"Service: {payload.service}\nSymptoms: {payload.symptoms}\n"
                    f"Recent changes: {payload.recent_changes}"
                )
            ),
            bank_id=LIVE_BANK_ID,
        )
        if memories.startswith("No relevant") or memories.startswith("No clearly"):
            matches: list[str] = []
        else:
            matches = [item.split(": ", 1)[1] for item in memories.split("\n\n") if ": " in item]

        context = (
            f"Affected service: {payload.service}\nObserved symptoms: {payload.symptoms}\n"
            f"Recent changes: {payload.recent_changes}\nDo-not-cross constraints: {payload.constraints}\n"
            f"Relevant operator-confirmed history, if any: {memories}"
        )
        investigation = hindsight.reflect(
            bank_id=LIVE_BANK_ID,
            query=(
                "Act as Rock, the incident investigator. In plain language, give a short "
                "evidence-aware response with these headings: 'What we know', 'Most likely "
                "cause (and confidence)', 'Possible fix', and 'Check next' with at most 3 "
                "read-only checks. "
                "Separate observations from guesses. Use matching past incident IDs only if "
                "they appear in the provided history. If a matching verified past case supports "
                "a fix, suggest it as a proposal and state what must be checked before an "
                "operator approves it. If history does not support a fix, label any possible "
                "fix as a hypothesis, or say no safe fix can be suggested yet. Never claim "
                "you changed a system. "
                "Do not recommend destructive actions, production writes, or a restart as a "
                "first step. Keep the full answer under 150 words."
            ),
            context=context,
            budget="mid",
        ).text
        safety_review = hindsight.reflect(
            bank_id=LIVE_BANK_ID,
            query=(
                "Act as Salt, an independent safety reviewer. Review the incident facts, "
                "constraints, and Rock's proposed checks below. In plain language, list "
                "'Safe to do now' (read-only checks only), 'Wait for approval' (any action "
                "that changes production), and 'Unknowns to confirm'. Catch steps that "
                "could lose data, widen impact, or repeat a historical fix without verifying "
                "it applies. If Rock's advice is cautious, say that. Do not invent access or "
                "claim to have executed any action. Keep the answer under 100 words.\n\n"
                f"Rock's investigation: {investigation}"
            ),
            context=context,
            budget="mid",
        ).text
        return {
            "matches": matches[:2],
            "match_count": len(matches[:2]),
            "history_summary": (
                "These are saved, operator-confirmed incidents from your team."
                if matches else "No team incidents have been saved yet. This review uses only the details you entered."
            ),
            "investigation": investigation,
            "safety_review": safety_review,
        }
    except Exception as exc:
        logger.exception("Live incident analysis failed")
        raise HTTPException(
            status_code=502,
            detail="Echo could not reach incident memory right now. Please try again.",
        ) from exc


@app.post("/api/incident/record")
def save_incident(payload: RecordRequest) -> dict[str, str]:
    """Record an outcome only after explicit operator confirmation."""
    if not payload.operator_confirmed:
        raise HTTPException(
            status_code=400,
            detail="Confirm the resolution before saving it to incident memory.",
        )
    try:
        message = record_incident(
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
def save_live_incident(payload: LiveRecordRequest) -> dict[str, str]:
    """Store only a resolution explicitly approved by the incident operator."""
    if not payload.operator_confirmed:
        raise HTTPException(
            status_code=400,
            detail="Confirm that the incident team verified and approved this outcome before saving it.",
        )
    try:
        message = record_incident(
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
