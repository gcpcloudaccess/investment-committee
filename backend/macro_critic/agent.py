from __future__ import annotations

from .models import CritiqueResult, EvidenceItem, MacroSnapshot, MarketSnapshot, TradeProposal


class MacroCriticAgent:
    """Challenges trade proposals using macro regime evidence."""

    name = "macro_critic"

    def critique(
        self,
        proposal: TradeProposal,
        macro: MacroSnapshot,
        market: MarketSnapshot,
    ) -> CritiqueResult:
        raw_evidence = self._collect_evidence(proposal, macro, market)
        directional_score = self._directional_score(proposal.action, raw_evidence)
        stance = self._stance(directional_score)
        critic_comments = self._comments(proposal, raw_evidence, stance)
        stress_scenarios = self._stress_scenarios(macro, market)

        summary = (
            f"Macro Critic {stance}s {proposal.action} {proposal.symbol}: "
            f"directional confidence {directional_score}/100; "
            f"{self._dominant_signal(raw_evidence, stance)}."
        )

        return CritiqueResult(
            agent_name=self.name,
            stance=stance,
            directional_confidence=directional_score,
            summary=summary,
            evidence=raw_evidence,
            critic_comments=critic_comments,
            stress_scenarios=stress_scenarios,
            consensus_payload={
                "agent": self.name,
                "target_symbol": proposal.symbol,
                "recommended_direction": self._recommended_direction(proposal.action, stance),
                "confidence": directional_score,
                "stance": stance,
                "top_evidence": [item.label for item in sorted(raw_evidence, key=lambda item: abs(item.score), reverse=True)[:3]],
            },
        )

    def _collect_evidence(
        self,
        proposal: TradeProposal,
        macro: MacroSnapshot,
        market: MarketSnapshot,
    ) -> list[EvidenceItem]:
        evidence: list[EvidenceItem] = []

        if macro.inflation_yoy is not None:
            if macro.inflation_yoy >= 6:
                evidence.append(EvidenceItem("inflation_pressure", "negative", -16, "Inflation is elevated and can pressure margins, multiples, and policy easing expectations."))
            elif macro.inflation_yoy <= 3:
                evidence.append(EvidenceItem("inflation_benign", "positive", 10, "Inflation is contained, improving the probability of stable or easier financial conditions."))
            else:
                evidence.append(EvidenceItem("inflation_moderate", "neutral", 0, "Inflation is not extreme enough to dominate the macro view."))

        if macro.policy_bias in {"hawkish", "tightening", "restrictive"}:
            evidence.append(EvidenceItem("policy_restriction", "negative", -18, "Central-bank stance is restrictive, reducing support for risk assets."))
        elif macro.policy_bias in {"dovish", "easing", "accommodative"}:
            evidence.append(EvidenceItem("policy_support", "positive", 16, "Policy stance is supportive for valuation and liquidity-sensitive assets."))

        if macro.gdp_growth_yoy is not None:
            if macro.gdp_growth_yoy >= 6:
                evidence.append(EvidenceItem("growth_strength", "positive", 14, "Growth is strong enough to support earnings expectations."))
            elif macro.gdp_growth_yoy < 3:
                evidence.append(EvidenceItem("growth_risk", "negative", -14, "Growth is weak and raises demand-side risk."))

        if macro.pmi is not None:
            if macro.pmi >= 55:
                evidence.append(EvidenceItem("pmi_expansion", "positive", 10, "PMI indicates broad economic expansion."))
            elif macro.pmi < 50:
                evidence.append(EvidenceItem("pmi_contraction", "negative", -12, "PMI is in contraction territory."))

        if macro.currency_change_30d_pct is not None:
            if macro.currency_change_30d_pct <= -2:
                evidence.append(EvidenceItem("currency_stress", "negative", -10, "Recent currency weakness can import inflation and deter foreign flows."))
            elif macro.currency_change_30d_pct >= 2:
                evidence.append(EvidenceItem("currency_tailwind", "positive", 8, "Currency strength is supportive for external confidence and inflation control."))

        if macro.liquidity_condition in {"tight", "tightening", "scarce"}:
            evidence.append(EvidenceItem("liquidity_tightening", "negative", -14, "Liquidity is tightening, which can lower risk appetite and amplify drawdowns."))
        elif macro.liquidity_condition in {"loose", "easing", "ample"}:
            evidence.append(EvidenceItem("liquidity_support", "positive", 14, "Ample liquidity supports risk-taking and funding conditions."))

        if macro.yield_curve_slope_bps is not None and macro.yield_curve_slope_bps < 0:
            evidence.append(EvidenceItem("curve_inversion", "negative", -12, "Yield-curve inversion warns of future growth stress."))

        if macro.fiscal_impulse in {"supportive", "expansionary"}:
            evidence.append(EvidenceItem("fiscal_support", "positive", 8, "Fiscal impulse supports demand and sector revenues."))
        elif macro.fiscal_impulse in {"austere", "contractionary"}:
            evidence.append(EvidenceItem("fiscal_drag", "negative", -8, "Fiscal drag can weaken demand conditions."))

        if market.index_trend_30d_pct is not None:
            if market.index_trend_30d_pct >= 3:
                evidence.append(EvidenceItem("market_risk_on", "positive", 8, "Broad market trend confirms risk-on positioning."))
            elif market.index_trend_30d_pct <= -3:
                evidence.append(EvidenceItem("market_risk_off", "negative", -10, "Broad market trend is risk-off."))

        if market.sector_trend_30d_pct is not None:
            if market.sector_trend_30d_pct >= 5:
                evidence.append(EvidenceItem("sector_momentum", "positive", 8, f"{proposal.sector} sector trend supports the proposal."))
            elif market.sector_trend_30d_pct <= -5:
                evidence.append(EvidenceItem("sector_weakness", "negative", -8, f"{proposal.sector} sector trend conflicts with the proposal."))

        if market.volatility_percentile is not None and market.volatility_percentile >= 75:
            evidence.append(EvidenceItem("volatility_elevated", "negative", -12, "Volatility is elevated, raising execution and drawdown risk."))

        if market.credit_spread_change_30d_bps is not None and market.credit_spread_change_30d_bps >= 25:
            evidence.append(EvidenceItem("credit_stress", "negative", -12, "Credit spreads are widening, which often precedes equity risk aversion."))

        if market.commodity_pressure in {"rising", "high"}:
            direction = "negative"
            score = -6
            explanation = "Rising commodity pressure can worsen inflation and input-cost risk."
            if proposal.sector in {"energy", "metals", "commodities"}:
                direction = "positive"
                score = 6
                explanation = "Rising commodity pressure can support commodity-linked revenues."
            evidence.append(EvidenceItem("commodity_pressure", direction, score, explanation))

        if not evidence:
            evidence.append(EvidenceItem("insufficient_macro_evidence", "neutral", 0, "No strong macro evidence was provided; confidence should be discounted."))

        return evidence

    def _directional_score(self, action: str, evidence: list[EvidenceItem]) -> int:
        net = sum(item.score for item in evidence)
        if action == "SELL":
            net *= -1
        elif action == "HOLD":
            net = -abs(net) // 2 if abs(net) > 20 else 8

        score = 50 + net
        missing_data_penalty = 6 if len(evidence) < 4 else 0
        return max(0, min(100, round(score - missing_data_penalty)))

    def _stance(self, score: int) -> str:
        if score >= 62:
            return "support"
        if score <= 42:
            return "oppose"
        return "caution"

    def _comments(
        self,
        proposal: TradeProposal,
        evidence: list[EvidenceItem],
        stance: str,
    ) -> list[str]:
        negatives = [item for item in evidence if item.score < 0]
        positives = [item for item in evidence if item.score > 0]
        comments: list[str] = []

        if stance == "oppose":
            comments.append(f"Macro backdrop does not justify {proposal.action} {proposal.symbol} without stronger non-macro evidence.")
        elif stance == "caution":
            comments.append(f"Macro evidence is mixed; require tighter sizing, stop-loss discipline, or confirmation before acting on {proposal.symbol}.")
        else:
            comments.append(f"Macro backdrop supports the proposed {proposal.action} direction, but consensus should still check valuation and technical timing.")

        if negatives:
            top_negative = min(negatives, key=lambda item: item.score)
            comments.append(f"Primary macro challenge: {top_negative.explanation}")

        if positives and negatives:
            top_positive = max(positives, key=lambda item: item.score)
            comments.append(f"Offsetting support exists: {top_positive.explanation}")

        if proposal.horizon_days <= 7:
            comments.append("Short holding period reduces the usefulness of slow-moving macro data; market microstructure evidence should receive higher weight.")

        return comments

    def _stress_scenarios(self, macro: MacroSnapshot, market: MarketSnapshot) -> list[str]:
        scenarios = [
            "Re-score the proposal under a 100 bps policy-rate shock.",
            "Test downside if broad index momentum reverses by 5 percent.",
        ]

        if macro.currency_change_30d_pct is not None and macro.currency_change_30d_pct < 0:
            scenarios.append("Model currency depreciation continuing for another month and raising imported inflation.")
        if market.volatility_percentile is not None and market.volatility_percentile >= 60:
            scenarios.append("Run execution slippage and drawdown stress under elevated volatility.")
        if market.credit_spread_change_30d_bps is not None and market.credit_spread_change_30d_bps > 0:
            scenarios.append("Check whether credit-spread widening is an early warning for equity de-risking.")

        return scenarios

    def _dominant_signal(self, evidence: list[EvidenceItem], stance: str) -> str:
        if stance == "support":
            aligned = [item for item in evidence if item.score > 0]
            if aligned:
                strongest = max(aligned, key=lambda item: item.score)
                return f"strongest support is {strongest.label}"
        if stance == "oppose":
            aligned = [item for item in evidence if item.score < 0]
            if aligned:
                strongest = min(aligned, key=lambda item: item.score)
                return f"strongest challenge is {strongest.label}"
        strongest = sorted(evidence, key=lambda item: abs(item.score), reverse=True)[0]
        return f"dominant mixed signal is {strongest.label} ({strongest.direction})"

    def _recommended_direction(self, action: str, stance: str) -> str:
        if stance == "support":
            return action
        if stance == "oppose":
            if action == "BUY":
                return "HOLD_OR_SELL"
            if action == "SELL":
                return "HOLD_OR_BUY"
        return "HOLD"
