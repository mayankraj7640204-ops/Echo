"""Send an Echo incident review to the live Rock and Salt agents on Band."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx


class BandReviewError(RuntimeError):
    """A safe, user-facing error from the Band review path."""


class BandBridge:
    def __init__(self) -> None:
        self.base_url = os.getenv("BAND_REST_URL", "https://app.band.ai").rstrip("/")
        self.user_key = os.getenv("BAND_USER_API_KEY", "")
        self.rock_id = os.getenv("BAND_ROCK_AGENT_ID", "")
        self.salt_id = os.getenv("BAND_SALT_AGENT_ID", "")

    @property
    def configured(self) -> bool:
        return bool(self.user_key and self.rock_id and self.salt_id)

    async def review(self, *, incident_context: str, room_title: str) -> dict[str, Any]:
        if not self.configured:
            raise BandReviewError(
                "The live Rock and Salt connection is not configured. Set the Band credentials in the server environment."
            )

        headers = {"X-API-Key": self.user_key}
        timeout = httpx.Timeout(15, connect=10)
        async with httpx.AsyncClient(
            base_url=f"{self.base_url}/api/v1/me",
            headers=headers,
            timeout=timeout,
        ) as client:
            peers = await self._request(client, "GET", "/peers", params={"page_size": 100})
            peer_rows = peers.get("data", [])
            by_id = {str(peer.get("id")): peer for peer in peer_rows}
            rock = by_id.get(self.rock_id)
            salt = by_id.get(self.salt_id)
            if not rock or not salt:
                raise BandReviewError("Echo could not find both Rock and Salt in the connected Band account.")
            unavailable = [agent.get("name", "Agent") for agent in (rock, salt) if not agent.get("online")]
            if unavailable:
                raise BandReviewError(
                    f"{', '.join(unavailable)} {'is' if len(unavailable) == 1 else 'are'} offline in Band. "
                    "Restart Echo's local agent service and try again."
                )

            room = await self._request(client, "POST", "/chats", json={"chat": {}})
            room_data = room.get("data", room)
            room_id = str(room_data.get("id") or room_data.get("chat_room_id") or "")
            if not room_id:
                raise BandReviewError("Band created a room but did not return its room ID.")

            for agent in (rock, salt):
                await self._request(
                    client,
                    "POST",
                    f"/chats/{room_id}/participants",
                    json={"participant": {"participant_id": agent["id"]}},
                )

            mentions = [self._mention(agent) for agent in (rock, salt)]
            mention_text = " ".join(f"@{mention['handle']}" for mention in mentions)
            message = (
                f"{mention_text} Review this current incident using the supplied facts and saved-history clues. "
                "Rock: investigate similarities, known facts, unknowns, and up to three safe read-only checks. "
                "Salt: independently review safety, distinguish checks from actions needing approval, and state key unknowns. "
                "Do not claim the cause is confirmed unless the evidence says so. Do not execute or authorize a fix. "
                "Write concise plain-language sections.\n\n"
                f"{incident_context}"
            )
            await self._request(
                client,
                "POST",
                f"/chats/{room_id}/messages",
                json={"message": {"content": message, "mentions": mentions}},
            )

            responses: dict[str, dict[str, str]] = {}
            deadline = asyncio.get_running_loop().time() + 120
            while asyncio.get_running_loop().time() < deadline:
                listed = await self._request(
                    client,
                    "GET",
                    f"/chats/{room_id}/messages",
                    params={"page": 1, "page_size": 100},
                )
                for item in listed.get("data", []):
                    sender_id = str(item.get("sender_id", ""))
                    if sender_id in {self.rock_id, self.salt_id} and item.get("message_type", "text") == "text":
                        content = self._plain_content(item.get("content", ""))
                        if content:
                            responses[sender_id] = {
                                "name": str(item.get("sender_name") or ("Rock" if sender_id == self.rock_id else "Salt")),
                                "content": content,
                            }
                if self.rock_id in responses and self.salt_id in responses:
                    break
                await asyncio.sleep(1.5)

            if self.rock_id not in responses or self.salt_id not in responses:
                raise BandReviewError(
                    "Rock and Salt received the incident, but their reviews did not both finish in time. "
                    f"Open the Band room {room_id} to see current activity, then retry if needed."
                )
            return {
                "investigation": responses[self.rock_id]["content"],
                "safety_review": responses[self.salt_id]["content"],
                "band_room_id": room_id,
                "band_room_title": room_title,
            }

    async def _request(self, client: httpx.AsyncClient, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise BandReviewError("Band returned an unexpected response while preparing the review.")
            return data
        except BandReviewError:
            raise
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if code in (401, 403):
                detail = "The Band connection was rejected. Check the server-side Band user key and account access."
            else:
                detail = f"Band could not complete the review setup (HTTP {code}). Please try again."
            raise BandReviewError(detail) from exc
        except httpx.HTTPError as exc:
            raise BandReviewError("Echo could not reach Band to run the live agent review. Please try again.") from exc

    @staticmethod
    def _mention(agent: dict[str, Any]) -> dict[str, str]:
        handle = str(agent.get("handle") or "").lstrip("@")
        return {"id": str(agent["id"]), "name": str(agent.get("name") or "Agent"), "handle": handle}

    @staticmethod
    def _plain_content(value: Any) -> str:
        if isinstance(value, str):
            return value.strip()
        return ""
