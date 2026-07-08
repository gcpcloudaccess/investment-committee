import streamlit as st

from api_client import get
from theme import inject_base_css, metric_card, page_header

st.set_page_config(page_title="Settings", page_icon="⚙️", layout="wide")
inject_base_css()
page_header("⚙️", "Settings", "Session configuration is read from `backend/.env` at backend startup — edit that file and restart the backend to change these")

settings = get("/settings")

st.subheader("Trading Session")
c1, c2, c3, c4 = st.columns(4)
c1.markdown(metric_card("Starting Capital", f"₹{settings['starting_capital_inr']:,.0f}"), unsafe_allow_html=True)
c2.markdown(metric_card("Leverage", f"1:{int(settings['leverage'])}"), unsafe_allow_html=True)
c3.markdown(metric_card("Session Length", f"{settings['session_hours']}h"), unsafe_allow_html=True)
c4.markdown(metric_card("Tick Interval", f"{settings['tick_minutes']} min"), unsafe_allow_html=True)

st.write("")
if settings["data_mode"] == "live":
    open_now = settings["currently_open_exchange"]
    data_mode_note = f"Currently trading **{open_now}**" if open_now else "All 4 exchanges are currently closed — the session runner will resume the moment one opens"
else:
    data_mode_note = "Replay of recent historical bars — demoable any time, single exchange only"
st.markdown(
    f'<div class="ic-card">Data Mode: <b style="color:#22D3EE;">{settings["data_mode"].upper()}</b> — {data_mode_note}</div>',
    unsafe_allow_html=True,
)

st.write("")
st.subheader("LLM Provider")
if settings["llm_key_configured"]:
    st.success(f"Provider `{settings['llm_provider']}` — API key configured, agents generate full LLM reasoning.")
else:
    st.error(
        f"No API key configured for `{settings['llm_provider']}`. Add `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` "
        "to `backend/.env` (matching `LLM_PROVIDER`) and restart the backend. Until then, agents fall back to "
        "deterministic templated reasoning — the math/consensus still works fully, just less richly worded."
    )

st.write("")
st.subheader("Exchanges (auto-switch when live)")
st.caption(
    "In LIVE mode, the session runner automatically trades whichever of these is currently open — one at a time — "
    "and rolls over to the next as markets close. Priority when more than one is open: India → Singapore → London → US."
)
for ex in settings["exchanges"]:
    status_color, status_text = ("#22C55E", "OPEN NOW") if ex["is_open"] else ("#64748B", "closed")
    st.markdown(
        f"""
        <div class="ic-card" style="display:flex; justify-content:space-between; align-items:center;">
            <div>
                <span style="font-weight:700; color:#F1F5F9; font-size:1.02rem;">{ex['label']}</span>
                <span class="ic-badge" style="margin-left:0.6rem; background:#131B2E;color:{status_color};border:1px solid {status_color};">{status_text}</span>
            </div>
            <div style="font-family:'SF Mono','Roboto Mono',monospace; color:#94A3B8; font-size:0.85rem;">
                {ex['open_time']}–{ex['close_time']} {ex['timezone']} · {ex['currency']} · {', '.join(ex['watchlist'])}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.write("")
st.subheader("NSE Watchlist (default/replay)")
st.markdown(
    " ".join(f'<span class="ic-badge" style="background:#131B2E;color:#93C5FD;border:1px solid #1E293B">{s}</span>' for s in settings["watchlist"]),
    unsafe_allow_html=True,
)

st.write("")
st.subheader("Investment Planner — Asset Allocation & Goals")
plan = get("/planner/allocation-plan")
p1, p2, p3, p4 = st.columns(4)
p1.markdown(metric_card("Risk Tolerance", plan["risk_tolerance"].capitalize()), unsafe_allow_html=True)
p2.markdown(metric_card("Per-Symbol Cap", f"₹{plan['symbol_cap_inr']:,.0f}"), unsafe_allow_html=True)
p3.markdown(metric_card("Per-Sector Cap", f"₹{plan['sector_cap_inr']:,.0f}"), unsafe_allow_html=True)
p4.markdown(
    metric_card("Profit Target / Loss Limit", f"+₹{plan['profit_target_inr']:,.0f} / ₹{plan['loss_limit_inr']:,.0f}"),
    unsafe_allow_html=True,
)
st.markdown(f'<div class="ic-card">{plan["reasoning"]}</div>', unsafe_allow_html=True)
st.caption(
    "Set via `RISK_TOLERANCE` in `backend/.env` (conservative | moderate | aggressive). These caps gate every new "
    "BUY the Portfolio Manager Agent considers — a trade that would breach the symbol/sector cap is sized down or "
    "skipped, and once the profit target or loss limit is hit, no new positions open for the rest of the session."
)

st.markdown('<hr class="ic-divider">', unsafe_allow_html=True)
st.subheader("Architecture Notes")
st.markdown(
    """
This build implements the full committee architecture (Investment Planner → 7 analyst agents → Debate Agent →
4-critic debate loop → trust-weighted directional consensus → portfolio decision → simulated execution → reporting)
with a **lean, zero-Docker stack** suited for a hackathon environment:
"""
)

rows = [
    ("Orchestration", "Custom async Python orchestrator (not LangGraph)"),
    ("Database", "SQLite (swap `DATABASE_URL` for Postgres later)"),
    ("Vector / memory store", "SQLite decision history (no PGVector dependency)"),
    ("Cache", "In-process (no Redis)"),
    ("Scheduling", "APScheduler in-process ticks (no Airflow/Kafka)"),
    ("Broker execution", "Simulated fills with a realistic Indian intraday cost model (no live broker)"),
    ("Monitoring", "Structured logs + DB audit log (no Prometheus/Grafana/LangSmith)"),
]
for label, note in rows:
    st.markdown(
        f"""
        <div class="ic-card" style="display:flex; padding:0.7rem 1.1rem;">
            <div style="width:200px; font-weight:700; color:#F1F5F9; flex-shrink:0;">{label}</div>
            <div style="color:#94A3B8;">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.caption("See the project README for the full diagram-to-implementation mapping.")
