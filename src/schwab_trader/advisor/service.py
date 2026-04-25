"""Claude-powered portfolio advisor with live tool-calling agent loop."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Generator

import anthropic

from schwab_trader.agent.tools import TOOL_SCHEMAS, ToolExecutor
from schwab_trader.broker.service import SchwabBrokerService

logger = logging.getLogger(__name__)

_MAX_TOOL_ROUNDS = 6

_CHAT_MODEL = "claude-sonnet-4-6"   # interactive advisor — fast
_SCAN_MODEL = "claude-opus-4-6"     # buy/sell scans — deepest reasoning

# Beta headers: token-efficient tool schemas (~40% fewer tokens for tool definitions)
_BETA_HEADERS = {"anthropic-beta": "token-efficient-tools-2025-02-19"}

# Tool schemas with cache_control on the last entry — caches the entire tool list prefix
_CACHED_TOOL_SCHEMAS = [
    *TOOL_SCHEMAS[:-1],
    {**TOOL_SCHEMAS[-1], "cache_control": {"type": "ephemeral"}},
]

# Cached system prompt block — static content cached at the API layer (5-min TTL, auto-renewed)
_SYSTEM_BLOCK = [
    {
        "type": "text",
        "text": (
            "You are a sharp, direct personal finance advisor and asset manager with live "
            "access to the user's Schwab portfolio. You speak plainly — no fluff, no disclaimers "
            'about "consulting a professional." You give real, specific, actionable advice '
            "tailored to their exact holdings.\n\n"
            "You have live tools you should use proactively:\n"
            "- get_portfolio: current positions, values, P&L\n"
            "- get_price_history: OHLCV chart data for any symbol\n"
            "- get_news: recent headlines and analyst takes\n"
            "- get_earnings_calendar: upcoming earnings dates and fundamentals\n\n"
            "Always fetch live data before answering questions about the portfolio or specific stocks. "
            "Do not ask the user for data you can look up yourself.\n\n"
            "## Visualizations — MANDATORY\n"
            "ALWAYS use Python matplotlib/numpy/pandas for any chart, graph, or visual data. "
            "NEVER output ASCII charts, text-based graphs, or emoji bar charts. "
            "The dashboard runs your ```python blocks server-side and renders charts inline.\n\n"
            "Rules:\n"
            "- Any time-series data → line chart in Python\n"
            "- Any allocation or composition → pie or bar chart in Python\n"
            "- Any comparison across stocks → bar chart in Python\n"
            "- Any P&L, return, or performance data → chart in Python\n"
            "- Dark theme and axes styling are auto-applied — just write the data and plot calls\n\n"
            "Always use real numbers from your live tool calls. "
            "Fetch get_portfolio or get_price_history first, then pass the actual values into the chart.\n\n"
            "Example — portfolio allocation:\n"
            "```python\n"
            "import matplotlib.pyplot as plt\n"
            "import numpy as np\n"
            "labels = ['SOXX', 'AAPL', 'NVDA', 'QQQ', 'Other']\n"
            "values = [9200, 7800, 5400, 4100, 8300]\n"
            "fig, ax = plt.subplots(figsize=(7, 4))\n"
            "colors = ['#2563EB','#22C55E','#F59E0B','#8B5CF6','#64748B']\n"
            "bars = ax.barh(labels, values, color=colors, edgecolor='none', height=0.6)\n"
            "ax.bar_label(bars, fmt='$%.0f', padding=6, color='#E8EDF5', fontsize=10)\n"
            "ax.set_xlabel('Market Value ($)')\n"
            "ax.set_title('Portfolio Allocation', fontsize=13, fontweight='bold')\n"
            "plt.tight_layout()\n"
            "```\n\n"
            "## Formatting\n"
            "Use markdown: **bold**, bullet lists, markdown tables (| col | col |), and headers. "
            "Use markdown tables for small comparisons (under 6 rows). "
            "Use Python charts for anything with more data or that benefits from a visual.\n\n"
            "Keep answers concise and sharp. Be the advisor they'd pay $500/hr for."
        ),
        "cache_control": {"type": "ephemeral"},
    }
]

# Keep plain string for backward-compat with run_agent system_override paths
_SYSTEM = _SYSTEM_BLOCK[0]["text"]

_SYSTEM = (
    "You are a sharp, direct personal finance advisor and asset manager with live "
    "access to the user's Schwab portfolio. You speak plainly — no fluff, no disclaimers "
    'about "consulting a professional." You give real, specific, actionable advice '
    "tailored to their exact holdings.\n\n"
    "You have live tools you should use proactively:\n"
    "- get_portfolio: current positions, values, P&L\n"
    "- get_price_history: OHLCV chart data for any symbol\n"
    "- get_news: recent headlines and analyst takes\n"
    "- get_earnings_calendar: upcoming earnings dates and fundamentals\n\n"
    "Always fetch live data before answering questions about the portfolio or specific stocks. "
    "Do not ask the user for data you can look up yourself.\n\n"
    "## Visualizations — MANDATORY\n"
    "ALWAYS use Python matplotlib/numpy/pandas for any chart, graph, or visual data. "
    "NEVER output ASCII charts, text-based graphs, or emoji bar charts. "
    "The dashboard runs your ```python blocks server-side and renders charts inline.\n\n"
    "Rules:\n"
    "- Any time-series data → line chart in Python\n"
    "- Any allocation or composition → pie or bar chart in Python\n"
    "- Any comparison across stocks → bar chart in Python\n"
    "- Any P&L, return, or performance data → chart in Python\n"
    "- Dark theme and axes styling are auto-applied — just write the data and plot calls\n\n"
    "Always use real numbers from your live tool calls. "
    "Fetch get_portfolio or get_price_history first, then pass the actual values into the chart.\n\n"
    "Example — portfolio allocation:\n"
    "```python\n"
    "import matplotlib.pyplot as plt\n"
    "import numpy as np\n"
    "labels = ['SOXX', 'AAPL', 'NVDA', 'QQQ', 'Other']\n"
    "values = [9200, 7800, 5400, 4100, 8300]\n"
    "fig, ax = plt.subplots(figsize=(7, 4))\n"
    "colors = ['#2563EB','#22C55E','#F59E0B','#8B5CF6','#64748B']\n"
    "bars = ax.barh(labels, values, color=colors, edgecolor='none', height=0.6)\n"
    "ax.bar_label(bars, fmt='$%.0f', padding=6, color='#E8EDF5', fontsize=10)\n"
    "ax.set_xlabel('Market Value ($)')\n"
    "ax.set_title('Portfolio Allocation', fontsize=13, fontweight='bold')\n"
    "plt.tight_layout()\n"
    "```\n\n"
    "## Formatting\n"
    "Use markdown: **bold**, bullet lists, markdown tables (| col | col |), and headers. "
    "Use markdown tables for small comparisons (under 6 rows). "
    "Use Python charts for anything with more data or that benefits from a visual.\n\n"
    "Keep answers concise and sharp. Be the advisor they'd pay $500/hr for."
)


class AdvisorService:
    """Wraps Claude API with a tool-calling agent loop for live portfolio intelligence."""

    def __init__(self, broker_service: SchwabBrokerService, api_key: str) -> None:
        self._broker = broker_service
        self._client = anthropic.Anthropic(api_key=api_key)
        self._executor = ToolExecutor(broker_service)

    # ------------------------------------------------------------------
    # Interactive chat (streaming)
    # ------------------------------------------------------------------

    def stream_chat(
        self, message: str, history: list[dict], portfolio_context: str
    ) -> Generator[str]:
        """Agent loop: execute tool calls until end_turn, yielding streamed text chunks."""
        messages = [*history, {"role": "user", "content": message}]
        yield from self._agent_stream(messages, depth=0)

    def _agent_stream(
        self, messages: list[dict], depth: int
    ) -> Generator[str | dict]:
        if depth >= _MAX_TOOL_ROUNDS:
            logger.warning("AdvisorService: agent stream hit max rounds (%d)", _MAX_TOOL_ROUNDS)
            return

        with self._client.messages.stream(
            model=_CHAT_MODEL,
            max_tokens=4096,
            system=_SYSTEM_BLOCK,
            tools=_CACHED_TOOL_SCHEMAS,
            messages=messages,
            extra_headers=_BETA_HEADERS,
        ) as stream:
            yield from stream.text_stream
            final = stream.get_final_message()

        if final.stop_reason != "tool_use":
            return

        # Emit tool names so the UI can show a live "fetching…" indicator
        tool_names = [b.name for b in final.content if b.type == "tool_use"]
        if tool_names:
            yield {"status": "thinking", "tools": tool_names}

        tool_results = self._run_tool_calls(final.content)
        next_messages = [
            *messages,
            {"role": "assistant", "content": final.content},
            {"role": "user", "content": tool_results},
        ]
        yield from self._agent_stream(next_messages, depth + 1)

    # ------------------------------------------------------------------
    # Non-streaming agent run (for background scans / structured JSON)
    # ------------------------------------------------------------------

    def run_agent(
        self,
        prompt: str,
        system_override: str | None = None,
        max_rounds: int = _MAX_TOOL_ROUNDS,
    ) -> str:
        """Run a non-streaming agent loop. Returns complete response text.

        Intended for background jobs (e.g. portfolio scan) that need a full
        JSON response rather than streamed text chunks.
        """
        messages: list[dict] = [{"role": "user", "content": prompt}]
        # Use cached system block when using the default system; plain string for overrides
        system: list[dict] | str = (
            _SYSTEM_BLOCK if system_override is None else system_override
        )
        tools = _CACHED_TOOL_SCHEMAS

        for round_num in range(max_rounds):
            current_messages = messages
            response = self._call_with_retry(
                lambda current_messages=current_messages: self._client.messages.create(
                    model=_SCAN_MODEL,
                    max_tokens=4096,
                    system=system,
                    tools=tools,
                    messages=current_messages,
                    extra_headers=_BETA_HEADERS,
                )
            )

            cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
            if cache_read:
                logger.debug("run_agent round %d: cache hit (%d tokens)", round_num + 1, cache_read)

            if response.stop_reason != "tool_use":
                return "".join(
                    block.text for block in response.content if hasattr(block, "text")
                )

            logger.debug(
                "run_agent round %d: %d tool call(s)", round_num + 1,
                sum(1 for b in response.content if b.type == "tool_use"),
            )
            tool_results = self._run_tool_calls(response.content)
            messages = [
                *messages,
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": tool_results},
            ]

        # Hit round limit — force a final response without tools so we don't return empty
        logger.warning("run_agent: hit max rounds (%d), forcing final output", max_rounds)
        try:
            final = self._call_with_retry(
                lambda: self._client.messages.create(
                    model=_SCAN_MODEL,
                    max_tokens=4096,
                    system=system,
                    # No tools passed — forces text-only response
                    messages=[
                        *messages,
                        {
                            "role": "user",
                            "content": (
                                "Research complete. Output your final answer now as plain JSON "
                                "with no markdown fences and no explanation text. "
                                'Start your response with "{" and end with "}".'
                            ),
                        },
                    ],
                    extra_headers=_BETA_HEADERS,
                )
            )
            text = "".join(
                block.text for block in final.content if hasattr(block, "text")
            )
            logger.info("run_agent forced-final response (%d chars): %r", len(text), text[:200])
            return text
        except Exception:
            logger.exception("run_agent: failed to force final output")
            return ""

    @staticmethod
    def _call_with_retry(fn, max_retries: int = 4):
        """Retry on rate-limit (429) and transient server errors (5xx) with exponential backoff."""
        for attempt in range(max_retries):
            try:
                return fn()
            except anthropic.RateLimitError:
                wait = (2 ** attempt) + random.uniform(0, 1)
                logger.warning("Claude rate limit hit — retry %d in %.1fs", attempt + 1, wait)
                time.sleep(min(wait, 60))
            except anthropic.APIStatusError as exc:
                if exc.status_code >= 500:
                    wait = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning("Claude %d error — retry %d in %.1fs", exc.status_code, attempt + 1, wait)
                    time.sleep(min(wait, 60))
                else:
                    raise  # 4xx errors are caller bugs — don't retry
        raise RuntimeError(f"Claude API: max retries ({max_retries}) exceeded")

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    # Max characters per tool result kept in context (~10k chars ≈ ~2500 tokens)
    _MAX_TOOL_RESULT_CHARS = 10_000

    def _run_tool_calls(self, content: list) -> list[dict]:
        """Execute all tool_use blocks in a response content list."""
        results = []
        for block in content:
            if block.type != "tool_use":
                continue
            logger.debug("Tool call: %s(%s)", block.name, block.input)
            result = self._executor.execute(block.name, block.input)
            result = self._trim_tool_result(block.name, result)
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })
        return results

    def _trim_tool_result(self, tool_name: str, result: str) -> str:
        """Trim oversized tool results to protect context window.

        For get_price_history: drop raw candle array (Claude only needs summary stats).
        For all tools: hard cap at _MAX_TOOL_RESULT_CHARS with a truncation notice.
        """
        import json as _json

        # get_price_history: strip the candles array — Claude needs summary, not raw OHLCV
        if tool_name == "get_price_history":
            try:
                data = _json.loads(result)
                data.pop("candles", None)
                result = _json.dumps(data)
            except Exception:
                pass

        # Hard cap: truncate and append notice so Claude knows data was trimmed
        if len(result) > self._MAX_TOOL_RESULT_CHARS:
            truncated = result[: self._MAX_TOOL_RESULT_CHARS]
            # Try to close the JSON cleanly at last complete value boundary
            last_comma = max(truncated.rfind(","), truncated.rfind("}"))
            if last_comma > self._MAX_TOOL_RESULT_CHARS // 2:
                truncated = truncated[: last_comma]
            result = truncated + ' ... [truncated — full data available, ask for specifics]"}'
            logger.debug("Trimmed tool result for %s to %d chars", tool_name, len(result))

        return result
