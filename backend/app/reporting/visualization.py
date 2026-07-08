"""Visualization Agent: builds Plotly figures (as JSON-serializable dicts) for
the portfolio growth curve with trade markers overlaid. Served by the backend
API and rendered by the Streamlit frontend."""

from __future__ import annotations

import plotly.graph_objects as go

LINE_COLOR = "#22D3EE"
BUY_COLOR = "#4ADE80"
SELL_COLOR = "#F87171"
GRID_COLOR = "#1E293B"
TEXT_COLOR = "#94A3B8"


def build_equity_curve(timestamps: list[str], equity_values: list[float], trade_markers: list[dict]) -> dict:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=timestamps, y=equity_values, mode="lines", name="Portfolio Value (₹)",
            line={"width": 2.5, "color": LINE_COLOR}, fill="tozeroy", fillcolor="rgba(34, 211, 238, 0.08)",
        )
    )

    if trade_markers:
        buy_x = [t["timestamp"] for t in trade_markers if t["action"] == "BUY"]
        buy_y = [t["value"] for t in trade_markers if t["action"] == "BUY"]
        sell_x = [t["timestamp"] for t in trade_markers if t["action"] == "SELL"]
        sell_y = [t["value"] for t in trade_markers if t["action"] == "SELL"]

        fig.add_trace(go.Scatter(x=buy_x, y=buy_y, mode="markers", name="BUY", marker={"symbol": "triangle-up", "size": 12, "color": BUY_COLOR, "line": {"width": 1, "color": "#052e16"}}))
        fig.add_trace(go.Scatter(x=sell_x, y=sell_y, mode="markers", name="SELL", marker={"symbol": "triangle-down", "size": 12, "color": SELL_COLOR, "line": {"width": 1, "color": "#450a0a"}}))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": TEXT_COLOR, "family": "Inter, Segoe UI, sans-serif"},
        title={"text": "Portfolio Growth Curve", "font": {"color": "#F1F5F9", "size": 16}},
        xaxis={"title": "Time", "gridcolor": GRID_COLOR, "zerolinecolor": GRID_COLOR},
        yaxis={"title": "Value (₹)", "gridcolor": GRID_COLOR, "zerolinecolor": GRID_COLOR},
        legend={"bgcolor": "rgba(0,0,0,0)"},
        margin={"t": 50, "b": 40, "l": 50, "r": 20},
    )
    return fig.to_dict()


def build_price_chart(symbol: str, bars, trades: list[dict]) -> dict:
    """Candlestick chart for one symbol's recent intraday bars, with this
    portfolio's BUY/SELL fills for that symbol overlaid as markers."""
    # Plotly's .to_dict() keeps pandas/numpy objects as-is; FastAPI's JSON
    # serializer can't handle those, so convert to plain Python types up front.
    x = [ts.isoformat() for ts in bars.index.to_pydatetime()]
    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=x,
            open=bars["Open"].astype(float).tolist(),
            high=bars["High"].astype(float).tolist(),
            low=bars["Low"].astype(float).tolist(),
            close=bars["Close"].astype(float).tolist(),
            name=symbol, increasing_line_color=BUY_COLOR, decreasing_line_color=SELL_COLOR,
        )
    )

    if trades:
        buy_x = [t["timestamp"] for t in trades if t["action"] == "BUY"]
        buy_y = [t["price"] for t in trades if t["action"] == "BUY"]
        sell_x = [t["timestamp"] for t in trades if t["action"] == "SELL"]
        sell_y = [t["price"] for t in trades if t["action"] == "SELL"]

        fig.add_trace(go.Scatter(
            x=buy_x, y=buy_y, mode="markers", name="BUY fill",
            marker={"symbol": "triangle-up", "size": 13, "color": BUY_COLOR, "line": {"width": 1, "color": "#052e16"}},
        ))
        fig.add_trace(go.Scatter(
            x=sell_x, y=sell_y, mode="markers", name="SELL fill",
            marker={"symbol": "triangle-down", "size": 13, "color": SELL_COLOR, "line": {"width": 1, "color": "#450a0a"}},
        ))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"color": TEXT_COLOR, "family": "Inter, Segoe UI, sans-serif"},
        title={"text": f"{symbol} — Intraday Price", "font": {"color": "#F1F5F9", "size": 16}},
        xaxis={"title": "Time", "gridcolor": GRID_COLOR, "zerolinecolor": GRID_COLOR, "rangeslider": {"visible": False}},
        yaxis={"title": "Price (₹)", "gridcolor": GRID_COLOR, "zerolinecolor": GRID_COLOR},
        legend={"bgcolor": "rgba(0,0,0,0)"},
        margin={"t": 50, "b": 40, "l": 50, "r": 20},
    )
    return fig.to_dict()
