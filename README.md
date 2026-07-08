# Autonomous Multi-Agent Investment Committee

Autonomous multi-agent committee that paper-trades NSE/BSE intraday: starts with ₹10,000 virtual capital at 1:2 leverage, runs a 4–6 hour session, and autonomously decides BUY / SELL / HOLD / WAIT / SWITCH per symbol using a **trust-weighted, directional-confidence-aware consensus** across 7 analyst agents and a 4-critic debate loop — never simple majority voting or plain confidence averaging.

This build targets a **hackathon-friendly, zero-Docker setup**: everything runs with just a Python virtualenv (Python 3.14 verified) and two local processes (FastAPI backend + Streamlit frontend). See [Architecture mapping](#architecture-mapping-diagram--this-build) for how each diagrammed component was implemented.

## Quick start

```bash
# 1. Create venv & install deps (from the investment-committee/ root)
python -m venv .venv
./.venv/Scripts/pip install -r backend/requirements.txt -r frontend/requirements.txt

# 2. Configure secrets
cp backend/.env.example backend/.env
# edit backend/.env: set ANTHROPIC_API_KEY (or OPENAI_API_KEY + LLM_PROVIDER=openai)

# 3. Run the backend (from investment-committee/ root — this chdir's into backend/ itself)
./.venv/Scripts/python run_backend.py
# -> http://127.0.0.1:8000  (docs at /docs)

# 4. In a second terminal, run the frontend
./.venv/Scripts/python -m streamlit run frontend/Home.py
# -> http://localhost:8501
```

**Without an LLM key**, the app still runs fully — all indicator math, the consensus algorithm, position sizing, execution, and costs are pure Python and key-independent. Only the natural-language reasoning text degrades to a deterministic templated summary instead of an LLM-generated narrative. The Settings page and Dashboard both surface a warning if no key is configured.

### Data mode

- `DATA_MODE=replay` (default): downloads a window of recent historical intraday bars per symbol once (cached under `data_cache/`) and replays them tick-by-tick. Works at any time of day — good for demos.
- `DATA_MODE=live`: pulls live/delayed quotes from yfinance. Only meaningful during NSE hours (09:15–15:30 IST, Mon–Fri).

### Running a session

- The backend auto-ticks every `TICK_MINUTES` (default 10) via APScheduler once started.
- For a live demo, use the Dashboard's **"Run Tick Now"** button to trigger a tick on demand instead of waiting.
- **Stock Search** runs the full committee for any symbol as a preview (no trade executed).
- The session auto-closes (force-closing all positions + generating the PDF trade log) when replay data is exhausted, or near NSE close in live mode. You can also force it early from the Dashboard ("Force Close Session Now") or `POST /session/close`.

### Tests

```bash
cd backend && ../.venv/Scripts/python -m pytest tests/ -v
```

Covers the mandatory consensus algorithm (proves it is *not* majority voting / plain averaging) and the trading/cost engine, independent of any LLM or live network call.

## Architecture mapping (diagram → this build)

| Diagram layer | This build |
|---|---|
| Data Sources | `app/data/market_data.py` (yfinance, NSE `.NS` symbols), `app/data/news_data.py` (free RSS: Google News, Moneycontrol, Economic Times; NewsAPI optional), `app/data/fundamentals.py` (yfinance fundamentals) |
| Data Ingestion (Airflow/Kafka) | In-process APScheduler tick loop (`app/orchestration/session_runner.py`) — no external ingestion infra needed for a single-process hackathon deployment |
| Multi-Agent Orchestration (LangGraph) | Custom Python orchestrator (`app/orchestration/supervisor.py`, `app/agents/`) — avoided both LangGraph and CrewAI: these agents are deterministic Python/ML with a thin LLM narration call, not LLM-driven tool-use loops, so a framework built around agentic reasoning chains wouldn't fit. `app/agents/debate_loop.py` runs all analysts (then all critics) concurrently via a bounded `ThreadPoolExecutor` (`settings.max_parallel_agents`, default 4) instead of sequentially — full unbounded parallelism was tried first and tripped Anthropic rate limits, so concurrency is capped rather than open-ended |
| Specialized Analyst Agents | 8 agents in `app/agents/analysts/`: Fundamental, Technical, Macroeconomic, Sentiment, Geopolitical, Government Policy, Risk Assessment, Algo Signal — each wraps a custom-built tool in `app/tools/`. Several are blended with teammate-contributed engines (vendored unmodified under `backend/`): Risk Assessment blends our per-bar volatility read with `risk_agent/` (beta, Sharpe/Sortino, VaR/CVaR, liquidity/concentration/sector-exposure risk, on daily bars); Technical blends our intraday RSI/MACD with `technical_analyst_agent/` (daily-chart trend overlay); Sentiment fully replaces our lexicon with `sentiment_analyst.py` (emotion/credibility/risk-scored polarity); Algo Signal is new capability wrapping `algo_agent/` (a freshly-trained logistic regression model per tick, validated out-of-sample) reviewed by `critic_agent/` (a dedicated schema/consistency critic for that model's output) |
| Debate & Consensus Layer | `app/agents/debate_agent.py` (Debate Agent — surfaces the strongest contradicting analyst views before critique) → 4 critics in `app/agents/critics.py` (Risk, Profit, Macro, Opportunity) → `app/consensus/trust_weighted_consensus.py` (the mandatory directional confidence-aware algorithm, combining Confidence Scoring + Directional Consensus into one weighted engine) + `app/consensus/reliability_tracker.py` (persisted Beta-updated historical reliability). Evidence Fusion is implicit in how consensus aggregates each agent's evidence list, rather than a separate agent. |
| Portfolio Decision Layer | `app/portfolio/` — portfolio_manager, position_sizing (respects ₹10,000/1:2 leverage cap), scenario_analysis, execution_advisor |
| Reporting & Output | `app/reporting/` — report_agent (LLM "why" narrative), visualization (Plotly equity curve), alert_agent, audit_log, pdf_export (end-of-session explainable trade log PDF) |
| Memory & Knowledge (PostgreSQL/PGVector/Redis) | SQLite via SQLAlchemy (`DATABASE_URL` swappable for Postgres later); decision/vote history queried directly (no vector store dependency); no separate cache layer (single process) |
| Monitoring & Governance (Prometheus/Grafana/LangSmith/Auth0) | Structured logging + `AuditLog` DB table only — not built; noted here as the production upgrade path |
| External Integrations (Broker APIs) | Simulated execution engine (`app/trading/execution_engine.py`) with a realistic Indian intraday cost model (`app/trading/costs.py`: brokerage, STT, exchange charges, SEBI charges, stamp duty, GST) — no live broker, this is paper trading |
| User Interface | Streamlit, 6 pages under `frontend/pages/`: Dashboard, Watchlist, Stock Search, Committee Meetings, Reports & Logs, Settings |

### The mandatory consensus algorithm

`app/consensus/trust_weighted_consensus.py` computes, per agent, per tick:

```
weight = confidence × expertise_relevance(context) × trust_score(persisted history) × agreement_adjustment(this tick)
```

`agreement_adjustment` discounts agents that just agree with the room (redundant signal) and amplifies agents that disagree with the room *and* have a strong track record (the "reliable contrarian" case from the spec). The final `directional_confidence` blends the winning action's *dominance* (share of trust-weighted influence) with the *conviction* of the agents backing it (their own confidence × trust) — see `backend/tests/test_consensus.py` for the proofs that this diverges from both majority voting and plain confidence averaging.

## What's not built (explicitly out of scope for this hackathon build)

Airflow, Kafka, Kubernetes/Terraform, PGVector, Redis, Prometheus/Grafana, LangSmith/OpenTelemetry, WhyLabs/Arize, Auth0/Keycloak, live broker execution (Zerodha/Alpaca/IB). The architecture's *responsibilities* for each are preserved (see mapping table above) so swapping in the real infra later is additive, not a rewrite.
