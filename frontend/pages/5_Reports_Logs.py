from pathlib import Path

import streamlit as st

from api_client import get, post
from theme import inject_base_css, page_header, verdict_badge

st.set_page_config(page_title="Reports & Logs", page_icon="🧾", layout="wide")
inject_base_css()
page_header("🧾", "Reports & Logs", "Trade history, decision log, audit trail, and the explainable PDF trade log")

if st.button("🔄 Refresh"):
    st.rerun()

tab_trades, tab_decisions, tab_audit, tab_pdf = st.tabs(["Trade History", "Decision Log", "Audit Log", "PDF Trade Log"])

with tab_trades:
    st.caption("Retained and appended across every session/exchange rollover — not reset when the active session switches markets.")
    trades = get("/trades")
    if trades:
        st.dataframe(trades, width="stretch")
    else:
        st.info("No trades executed yet.")

with tab_decisions:
    decisions = get("/decisions", limit=200)
    if decisions:
        for d in decisions:
            st.markdown(
                f"""
                <div class="ic-card" style="display:flex; align-items:center; justify-content:space-between;">
                    <div>
                        <span style="color:#64748B; font-size:0.82rem; font-family:'SF Mono','Roboto Mono',monospace;">{d['timestamp']}</span>
                        <span style="font-weight:700; color:#F1F5F9; margin-left:0.7rem;">{d['symbol']}</span>
                        <span style="margin-left:0.6rem;">{verdict_badge(d['verdict'])}</span>
                    </div>
                    <div style="font-family:'SF Mono','Roboto Mono',monospace; color:#94A3B8; font-size:0.88rem;">
                        {d['directional_confidence']:.1f}% {"· executed" if d["executed"] else "· no trade"}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.info("No decisions recorded yet.")

with tab_audit:
    audit = get("/audit-log", limit=200)
    if audit:
        st.dataframe(
            [{"Time": a["timestamp"], "Event": a["event_type"], "Payload": a["payload"]} for a in audit],
            width="stretch",
        )
    else:
        st.info("No audit events yet.")

with tab_pdf:
    st.write("Generate the complete explainable trade log PDF (session summary + every trade + full reasoning for every trade and no-trade decision).")
    if st.button("📄 Generate PDF Report", type="primary"):
        with st.spinner("Generating PDF..."):
            result = post("/reports/generate")
        report_path = Path(result["report_path"])
        st.session_state["last_report_path"] = str(report_path)
        st.success(f"Report generated: {report_path.name}")

    last_path = st.session_state.get("last_report_path")
    if last_path and Path(last_path).exists():
        with open(last_path, "rb") as f:
            st.download_button("⬇️ Download PDF", f, file_name=Path(last_path).name, mime="application/pdf")
