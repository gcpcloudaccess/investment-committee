"""Critic agents for the debate loop. Each critic reviews the analyst votes
already cast for this tick and casts its own vote — critics are full
participants in the trust-weighted consensus, not just commentary.

Each critic is a thin adapter over a vendored, unmodified teammate package
(same pattern as every other agent in this project): translate our
AnalysisContext + prior votes into that package's own input schema, call its
real deterministic (and, for Risk Critic, LLM-backed) critique logic, then map
its structured result back into an AgentVote."""

from __future__ import annotations

from app.agents.base import AgentVote, AnalysisContext, BaseAgent
from app.config import get_settings
from app.llm.client import get_llm_client
from app.tools import opportunity_discovery, risk_model

from macro_critic.agent import MacroCriticAgent
from macro_critic.models import MacroSnapshot, MarketSnapshot
from macro_critic.models import TradeProposal as MacroTradeProposal
from opportunity_critic_agent import (
    CurrentProposal,
    Evidence as OppEvidence,
    InvestmentCandidate,
    OpportunityCriticAgent,
)
from profit_critic_agent import MarketContext as ProfitMarketContext
from profit_critic_agent import ProfitCriticAgent
from profit_critic_agent import TradeProposal as ProfitTradeProposal
from profit_critic_agent import Verdict as ProfitVerdict
from risk_critic_agent.risk_critic_agent import RiskCriticAgent, aggregate_committee_payload


def _action_confidences(votes: list[AgentVote], action: str) -> list[float]:
    return [v.confidence for v in votes if v.action == action]


def _dominant_action(votes: list[AgentVote]) -> str:
    if not votes:
        return "HOLD"
    return max({v.action for v in votes}, key=lambda a: sum(_action_confidences(votes, a)))


def _latest_close(ctx: AnalysisContext) -> float | None:
    if ctx.bars is None or ctx.bars.empty:
        return None
    return float(ctx.bars["Close"].iloc[-1])


def _series_trend_pct(bars, lookback: int = 30) -> float | None:
    if bars is None or bars.empty or len(bars) < 2:
        return None
    window = bars["Close"].tail(lookback)
    first, last = float(window.iloc[0]), float(window.iloc[-1])
    return None if first == 0 else round((last - first) / first * 100, 3)


class RiskCritic(BaseAgent):
    name = "Risk Critic"
    agent_type = "critic"
    expertise = "risk"

    _DECISION_MAP = {
        # (action, confidence_scale) - action falls back to the committee's current lean
        # for decisions that endorse the trade in some form, HOLD/WAIT for ones that don't.
        "approve_with_controls": (None, 0.8),
        "reduce_size": (None, 0.5),
        "hedge_required": ("HOLD", 0.6),
        "reject": ("HOLD", 0.6),
        "delay_for_confirmation": ("WAIT", 0.4),
        "insufficient_data": ("WAIT", 0.25),
    }

    def vote(self, ctx: AnalysisContext, analyst_votes: list[AgentVote]) -> AgentVote:
        settings = get_settings()
        proposed_action = _dominant_action(analyst_votes)
        risk_signal = risk_model.analyze(ctx.bars)
        price = _latest_close(ctx)

        payload = aggregate_committee_payload(
            proposal={
                "action": proposed_action.lower(),
                "instrument": ctx.symbol,
                "time_horizon": "intraday (same session)",
                "entry": price,
                "target": None,
                "stop_loss": None,
                "expected_return": None,
                "expected_drawdown": risk_signal["metrics"].get("max_drawdown_pct"),
                "position_size": None,
            },
            market_data={
                "volatility": risk_signal["metrics"].get("volatility"),
                "risk_level": risk_signal["metrics"].get("risk_level"),
                "var_95_pct": risk_signal["metrics"].get("var_95_pct"),
            },
            portfolio_context={
                "open_positions": [p.get("symbol") for p in (ctx.open_positions or [])],
                "starting_capital_inr": settings.starting_capital_inr,
                "leverage": settings.leverage,
            },
            agent_recommendations=[{"agent": v.agent_name, "action": v.action, "confidence": v.confidence} for v in analyst_votes],
            supporting_evidence=[{"agent": v.agent_name, "evidence": e} for v in analyst_votes for e in v.evidence[:1]],
        )

        llm = get_llm_client()
        agent = RiskCriticAgent(model_caller=self._model_caller(llm) if llm.available else None)
        try:
            result = agent.run(payload)
        except Exception:
            result = agent.insufficient_data_response(payload)

        decision = result.get("decision", "insufficient_data")
        mapped_action, scale = self._DECISION_MAP.get(decision, ("HOLD", 0.4))
        action = mapped_action or proposed_action
        confidence = round(min(0.95, max(0.1, result.get("risk_confidence_score", 50) / 100 * scale)), 3)

        top_risks = result.get("top_risks", [])[:3]
        evidence = [f"{r.get('risk', 'risk')}: {r.get('mitigation', '')}" for r in top_risks] or [result.get("summary", "")]
        reasoning = " ".join(filter(None, [result.get("summary", ""), result.get("final_risk_note", "")])) or "Risk Critic could not form a critique from the available data."

        return AgentVote(
            agent_name=self.name, agent_type=self.agent_type, action=action, confidence=confidence,
            reasoning=reasoning, evidence=evidence,
            metrics={"decision": decision, "overall_risk_rating": result.get("overall_risk_rating")},
        )

    @staticmethod
    def _model_caller(llm):
        def _call(messages: list[dict], _options: dict) -> str:
            system = next((m["content"] for m in messages if m["role"] == "system"), "")
            user = next((m["content"] for m in messages if m["role"] == "user"), "")
            # The Risk Critic's schema requires a large structured JSON response
            # (top_risks, 3+ scenario_analysis entries, portfolio/consensus impact,
            # required_controls, ...) and this model reliably spends 2000+ tokens on
            # extended thinking for this prompt before any text - measured empirically
            # (2064 thinking tokens observed at max_tokens=4000). A smaller budget lets
            # thinking consume the whole response, which chat() then treats as a failed
            # call and falls back (see llm/client.py).
            return llm.chat(system=system, user=user, max_tokens=4000, fallback="")
        return _call


class ProfitCritic(BaseAgent):
    name = "Profit Critic"
    agent_type = "critic"
    expertise = "technical"

    def vote(self, ctx: AnalysisContext, analyst_votes: list[AgentVote]) -> AgentVote:
        proposed_action = _dominant_action(analyst_votes)
        price = _latest_close(ctx)
        risk_signal = risk_model.analyze(ctx.bars)
        vol = risk_signal["metrics"].get("volatility") or 0.01

        if price is None or proposed_action not in ("BUY", "SELL"):
            challenge = "No priceable directional proposal to critique this tick."
            return AgentVote(agent_name=self.name, agent_type=self.agent_type, action="WAIT", confidence=0.3, reasoning=challenge, evidence=[challenge], metrics={})

        direction = 1 if proposed_action == "BUY" else -1
        target_price = price * (1 + direction * 2 * vol)
        stop_loss = price * (1 - direction * vol)

        bullish_conf = sum(_action_confidences(analyst_votes, "BUY"))
        bearish_conf = sum(_action_confidences(analyst_votes, "SELL"))
        alt_result = opportunity_discovery.find_alternatives(ctx.symbol, proposed_action, ctx.peer_bars or {ctx.symbol: ctx.bars})

        proposal = ProfitTradeProposal(
            symbol=ctx.symbol, action=proposed_action, entry_price=price, target_price=target_price,
            stop_loss=stop_loss, holding_days=0, position_size_pct=10.0,
            thesis="; ".join(v.reasoning[:120] for v in analyst_votes[:2]),
            fees_bps=15.0, slippage_bps=15.0,
            alternative_symbols=[a["symbol"] for a in alt_result.get("alternatives", [])],
        )
        context = ProfitMarketContext(
            sector_trend_score=50.0,
            technical_score=round(bullish_conf * 100, 1),
            fundamental_score=round(sum(_action_confidences(analyst_votes, proposed_action)) * 100, 1),
            sentiment_score=round(max(bullish_conf, bearish_conf) * 100, 1),
            liquidity_score=70.0,
            macro_risk_score=round((risk_signal["metrics"].get("volatility") or 0.0) * 2000, 1),
            evidence=[e for v in analyst_votes for e in v.evidence[:1]],
        )

        critique = ProfitCriticAgent().critique(proposal, context)

        verdict_map = {
            ProfitVerdict.SUPPORT: (proposed_action, 0.85),
            ProfitVerdict.CHALLENGE: ("HOLD", 0.5),
            ProfitVerdict.ESCALATE: ("HOLD", 0.55),
            ProfitVerdict.REJECT: ("HOLD", 0.6),
        }
        action, scale = verdict_map.get(critique.verdict, ("HOLD", 0.4))
        confidence = round(min(0.9, max(0.1, critique.confidence * scale)), 3)

        reasoning = critique.recommendation or f"Profit Critic {critique.verdict.value}s {proposed_action} {ctx.symbol}."
        evidence = critique.objections[:2] or [reasoning]

        return AgentVote(
            agent_name=self.name, agent_type=self.agent_type, action=action, confidence=confidence,
            reasoning=reasoning, evidence=evidence,
            metrics={"verdict": critique.verdict.value, "expected_return_pct": round(critique.expected_return_pct, 2), "reward_to_risk": critique.reward_to_risk},
        )


class MacroCritic(BaseAgent):
    name = "Macro Critic"
    agent_type = "critic"
    expertise = "macro"

    def vote(self, ctx: AnalysisContext, analyst_votes: list[AgentVote]) -> AgentVote:
        settings = get_settings()
        proposed_action = _dominant_action(analyst_votes)
        risk_signal = risk_model.analyze(ctx.bars)

        proposal = MacroTradeProposal(
            action=proposed_action if proposed_action in ("BUY", "SELL", "HOLD") else "HOLD",
            symbol=ctx.symbol, asset_class="equity",
            sector=(ctx.fundamentals or {}).get("sector", "unknown"), country="IN", horizon_days=1,
        )
        macro = MacroSnapshot(
            inflation_yoy=settings.macro_inflation_pct, gdp_growth_yoy=settings.macro_gdp_growth_pct,
            policy_rate=settings.macro_policy_rate_pct,
        )
        market = MarketSnapshot(
            index_trend_30d_pct=_series_trend_pct(ctx.benchmark_bars),
            sector_trend_30d_pct=_series_trend_pct(ctx.bars),
            volatility_percentile=min(100.0, (risk_signal["metrics"].get("volatility") or 0.0) * 4000),
        )

        result = MacroCriticAgent().critique(proposal, macro, market)

        stance_map = {"support": (proposed_action, 1.0), "caution": ("HOLD", 0.7), "oppose": ("HOLD", 0.85)}
        action, scale = stance_map.get(result.stance, ("HOLD", 0.5))
        confidence = round(min(0.9, max(0.1, result.directional_confidence / 100 * scale)), 3)

        reasoning = " ".join(filter(None, [result.summary, *result.critic_comments[:1]]))
        evidence = result.critic_comments or [e.explanation for e in result.evidence[:2]]

        return AgentVote(
            agent_name=self.name, agent_type=self.agent_type, action=action, confidence=confidence,
            reasoning=reasoning, evidence=evidence, metrics={"stance": result.stance},
        )


class OpportunityCritic(BaseAgent):
    name = "Opportunity Critic"
    agent_type = "critic"
    expertise = "opportunity"

    def vote(self, ctx: AnalysisContext, analyst_votes: list[AgentVote]) -> AgentVote:
        current_lean = _dominant_action(analyst_votes)
        alt_result = opportunity_discovery.find_alternatives(ctx.symbol, current_lean, ctx.peer_bars or {ctx.symbol: ctx.bars})
        risk_signal = risk_model.analyze(ctx.bars)
        vol = risk_signal["metrics"].get("volatility") or 0.01

        proposal_action = current_lean.lower() if current_lean in ("BUY", "SELL", "HOLD") else "hold"
        current_candidate = InvestmentCandidate(
            ticker=ctx.symbol, name=ctx.symbol,
            expected_return=sum(_action_confidences(analyst_votes, current_lean)) or 0.1,
            downside_risk=min(1.0, vol * 40), conviction=sum(v.confidence for v in analyst_votes) / max(len(analyst_votes), 1),
            liquidity_score=0.7, catalyst_score=0.5, valuation_score=0.5,
        )
        alternatives = []
        for alt in alt_result.get("alternatives", []):
            alt_bars = (ctx.peer_bars or {}).get(alt["symbol"])
            alt_vol = risk_model.analyze(alt_bars)["metrics"].get("volatility") if alt_bars is not None else None
            alternatives.append(InvestmentCandidate(
                ticker=alt["symbol"], name=alt["symbol"],
                expected_return=max(0.0, alt["score"]), downside_risk=min(1.0, (alt_vol or vol) * 40),
                conviction=min(1.0, max(0.0, alt["score"])), liquidity_score=0.7, catalyst_score=0.5, valuation_score=0.5,
                evidence=(OppEvidence(source="opportunity_discovery", claim=f"risk-adjusted score {alt['score']:+.2f}", rating="mixed"),),
            ))

        critique = OpportunityCriticAgent().critique(
            CurrentProposal(action=proposal_action, candidate=current_candidate, thesis="; ".join(v.reasoning[:100] for v in analyst_votes[:1])),
            alternatives,
        )

        # support_current means "no objection to the room's current lean" - so it should
        # echo current_lean (whatever action that is), not be hardcoded to HOLD.
        verdict_map = {"support_current": (current_lean, 0.3), "challenge_current": ("SWITCH", 0.55), "escalate_to_debate": ("SWITCH", 0.7)}
        action, confidence = verdict_map.get(critique.verdict.value, (current_lean, 0.3))

        return AgentVote(
            agent_name=self.name, agent_type=self.agent_type, action=action, confidence=confidence,
            reasoning=critique.committee_message, evidence=list(critique.questions_for_debate[:2]) or [critique.committee_message],
            metrics={"alternatives": alt_result.get("alternatives", [])},
        )


ALL_CRITICS = [RiskCritic, ProfitCritic, MacroCritic, OpportunityCritic]
