import plotly.graph_objects as go
import streamlit as st

from api_client import get, post
from theme import inject_base_css, metric_card, page_header, tone_for

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")
inject_base_css()
page_header("📊", "Dashboard", "Live portfolio state for the active paper-trading session")

col_a, col_b, col_c = st.columns([1, 1, 4])
with col_a:
    if st.button("🔄 Refresh", width="stretch"):
        st.rerun()
with col_b:
    if st.button("⏱️ Run Tick Now", width="stretch"):
        with st.spinner("Running committee tick across the watchlist..."):
            post("/session/tick")
        st.success("Tick complete.")
        st.rerun()

portfolio = get("/portfolio")
status_tone = "positive" if portfolio["status"] == "active" else "muted"
overall = portfolio["overall"]

c1, c2, c3, c4, c5 = st.columns(5)
c1.markdown(metric_card("Status", portfolio["status"].upper(), tone=status_tone), unsafe_allow_html=True)
c2.markdown(metric_card("Total Value", f"₹{portfolio['total_value']:,.2f}", tone=tone_for(portfolio["net_profit"])), unsafe_allow_html=True)
c3.markdown(
    metric_card("Intraday Return", f"₹{portfolio['net_profit']:,.2f}", delta=f"{portfolio['total_return_pct']:+.2f}%", tone=tone_for(portfolio["net_profit"])),
    unsafe_allow_html=True,
)
c4.markdown(metric_card("Cash", f"₹{portfolio['cash']:,.2f}"), unsafe_allow_html=True)
c5.markdown(metric_card("Open Positions Value", f"₹{portfolio['open_positions_value']:,.2f}"), unsafe_allow_html=True)

st.write("")
st.subheader("Overall Return (across all sessions)")
o1, o2, o3, o4 = st.columns(4)
o1.markdown(
    metric_card("Overall Net Profit", f"₹{overall['net_profit']:,.2f}", delta=f"{overall['return_pct']:+.2f}%", tone=tone_for(overall["net_profit"])),
    unsafe_allow_html=True,
)
o2.markdown(
    metric_card("Cumulative Capital Deployed", f"₹{overall['starting_capital']:,.2f}", delta=f"{overall['total_sessions']} × ₹{portfolio['starting_capital']:,.0f} sessions"),
    unsafe_allow_html=True,
)
o3.markdown(metric_card("Cumulative Ending Value", f"₹{overall['ending_value']:,.2f}"), unsafe_allow_html=True)
o4.markdown(metric_card("Sessions Run", f"{overall['total_sessions']}", delta=f"{overall['closed_sessions']} closed"), unsafe_allow_html=True)
st.caption(
    f"Not a leverage figure. Each of the {overall['total_sessions']} sessions independently starts fresh at "
    f"₹{portfolio['starting_capital']:,.0f} (non-compounding) — this row just adds them up for a historical total. "
    f"Your current session's leverage cap is separate: cash (₹{portfolio['cash']:,.0f}) × {portfolio['leverage']:.0f}× leverage "
    f"= up to ₹{portfolio['starting_capital'] * portfolio['leverage']:,.0f} exposure, shown per-trade under Position Sizing & Leverage on Stock Search."
)

st.write("")
chart_col, price_col = st.columns([3, 2])
with chart_col:
    st.subheader("Portfolio Growth Curve")
    eq = get("/portfolio/equity-curve")
    if eq["figure"]["data"]:
        fig = go.Figure(eq["figure"])
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("No trades yet this session — equity curve will populate once the committee executes trades.")

with price_col:
    st.subheader("Stock Chart")
    watchlist = get("/settings")["watchlist"]
    held_symbols = [p["symbol"] for p in portfolio["positions"]]
    default_symbol = held_symbols[0] if held_symbols else (watchlist[0] if watchlist else "RELIANCE.NS")
    chart_options = list(dict.fromkeys([*held_symbols, *watchlist]))
    chart_symbol = st.selectbox("Symbol", chart_options or [default_symbol], index=0)
    chart_data = get(f"/market/chart/{chart_symbol}", silent=True)
    if chart_data:
        st.plotly_chart(go.Figure(chart_data["figure"]), width="stretch")
    else:
        st.info(f"No chart data available for {chart_symbol} right now.")

st.subheader("Open Positions")
if portfolio["positions"]:
    for p in portfolio["positions"]:
        pnl_tone = tone_for(p.get("realized_pnl") or 0)
        st.markdown(
            f"""
            <div class="ic-card" style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <span style="font-weight:700; color:#F1F5F9; font-size:1.05rem;">{p['symbol']}</span>
                    <span class="ic-badge" style="margin-left:0.6rem; background:#0F2A1C;color:#4ADE80;border:1px solid #22C55E;">{p['side']}</span>
                </div>
                <div style="font-family:'SF Mono','Roboto Mono',monospace; color:#94A3B8;">
                    Qty {p['quantity']:g} @ ₹{p['avg_price']:,.2f}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
else:
    st.info("No open positions.")

st.markdown('<hr class="ic-divider">', unsafe_allow_html=True)
if st.button("🛑 Force Close Session Now (square off all positions + generate PDF)"):
    with st.spinner("Closing session..."):
        post("/session/close")
    st.success("Session closed. See Reports & Logs for the PDF trade log.")
    st.rerun()
