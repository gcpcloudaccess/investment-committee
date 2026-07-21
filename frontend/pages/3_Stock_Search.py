import streamlit as st

from api_client import get, post
from theme import inject_base_css, metric_card, page_header, verdict_badge, verdict_icon

st.set_page_config(page_title="Stock Search", page_icon="🔍", layout="wide")
inject_base_css()
page_header("🔍", "Stock Search", "Run the full investment committee on any NSE symbol on demand — preview only, no trade is executed")

settings = get("/settings")
default_symbol = settings["watchlist"][0] if settings["watchlist"] else "NIFTYBEES.NS"

col1, col2 = st.columns([3, 1])
with col1:
    symbol = st.text_input("NSE symbol (e.g. NIFTYBEES.NS, GOLDBEES.NS, SILVERBEES.NS)", value=default_symbol)
with col2:
    st.write("")
    st.write("")
    run = st.button("Run Committee Analysis", type="primary", width="stretch")

if run and symbol:
    with st.spinner(f"Running the full committee (9 analysts + Debate Agent + 4 critics + trust-weighted consensus) on {symbol}..."):
        result = post(f"/analyze/{symbol.strip()}")

    st.markdown(
        f"""
        <div class="ic-card" style="display:flex; align-items:center; justify-content:space-between; margin-top:0.5rem;">
            <div>
                <span style="font-size:1.4rem; font-weight:700; color:#F1F5F9;">{result['symbol']}</span>
                <span style="margin-left:0.8rem;">{verdict_badge(result['verdict'])}</span>
            </div>
            <div style="font-family:'SF Mono','Roboto Mono',monospace; color:#94A3B8; font-size:0.95rem;">
                {result['directional_confidence']:.1f}% directional confidence
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(metric_card("Current Price", f"₹{result['price']:.2f}" if result["price"] else "—"), unsafe_allow_html=True)

    st.write("")
    st.subheader("Consensus Reasoning")
    st.markdown(f'<div class="ic-card">{result["consensus_reasoning"]}</div>', unsafe_allow_html=True)

    st.subheader("Agent-wise Recommendations")
    for v in result["agent_votes"]:
        with st.expander(f"{verdict_icon(v['action'])} {v['agent_name']} — {v['action']} ({v['confidence']:.2f} confidence)"):
            st.write(v["reasoning"])
            if v["evidence"]:
                st.markdown("**Evidence:**")
                for e in v["evidence"]:
                    st.markdown(f"- {e}")

    st.subheader("🗣️ Debate Agent")
    debate = result.get("debate")
    if debate:
        st.markdown(
            f"""
            <div class="ic-card">
                <div>{verdict_badge(debate['action'])} <span style="color:#94A3B8; font-size:0.85rem; margin-left:0.5rem;">synthesis confidence {debate['confidence']:.2f}</span></div>
                <div style="margin-top:0.6rem; color:#CBD5E1;">{debate['reasoning']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.subheader("Critic Feedback (Debate Loop)")
    for v in result["critic_feedback"]:
        with st.expander(f"{verdict_icon(v['action'])} {v['agent_name']} — {v['action']} ({v['confidence']:.2f} confidence)"):
            st.write(v["reasoning"])
            if v["evidence"]:
                for e in v["evidence"]:
                    st.markdown(f"- {e}")

    st.subheader("Alternative Stocks Considered")
    if result["alternatives"]:
        st.dataframe(result["alternatives"], width="stretch")
    else:
        st.info("No stronger risk-adjusted alternative was found in the watchlist this tick.")

    sizing = (result.get("execution") or {}).get("sizing") or {}
    if sizing.get("quantity"):
        st.subheader("Position Sizing & Leverage")
        s1, s2, s3, s4 = st.columns(4)
        s1.markdown(metric_card("Quantity", f"{sizing['quantity']:g} shares"), unsafe_allow_html=True)
        s2.markdown(metric_card("Notional", f"₹{sizing['notional']:,.2f}"), unsafe_allow_html=True)
        s3.markdown(
            metric_card("Leverage Used", f"{sizing['leverage_used']:.2f}×", tone="positive" if sizing["leverage_used"] > 1.0 else "neutral"),
            unsafe_allow_html=True,
        )
        s4.markdown(metric_card("Margin Used", f"₹{sizing['margin_used_inr']:,.2f}"), unsafe_allow_html=True)
        st.caption(
            f"Leverage scales with directional confidence and risk regime, capped at {sizing['max_leverage']:.0f}× "
            "(1:2) — a stronger, lower-risk recommendation can use more margin to buy more shares against the same capital."
        )

    st.subheader("Expected Risk & Return (Scenario Analysis)")
    err = result.get("expected_risk_return") or {}
    if err.get("scenarios"):
        rc1, rc2, rc3 = st.columns(3)
        rc1.markdown(metric_card("Expected Risk", f"₹{err['expected_risk_inr']:,.2f}", tone="negative"), unsafe_allow_html=True)
        rc2.markdown(metric_card("Expected Return", f"₹{err['expected_return_inr']:,.2f}", tone="positive"), unsafe_allow_html=True)
        rc3.markdown(metric_card("Risk/Reward Ratio", f"{err['risk_reward_ratio']}" if err["risk_reward_ratio"] else "—"), unsafe_allow_html=True)
        st.write("")
        st.dataframe(err["scenarios"], width="stretch")

    if result.get("alerts"):
        st.subheader("Alerts")
        icon_map = {"warning": "⚠️", "info": "ℹ️", "opportunity": "💡"}
        for a in result["alerts"]:
            st.markdown(f'<div class="ic-card">{icon_map.get(a["severity"], "•")} {a["message"]}</div>', unsafe_allow_html=True)
