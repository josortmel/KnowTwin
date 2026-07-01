"""ecodb-langchain — LangChain / LangGraph integration for EcoDB."""

from .agent import DEFAULT_SYSTEM_PROMPT, build_ecodb_agent, default_llm
from .cell_agent import acell_llm_call, make_cell_llm
from .client import EcoDBClient, EcoDBError
from .mcp_tools import build_ecodb_agent_from_mcp, load_ecodb_mcp_tools
from .memory import EcoDBMemory
from .retriever import EcoDBRetriever
from .tools import make_ecodb_tools

__version__ = "0.2.0"

__all__ = [
    "EcoDBClient",
    "EcoDBError",
    "make_ecodb_tools",
    "EcoDBRetriever",
    "EcoDBMemory",
    "build_ecodb_agent",
    "default_llm",
    "DEFAULT_SYSTEM_PROMPT",
    "load_ecodb_mcp_tools",
    "build_ecodb_agent_from_mcp",
    "make_cell_llm",
    "acell_llm_call",
    "__version__",
]
