"""Full MCP parity — expose ALL EcoDB MCP tools as LangChain tools.

The native ``make_ecodb_tools`` exposes a curated agentic subset (9 tools). When
you want every tool the EcoDB MCP server publishes (the full ~32: memories,
graph, documents, identity, admin), point ``langchain-mcp-adapters`` at the
running MCP server and it converts them all into LangChain tools automatically,
reading the MCP's own schemas — so parity is guaranteed and stays in sync as
EcoDB adds tools.

Requires the EcoDB MCP server running (``docker compose up mcp``) and
``pip install "ecodb-langchain[mcp]"``.

    import asyncio
    from ecodb_langchain import build_ecodb_agent_from_mcp

    agent = asyncio.run(build_ecodb_agent_from_mcp())
    agent.invoke({"messages": [("user", "register this document and link it")]})
"""

from __future__ import annotations

import os
from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

# EcoDB MCP server speaks SSE on :8091 by default.
DEFAULT_MCP_URL = os.environ.get("ECODB_MCP_URL", "http://localhost:8091/sse")


async def load_ecodb_mcp_tools(
    url: Optional[str] = None,
    *,
    transport: str = "sse",
) -> list[BaseTool]:
    """Load EVERY EcoDB MCP tool as a LangChain tool (full parity, ~32 tools).

    Args:
        url: MCP server endpoint. Defaults to ``$ECODB_MCP_URL`` or
            ``http://localhost:8091/sse``.
        transport: MCP transport — ``"sse"`` (default) or ``"streamable_http"``.

    Returns:
        A list of LangChain ``BaseTool`` — one per MCP tool, names and schemas
        taken straight from the MCP server.
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient

    url = url or DEFAULT_MCP_URL
    client = MultiServerMCPClient({"ecodb": {"url": url, "transport": transport}})
    return await client.get_tools()


async def build_ecodb_agent_from_mcp(
    llm: Optional[BaseChatModel] = None,
    *,
    mcp_url: Optional[str] = None,
    transport: str = "sse",
    system_prompt: Optional[str] = None,
    checkpointer=None,
):
    """Build a LangGraph agent wired to the FULL EcoDB MCP toolset (parity).

    Same StateGraph ReAct loop as ``build_ecodb_agent``, but the tools are every
    tool the MCP server publishes rather than the curated native subset.
    """
    from .agent import build_ecodb_agent, default_llm

    tools = await load_ecodb_mcp_tools(mcp_url, transport=transport)
    return build_ecodb_agent(
        llm=llm if llm is not None else default_llm(),
        tools=tools,
        system_prompt=system_prompt,
        checkpointer=checkpointer,
    )
