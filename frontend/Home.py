import streamlit as st

from api_client import get
from theme import inject_base_css, metric_card, page_header

st.set_page_config(page_title="Investment Committee", page_icon="📈", layout="wide")
inject_base_css()

page_header("📈", "Autonomous Multi-Agent Investment Committee", "Intraday NSE/BSE paper trading — explainable, trust-weighted multi-agent consensus")

settings = get("/settings")

col1, col2, col3, col4 = st.columns(4)
col1.markdown(metric_card("Starting Capital", f"₹{settings['starting_capital_inr']:,.0f}"), unsafe_allow_html=True)
col2.markdown(metric_card("Leverage", f"1:{int(settings['leverage'])}"), unsafe_allow_html=True)
col3.markdown(metric_card("Tick Interval", f"{settings['tick_minutes']} min"), unsafe_allow_html=True)
col4.markdown(metric_card("Data Mode", settings["data_mode"].upper(), tone="positive" if settings["data_mode"] == "live" else "neutral"), unsafe_allow_html=True)

st.write("")

if not settings["llm_key_configured"]:
    st.warning(
        f"No LLM API key configured for provider `{settings['llm_provider']}`. The committee still runs "
        "(all indicator/consensus math is independent of the LLM), but agent reasoning text will fall back "
        "to templated summaries instead of LLM-generated narratives. Add a key to `backend/.env` and restart "
        "the backend for full explanations."
    )

nav_items = [
    ("📊", "Dashboard", "Live portfolio value, P&L, open positions, equity curve"),
    ("👀", "Watchlist", "Candidate stocks and their latest committee signal"),
    ("🔍", "Stock Search", "Run the full committee on any NSE symbol on demand"),
    ("🏛️", "Committee Meetings", "The full debate transcript behind any decision"),
    ("🧾", "Reports & Logs", "Trade history, audit log, downloadable PDF trade log"),
    ("⚙️", "Settings", "Current session configuration"),
]
cols = st.columns(3)
for i, (icon, title, desc) in enumerate(nav_items):
    with cols[i % 3]:
        st.markdown(
            f"""
            <div class="ic-card" style="min-height:118px">
                <div style="font-size:1.6rem">{icon}</div>
                <div style="font-weight:700; color:#F1F5F9; margin-top:0.3rem;">{title}</div>
                <div style="font-size:0.85rem; color:#94A3B8; margin-top:0.2rem;">{desc}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.markdown('<hr class="ic-divider">', unsafe_allow_html=True)
st.markdown(
    "**Watchlist:** " + " ".join(f'<span class="ic-badge" style="background:#131B2E;color:#93C5FD;border:1px solid #1E293B">{s}</span>' for s in settings["watchlist"]),
    unsafe_allow_html=True,
)
