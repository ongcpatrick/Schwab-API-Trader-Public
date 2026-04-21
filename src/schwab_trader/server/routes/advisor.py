"""Advisor chat endpoint with streaming."""

import base64
import io
import json
import subprocess
import sys
import textwrap
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from schwab_trader.advisor.service import AdvisorService
from schwab_trader.broker.service import SchwabBrokerService
from schwab_trader.core.settings import get_settings
from schwab_trader.server.dependencies import get_broker_service

router = APIRouter()


class ChatMessage(BaseModel):
    """A single message in the conversation history."""

    role: str
    content: str


class ChatRequest(BaseModel):
    """Incoming chat request with message and optional history."""

    message: str
    history: list[ChatMessage] = []


def get_advisor_service(
    broker_service: Annotated[SchwabBrokerService, Depends(get_broker_service)],
) -> AdvisorService:
    """Build an AdvisorService with the current broker and API key."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ANTHROPIC_API_KEY not configured.",
        )
    return AdvisorService(broker_service=broker_service, api_key=settings.anthropic_api_key)


@router.get("/quick-take/{symbol}")
def quick_take(
    symbol: str,
    advisor: Annotated[AdvisorService, Depends(get_advisor_service)],
) -> dict:
    """Return a 2-3 sentence Claude analysis for a single stock."""
    prompt = (
        f"Give me a 2-3 sentence sharp take on {symbol.upper()} right now. "
        f"Use get_stock_fundamentals to check valuation and analyst targets, "
        f"and get_news for recent developments. "
        f"Return ONLY valid JSON: "
        f'{{ "take": "your 2-3 sentence analysis", "signal": "BUY" | "HOLD" | "TRIM" | "AVOID" }}'
    )
    system = (
        "You are a sharp buy-side analyst. Use your tools. "
        "Return concise JSON only. No Markdown."
    )
    raw = advisor.run_agent(prompt, system_override=system, max_rounds=4)
    try:
        stripped = raw.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("```", 2)[1]
            if stripped.startswith("json"):
                stripped = stripped[4:]
            stripped = stripped.rsplit("```", 1)[0].strip()
        start = stripped.find("{"); end = stripped.rfind("}") + 1
        if start != -1 and end > 0:
            return json.loads(stripped[start:end])
    except Exception:
        pass
    return {"take": raw[:400] if raw else "Unable to generate analysis.", "signal": "HOLD"}


@router.post("/chat")
def advisor_chat(
    payload: ChatRequest,
    advisor: Annotated[AdvisorService, Depends(get_advisor_service)],
) -> StreamingResponse:
    """Stream a Claude advisor response. Claude fetches live portfolio data via tools."""
    history = [{"role": m.role, "content": m.content} for m in payload.history]

    def generate():
        try:
            for chunk in advisor.stream_chat(payload.message, history, ""):
                if isinstance(chunk, dict):
                    yield f"data: {json.dumps(chunk)}\n\n"
                else:
                    yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Dark-theme matplotlib defaults injected before every user script
_MATPLOTLIB_PREAMBLE = textwrap.dedent("""\
    import sys as _sys, io as _io, base64 as _b64, json as _json, traceback as _tb
    _stdout = _io.StringIO()
    _sys.stdout = _stdout
    _img_b64 = None
    _error = None

    try:
        import matplotlib as _mpl
        _mpl.use('Agg')
        import matplotlib.pyplot as plt
        import numpy as np
        try:
            import pandas as pd
        except ImportError:
            pass
        plt.rcParams.update({
            'figure.facecolor':  '#0E1318',
            'axes.facecolor':    '#141A22',
            'axes.edgecolor':    '#2D3748',
            'axes.labelcolor':   '#E8EDF5',
            'axes.spines.top':   False,
            'axes.spines.right': False,
            'grid.color':        '#222B38',
            'grid.linestyle':    '--',
            'grid.linewidth':    0.5,
            'text.color':        '#E8EDF5',
            'xtick.color':       '#7A8599',
            'ytick.color':       '#7A8599',
            'lines.color':       '#2563EB',
            'patch.edgecolor':   '#0E1318',
        })
    except ImportError:
        pass

    try:
""")

_MATPLOTLIB_POSTAMBLE = textwrap.dedent("""\
    except Exception:
        _error = _tb.format_exc()

    _sys.stdout = _sys.__stdout__

    try:
        import matplotlib.pyplot as plt
        if plt.get_fignums():
            _buf = _io.BytesIO()
            plt.savefig(_buf, format='png', dpi=150, bbox_inches='tight',
                        facecolor='#0E1318', edgecolor='none')
            _buf.seek(0)
            _img_b64 = _b64.b64encode(_buf.read()).decode()
            plt.close('all')
    except Exception:
        pass

    print(_json.dumps({
        'output': _stdout.getvalue(),
        'image_b64': _img_b64,
        'error': _error,
    }))
""")


@router.post("/exec-python")
def exec_python(payload: dict) -> dict:
    """Execute a Python snippet and return stdout + matplotlib chart as base64 PNG."""
    code = payload.get("code", "").strip()
    if not code:
        return {"output": "", "image_b64": None, "error": "No code provided."}

    # Indent user code into the try block
    indented = textwrap.indent(code, "    ")
    full_script = _MATPLOTLIB_PREAMBLE + indented + "\n" + _MATPLOTLIB_POSTAMBLE

    try:
        proc = subprocess.run(
            [sys.executable, "-c", full_script],
            capture_output=True,
            text=True,
            timeout=30,
        )
        stdout = proc.stdout.strip()
        if not stdout:
            stderr = proc.stderr.strip()
            return {"output": "", "image_b64": None, "error": stderr or "Script produced no output."}
        return json.loads(stdout)
    except subprocess.TimeoutExpired:
        return {"output": "", "image_b64": None, "error": "Execution timed out (30 s)."}
    except json.JSONDecodeError:
        return {"output": proc.stdout, "image_b64": None, "error": None}
    except Exception as exc:
        return {"output": "", "image_b64": None, "error": str(exc)}
