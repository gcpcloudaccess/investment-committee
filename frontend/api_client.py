import os

import httpx
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")

# A committee tick analyzes up to 4 symbols, each running ~14 agent LLM calls
# (bounded to 4 concurrent) - this reliably takes 2-2.5 minutes in practice.
# Keep a generous margin above that rather than the httpx default of a few
# seconds, or "Run Tick Now" / "Stock Search" will time out mid-analysis.
TIMEOUT_SECONDS = 420.0


def _client() -> httpx.Client:
    return httpx.Client(base_url=BACKEND_URL, timeout=TIMEOUT_SECONDS)


def get(path: str, silent: bool = False, **params):
    """silent=True returns None on a failed request instead of halting the whole
    page — for optional widgets (e.g. a stock chart) that shouldn't take down a
    dashboard that's otherwise fine."""
    try:
        with _client() as c:
            resp = c.get(path, params=params or None)
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        if silent:
            return None
        st.error(f"Cannot reach backend at {BACKEND_URL}. Is `uvicorn app.main:app` running?")
        st.stop()
    except httpx.TimeoutException:
        if silent:
            return None
        st.error(f"Backend didn't respond within {TIMEOUT_SECONDS:.0f}s. It may still be finishing in the background — try refreshing shortly.")
        st.stop()
    except httpx.HTTPStatusError as e:
        if silent:
            return None
        st.error(f"Backend error on {path}: {e.response.status_code} {e.response.text}")
        st.stop()


def get_bytes(path: str) -> bytes | None:
    """Like get(), but for binary responses (e.g. PDF downloads) - the frontend
    and backend are separate deployed services with no shared filesystem, so
    file content always has to come back over HTTP, never via a local open()."""
    try:
        with _client() as c:
            resp = c.get(path)
            resp.raise_for_status()
            return resp.content
    except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
        return None


def post(path: str, **params):
    try:
        with _client() as c:
            resp = c.post(path, params=params or None)
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        st.error(f"Cannot reach backend at {BACKEND_URL}. Is `uvicorn app.main:app` running?")
        st.stop()
    except httpx.TimeoutException:
        st.error(f"Backend didn't respond within {TIMEOUT_SECONDS:.0f}s. It may still be finishing in the background — try refreshing shortly.")
        st.stop()
    except httpx.HTTPStatusError as e:
        st.error(f"Backend error on {path}: {e.response.status_code} {e.response.text}")
        st.stop()
