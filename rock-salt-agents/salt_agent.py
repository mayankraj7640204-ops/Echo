"""Salt the mouse agent (Codex)."""

from __future__ import annotations

import asyncio
import logging

from dotenv import load_dotenv

from characters import generate_jerry_prompt

from band import Agent, configure_logging
from band.adapters.codex import CodexAdapter, CodexAdapterConfig
from band.core.types import Emit

configure_logging(
    level=logging.INFO,
    root_level=logging.INFO,
    stream="stdout",
    extra_loggers={
        "websockets": logging.WARNING,
        "httpx": logging.WARNING,
    },
)
logger = logging.getLogger(__name__)


async def main() -> None:
    load_dotenv()

    # model self-sources from CODEX_MODEL when omitted here.
    adapter = CodexAdapter(
        config=CodexAdapterConfig(
            transport="stdio",
            personality="none",
            custom_section=generate_jerry_prompt("Salt", "Rock"),
            include_base_instructions=True,
        ),
        emit={Emit.TASK_EVENTS, Emit.THOUGHTS},
    )

    logger.info("Salt is connected and ready.")
    async with Agent.from_config(
        "salt_agent",
        adapter=adapter,
    ) as agent:
        await agent.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
