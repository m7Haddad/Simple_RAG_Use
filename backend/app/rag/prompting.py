"""
STEP 6: PROMPT. Combine the question and the retrieved chunks into the exact text the LLM reads.

This is where "retrieval-augmented" happens: the LLM never sees your files,
only the handful of chunks we paste in here. If the answer is not in these
chunks, the model cannot know it, which is why the system prompt orders it to
say "I don't know" instead of guessing from its general training.

Layout of the final prompt (the Pipeline Inspector shows it verbatim):
  SYSTEM     rules + the numbered context block
  USER/AI    a few recent turns of conversation (so follow-ups make sense)
  USER       the current question

Each chunk is labelled "[n] file, page N" so the model can cite it, and so
you can check its claims against the sources list.
"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from .retrieval import RetrievedChunk

# The anti-hallucination guardrail: answer ONLY from the context, admit when
# the answer is not there, and cite the numbered sources.
SYSTEM_PROMPT = (
    "You are a helpful assistant answering questions using ONLY the provided "
    "context below. If the context does not contain the answer, say you don't "
    "know — do not use outside knowledge or guess.\n"
    "When you use information from the context, cite it with its number in "
    "square brackets, like [1] or [2].\n\n"
    "Context:\n{context}"
)

# When nothing was retrieved there is nothing to ground an answer in, so we
# answer directly and do not call the LLM at all.
NO_CONTEXT_ANSWER = "I don't know. This knowledge base has no indexed content to answer from yet."

# Used when chunks exist but none passed the min_relevance cutoff.
NO_RELEVANT_ANSWER = (
    "I don't know. Nothing in this knowledge base was close enough to your question. "
    "Try rephrasing it, or lower the minimum relevance setting."
)

# How much conversation history is replayed to the LLM. More history helps
# follow-up questions, but costs tokens and can drown out the context.
MAX_HISTORY_MESSAGES = 6
MAX_HISTORY_CHARS = 1500  # per message

# Instructions for the query-rewrite LLM call (see generation.py).
REWRITE_PROMPT = (
    "Rewrite the user's latest question as a single standalone question that "
    "can be understood without the conversation. Resolve pronouns like "
    "\"it\" or \"that\" using the conversation. Keep the original language and "
    "meaning, and do not answer it. If it is already standalone, return it "
    "unchanged. Reply with the question only."
)


def citation_label(chunk: RetrievedChunk) -> str:
    """The "file, page N" label shown for a chunk."""
    meta = chunk.document.metadata
    return f"{meta.get('source_name', 'unknown source')}, {meta.get('location', 'page ?')}"


def format_context(chunks: list[RetrievedChunk]) -> str:
    """Join the retrieved chunks into the numbered context block. [1] is the closest match."""
    blocks = [f"[{c.rank}] {citation_label(c)}\n{c.document.page_content.strip()}" for c in chunks]
    return "\n\n---\n\n".join(blocks)


def history_messages(history: list[dict]) -> list[BaseMessage]:
    """Convert the most recent chat turns into LLM messages, truncating the long ones."""
    messages: list[BaseMessage] = []
    for turn in history[-MAX_HISTORY_MESSAGES:]:
        text = turn["content"][:MAX_HISTORY_CHARS]
        messages.append(HumanMessage(text) if turn["role"] == "user" else AIMessage(text))
    return messages


def build_messages(question: str, chunks: list[RetrievedChunk], history: list[dict]) -> list[BaseMessage]:
    """Assemble the full prompt: system rules + context, then history, then the question."""
    system = SystemMessage(SYSTEM_PROMPT.format(context=format_context(chunks)))
    return [system, *history_messages(history), HumanMessage(question)]


def build_rewrite_messages(question: str, history: list[dict]) -> list[BaseMessage]:
    """Assemble the prompt for the query-rewrite call: the recent conversation, then the question to rewrite."""
    transcript = "\n".join(
        f"{'User' if t['role'] == 'user' else 'Assistant'}: {t['content'][:500]}"
        for t in history[-MAX_HISTORY_MESSAGES:]
    )
    return [
        SystemMessage(REWRITE_PROMPT),
        HumanMessage(f"Conversation:\n{transcript}\n\nLatest question: {question}\n\nStandalone question:"),
    ]


def render_prompt(messages: list[BaseMessage]) -> str:
    """Plain-text view of the messages, exactly as sent, for the Pipeline Inspector."""
    names = {"system": "SYSTEM", "human": "USER", "ai": "ASSISTANT"}
    return "\n\n".join(f"===== {names.get(m.type, m.type.upper())} =====\n{m.content}" for m in messages)


def role_of(message: BaseMessage) -> str:
    """Map LangChain message types to the usual chat roles: system, user, assistant."""
    return {"system": "system", "human": "user", "ai": "assistant"}.get(message.type, message.type)
