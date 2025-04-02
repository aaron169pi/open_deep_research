import os
from enum import Enum
from dataclasses import dataclass, fields
from typing import Any, Optional, Dict 

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from dataclasses import dataclass

DEFAULT_REPORT_STRUCTURE = """Use this structure to create a comprehensive and well-organized report on the user-provided topic:

1. Introduction (no external research required)
    - Provide a brief overview of the topic
    - Highlight the importance or relevance of the topic

2. Main Body Sections: (external research required)
    - Divide the topic into logical sub-topics or themes
    - Provide detailed explanations, supported by examples or data where applicable
    - Ensure smooth transitions between sections for better readability

3. Conclusion:
    - Summarize the key points discussed in the main body
    - Include one structural element (e.g., a table, or list) to distill the main findings
    - Provide a concise and insightful summary of the report's overall message"""

class SearchAPI(Enum):
    PERPLEXITY = "perplexity"
    TAVILY = "tavily"
    EXA = "exa"
    ARXIV = "arxiv"
    PUBMED = "pubmed"
    LINKUP = "linkup"
    DUCKDUCKGO = "duckduckgo"
    GOOGLESEARCH = "googlesearch"

@dataclass(kw_only=True)
class Configuration:
    """The configurable fields for the chatbot."""
    report_structure: str = DEFAULT_REPORT_STRUCTURE # Defaults to the default report structure
    number_of_queries: int = 5 # Number of search queries to generate per iteration
    max_search_depth: int = 3 # Maximum number of reflection + search iterations
    planner_provider: str = "google_genai"  # Defaults to Anthropic as provider
    planner_model: str = "gemini-2.5-pro-exp-03-25" # Defaults to claude-3-7-sonnet-latest
    writer_provider: str = "google_genai" # Defaults to Anthropic as provider
    writer_model: str = "gemini-2.5-pro-exp-03-25" # Defaults to claude-3-5-sonnet-latest
    search_api: SearchAPI = SearchAPI.TAVILY # Default to TAVILY
    max_token: int = 30000 #Default to 30000
    search_api_config: Optional[Dict[str, Any]] = None 

    @classmethod
    def from_runnable_config(
        cls, config: Optional[RunnableConfig] = None
    ) -> "Configuration":
        """Create a Configuration instance from a RunnableConfig."""
        configurable = (
            config["configurable"] if config and "configurable" in config else {}
        )
        values: dict[str, Any] = {
            f.name: os.environ.get(f.name.upper(), configurable.get(f.name))
            for f in fields(cls)
            if f.init
        }
        return cls(**{k: v for k, v in values.items() if v})
