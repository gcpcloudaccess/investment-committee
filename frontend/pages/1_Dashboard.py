from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from api_client import get, post
from theme import inject_base_css, metric_card, page_header, tone_for

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")
inject_base_css()
page_header("📊", "Dashboard", "Live portfolio state for the active paper-trading session")

col_a, col_b, col_c = st.columns([1, 1, 4])
with col_a:
    if st.button("Refresh", width="stretch"):
        st.rerun()
with col_b:
    if st.button("Run Tick Now", width="stretch"):
        with st.spinner("Running committee tick across the watchlist..."):
            post("/session/tick")
        st.success("Tick complete.")
        st.rerun()

portfolio = get("/portfolio")
overall = portfolio["overall"]
status_tone = "positive" if portfolio["status"] == "active" else "muted"

# ---------------------------------------------------------------- top KPI strip
k1, k2, k3, k4, k5 = st.columns(5)
k1.markdown(metric_card("Status", portfolio["status"].upper(), tone=status_tone), unsafe_allow_html=True)
k2.markdown(metric_card("Total Value", f"₹{portfolio['total_value']:,.2f}", tone=tone_for(portfolio["net_profit"])), unsafe_allow_html=True)
k3.markdown(
    metric_card("Today's Return", f"₹{portfolio['net_profit']:,.2f}", delta=f"{portfolio['total_return_pct']:+.2f}%", tone=tone_for(portfolio["net_profit"])),
    unsafe_allow_html=True,
)
k4.markdown(metric_card("Cash", f"₹{portfolio['cash']:,.2f}"), unsafe_allow_html=True)
k5.markdown(metric_card("Open Exposure", f"₹{portfolio['open_positions_value']:,.2f}"), unsafe_allow_html=True)

st.write("")
tab_overview, tab_positions, tab_planner, tab_reports = st.tabs(["Overview", "Positions & Trades", "Planner & Risk", "Reports"])

# ---------------------------------------------------------------- Overview
with tab_overview:
    is_closed = portfolio["status"] != "active"
    output_title = "FINAL SYSTEM OUTPUT — AT MARKET CLOSE" if is_closed else "LIVE SYSTEM OUTPUT — SESSION IN PROGRESS"
    st.markdown(
        f"""
        <div class="ic-card" style="background:linear-gradient(135deg,#131B2E 0%,#0F1729 100%); text-align:center;
             font-weight:700; color:#F1F5F9; letter-spacing:0.06em; padding:0.7rem; font-size:0.9rem;">
            {output_title}
        </div>
        """,
        unsafe_allow_html=True,
    )

    f1, f2, f3, f4 = st.columns(4)
    f1.markdown(metric_card("Final Portfolio Value", f"₹{portfolio['total_value']:,.2f}", tone=tone_for(portfolio["net_profit"])), unsafe_allow_html=True)
    f2.markdown(
        metric_card("Net Profit / Loss", f"₹{portfolio['net_profit']:,.2f}", delta="after brokerage, taxes & trading costs", tone=tone_for(portfolio["net_profit"])),
        unsafe_allow_html=True,
    )
    f3.markdown(metric_card("Total Return", f"{portfolio['total_return_pct']:+.1f}%", tone=tone_for(portfolio["total_return_pct"])), unsafe_allow_html=True)
    f4.markdown(
        metric_card("Win Rate", f"{portfolio['win_rate_pct']:.0f}%", delta=f"{portfolio['winning_trades_count']} of {portfolio['closed_trades_count']} trades" if portfolio["closed_trades_count"] else "no closed trades yet"),
        unsafe_allow_html=True,
    )

    st.write("")
    st.subheader("Portfolio Growth Curve")
    eq = get("/portfolio/equity-curve")
    if eq["figure"]["data"]:
        st.plotly_chart(go.Figure(eq["figure"]), width="stretch")
    else:
        st.info("No trades yet this session — equity curve will populate once the committee executes trades.")

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

# ---------------------------------------------------------------- Positions & Trades
with tab_positions:
    st.subheader("Open Positions")
    if portfolio["positions"]:
        for p in portfolio["positions"]:
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

    st.write("")
    trade_col, chart_col = st.columns([2, 3])
    with trade_col:
        st.subheader("Trade History")
        trades = get("/trades") or []
        recent_trades = list(reversed(trades))[-10:]  # chronological, most recent 10
        if recent_trades:
            rows_html = ""
            for t in recent_trades:
                action_color = "#4ADE80" if t["action"] == "BUY" else "#F87171"
                time_str = t["timestamp"][11:16] if t["timestamp"] else "--:--"
                rows_html += (
                    f'<div style="display:flex; justify-content:space-between; padding:0.3rem 0.2rem; '
                    f'border-bottom:1px solid #1E293B; font-family:\'SF Mono\',\'Roboto Mono\',monospace; font-size:0.85rem;">'
                    f'<span style="color:#64748B;">{time_str}</span>'
                    f'<span style="color:{action_color}; font-weight:700;">{t["action"]}</span>'
                    f'<span style="color:#F1F5F9;">{t["symbol"]}</span>'
                    f'<span style="color:#94A3B8;">₹{t["price"]:,.2f}</span>'
                    f"</div>"
                )
            st.markdown(f'<div class="ic-card" style="padding:0.7rem 1rem;">{rows_html}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="ic-card">No trades yet this session.</div>', unsafe_allow_html=True)

    with chart_col:
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

# ---------------------------------------------------------------- Planner & Risk
with tab_planner:
    plan = get("/planner/allocation-plan")

    st.subheader("Asset Allocation Caps")
    a1, a2, a3 = st.columns(3)
    a1.markdown(metric_card("Risk Tolerance", plan["risk_tolerance"].capitalize()), unsafe_allow_html=True)
    a2.markdown(metric_card("Per-Symbol Cap", f"₹{plan['symbol_cap_inr']:,.0f}"), unsafe_allow_html=True)
    a3.markdown(metric_card("Per-Sector Cap", f"₹{plan['sector_cap_inr']:,.0f}"), unsafe_allow_html=True)
    st.markdown(f'<div class="ic-card">{plan["reasoning"]}</div>', unsafe_allow_html=True)

    st.write("")
    st.subheader("Goal Progress")
    g1, g2, g3 = st.columns(3)
    g1.markdown(
        metric_card("Today's P&L (est.)", f"₹{plan['running_pnl_estimate']:,.2f}", tone=tone_for(plan["running_pnl_estimate"])),
        unsafe_allow_html=True,
    )
    g2.markdown(metric_card("Profit Target", f"+₹{plan['profit_target_inr']:,.0f}"), unsafe_allow_html=True)
    g3.markdown(metric_card("Loss Limit", f"₹{plan['loss_limit_inr']:,.0f}"), unsafe_allow_html=True)
    if plan["goal_hit"]:
        st.warning(f"Session goal reached ({plan['risk_tolerance']} profile) — the Portfolio Manager Agent will not open new positions for the rest of this session. Existing positions still monitored normally.")
    else:
        span = plan["profit_target_inr"] - plan["loss_limit_inr"]
        progress = (plan["running_pnl_estimate"] - plan["loss_limit_inr"]) / span if span else 0.5
        st.progress(min(max(progress, 0.0), 1.0))
    st.caption(
        f"Set via RISK_TOLERANCE in backend/.env. These caps gate every new BUY the Portfolio Manager Agent considers — "
        "a trade that would breach the symbol/sector cap is sized down or skipped, and once the profit target or loss "
        "limit is hit, no new positions open for the rest of the session."
    )

# ---------------------------------------------------------------- Reports
with tab_reports:
    st.subheader("Complete Explainable Trade Log")
    st.write("Full session summary, every trade, and the complete reasoning behind every decision.")
    pdf_c1, pdf_c2 = st.columns(2)
    with pdf_c1:
        if st.button("Generate PDF", width="stretch"):
            with st.spinner("Generating PDF..."):
                result = post("/reports/generate")
            st.session_state["dashboard_report_path"] = result["report_path"]
    with pdf_c2:
        last_path = st.session_state.get("dashboard_report_path")
        if last_path and Path(last_path).exists():
            with open(last_path, "rb") as f:
                st.download_button("Download PDF", f, file_name=Path(last_path).name, mime="application/pdf", width="stretch")

    st.markdown('<hr class="ic-divider">', unsafe_allow_html=True)
    st.subheader("Session Control")
    if st.button("Force Close Session Now (square off all positions + generate PDF)"):
        with st.spinner("Closing session..."):
            post("/session/close")
        st.success("Session closed. See the PDF above (or Reports & Logs) for the full trade log.")
        st.rerun()
