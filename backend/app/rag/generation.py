"""
STEP 7: GENERATE. Send the prompt to the LLM and stream the answer back.

The LLM is reached through an "OpenAI-compatible" API. OpenRouter, Ollama,
LM Studio, vLLM and OpenAI itself all accept the same request format at
different URLs, so one client class (LangChain's ChatOpenAI) works for all of
them. Only LLM_BASE_URL, LLM_API_KEY and LLM_MODEL in .env change.
See app/llm.py for how the client is created.

Streaming:
  Instead of waiting for the whole answer, we ask for tokens as they are
  produced and forward each one to the browser. The answer appears word by
  word, and "time to first token" becomes a useful number to watch.

Query rewriting (optional, a small extra LLM call BEFORE retrieval):
  A follow-up such as "and how much does it cost?" is a poor search query on
  its own, because "it" matches nothing useful. We ask the LLM to rewrite it,
  using the conversation, into a standalone question ("How much does the Pro
  plan cost?"), and search with THAT. The original question is still what the
  user sees and what the final prompt asks.
"""

from collections.abc import AsyncIterator

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage

from .prompting import build_rewrite_messages


async def rewrite_query(llm: BaseChatModel, question: str, history: list[dict]) -> str:
    """Ask the LLM to turn a follow-up question into a standalone search query."""
    response = await llm.ainvoke(build_rewrite_messages(question, history))
    rewritten = str(response.content).strip().strip('"').strip()
    # Guard against a chatty or empty reply: fall back to the original question.
    if not rewritten or len(rewritten) > max(400, 3 * len(question)):
        return question
    return rewritten


async def stream_answer(llm: BaseChatModel, messages: list[BaseMessage]) -> AsyncIterator[str]:
    """Stream the LLM's answer, yielding each non-empty piece of text as it arrives."""
    async for chunk in llm.astream(messages):
        if chunk.content:
            yield str(chunk.content)
