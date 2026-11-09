"""Read-only incident details from the configured GitHub Issues repository."""

from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_GITHUB_REPOSITORY = "mayankraj7640204-ops/Echo"
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class IncidentSourceError(RuntimeError):
    """The configured incident source could not be reached or read."""


def github_repository() -> str:
    repository = os.getenv("GITHUB_REPOSITORY", DEFAULT_GITHUB_REPOSITORY).strip()
    if not REPOSITORY_PATTERN.fullmatch(repository):
        raise IncidentSourceError("Set GITHUB_REPOSITORY as owner/repository.")
    return repository


def _fetch_issue(repository: str, number: str) -> dict[str, object] | None:
    url = f"https://api.github.com/repos/{repository}/issues/{number}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Echo-Incident-Response",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=8) as response:
            issue = json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code in (401, 403):
            raise IncidentSourceError(
                "GitHub could not read this issue. Check the repository and read-only token settings."
            ) from exc
        raise IncidentSourceError("GitHub could not return this issue right now.") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise IncidentSourceError("GitHub could not be reached right now.") from exc

    if not isinstance(issue, dict):
        raise IncidentSourceError("GitHub returned an unexpected issue response.")
    # Pull requests also use GitHub's Issues API, but they are not incident reports.
    if issue.get("pull_request"):
        return None
    return issue


async def lookup_github_issue(incident_id: str) -> dict[str, str] | None:
    """Fetch a GitHub issue using the incident ID as its issue number."""
    import asyncio

    number = incident_id.strip().lstrip("#")
    if not number.isdigit() or not 1 <= len(number) <= 12:
        return None
    repository = github_repository()
    issue = await asyncio.to_thread(_fetch_issue, repository, number)
    if issue is None:
        return None

    labels = [
        str(label.get("name", ""))
        for label in issue.get("labels", [])
        if isinstance(label, dict) and label.get("name")
    ]
    title = str(issue.get("title") or "Untitled issue").strip()
    body = str(issue.get("body") or "").strip()
    return {
        "number": str(issue.get("number", number)),
        "title": title,
        "body": body[:4000],
        "state": str(issue.get("state") or "unknown"),
        "labels": ", ".join(labels),
        "url": f"https://github.com/{repository}/issues/{number}",
        "repository": repository,
    }
