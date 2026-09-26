"""Streamlit front end: pick your ETFs, see what you really own."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from etf_overlap.data import load_funds, load_holdings
from etf_overlap.overlap import concentration, look_through, overlap_matrix, pair_overlap, redundant_pairs

# Fixed categorical order: a fund keeps its color no matter how many are selected.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#4a3aa7"]
SEQUENTIAL = ["#f0efec", "#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#104281"]
SURFACE = "#fcfcfb"
INK, INK_2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
MAX_FUNDS = len(SERIES)
REDUNDANT_AT = 50.0

st.set_page_config(page_title="ETF Overlap Analyzer", page_icon="📊", layout="wide")


@st.cache_data
def get_funds() -> pd.DataFrame:
    return load_funds()


@st.cache_data
def get_holdings(funds: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    return load_holdings(list(funds))


def base_layout(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=8, b=8),
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", color=INK_2, size=13),
        hoverlabel=dict(bgcolor="white", font_color=INK, bordercolor=GRID),
    )
    return fig


def exposure_chart(exposure: pd.DataFrame, funds: list[str], colors: dict[str, str], top: int = 15) -> go.Figure:
    data = exposure.head(top).iloc[::-1]
    labels = data["ticker"] + "  " + data["name"].str.slice(0, 28)
    fig = go.Figure()
    for fund in funds:
        fig.add_bar(
            y=labels,
            x=data[fund],
            name=fund,
            orientation="h",
            marker=dict(color=colors[fund], line=dict(color=SURFACE, width=2)),
            customdata=data[["exposure"]].values,
            hovertemplate=f"<b>%{{y}}</b><br>via {fund}: %{{x:.2f}}%<br>total: %{{customdata[0]:.2f}}%<extra></extra>",
        )
    fig.update_layout(barmode="stack", bargap=0.3, legend=dict(orientation="h", y=1.06, x=0, title=None, traceorder="normal"))
    fig.update_xaxes(ticksuffix="%", gridcolor=GRID, zeroline=False, color=MUTED)
    fig.update_yaxes(color=INK_2, tickfont=dict(size=12))
    return base_layout(fig, 34 * top + 60)


def overlap_heatmap(matrix: pd.DataFrame) -> go.Figure:
    shown = matrix.copy()
    for f in shown.index:
        shown.loc[f, f] = None  # a fund vs itself is always 100% and adds nothing
    fig = go.Figure(
        go.Heatmap(
            z=shown.values,
            x=shown.columns,
            y=shown.index,
            zmin=0,
            zmax=100,
            colorscale=[[i / (len(SEQUENTIAL) - 1), c] for i, c in enumerate(SEQUENTIAL)],
            text=[[("" if pd.isna(v) else f"{v:.0f}%") for v in row] for row in shown.values],
            texttemplate="%{text}",
            textfont=dict(size=14),
            xgap=2,
            ygap=2,
            hovertemplate="%{y} ↔ %{x}: <b>%{z:.1f}%</b> of money in the same stocks<extra></extra>",
            colorbar=dict(ticksuffix="%", thickness=10, outlinewidth=0),
        )
    )
    fig.update_yaxes(autorange="reversed", color=INK_2, showgrid=False, ticks="")
    fig.update_xaxes(side="top", color=INK_2, showgrid=False, ticks="")
    return base_layout(fig, 70 * len(matrix) + 60)


# --- Sidebar: portfolio input -------------------------------------------

funds_meta = get_funds()
all_funds = list(funds_meta.index)

st.sidebar.header("Your portfolio")
selected = st.sidebar.multiselect(
    "ETFs you own",
    options=all_funds,
    default=["SPY", "QQQ", "XLK"],
    max_selections=MAX_FUNDS,
    format_func=lambda f: f"{f} · {funds_meta.loc[f, 'fund_name']}",
)
st.sidebar.caption("How much is in each one? Dollars or percentages, it's rescaled automatically.")
allocation = {
    f: st.sidebar.number_input(f, min_value=0.0, value=10_000.0, step=1_000.0, format="%.0f", key=f"alloc_{f}")
    for f in selected
}
st.sidebar.divider()
st.sidebar.caption(
    f"Holdings as of {funds_meta['as_of'].max()}, taken from the issuers' own files "
    "(State Street SPDR, Invesco). Not investment advice."
)

# --- Main page ------------------------------------------------------------

st.title("ETF Overlap Analyzer")
st.markdown("Owning five funds doesn't mean you're diversified. See how much they overlap and what you **really** own underneath.")

if len(selected) < 2 or sum(allocation.values()) <= 0:
    st.info("Pick at least two ETFs and put some amount in each to see the analysis.")
    st.stop()

holdings = get_holdings(tuple(selected))
colors = {f: SERIES[i] for i, f in enumerate(selected)}
exposure = look_through(holdings, allocation)
conc = concentration(exposure)
matrix = overlap_matrix(holdings)
pairs = redundant_pairs(matrix, REDUNDANT_AT)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Different stocks you own", f"{conc.stocks:,}")
k2.metric("Money in your top 10 stocks", f"{conc.top10_share:.0f}%")
k3.metric("Behaves like", f"{conc.effective_stocks:.0f} stocks", help=(
    "Diversification expressed as a number of equally weighted stocks "
    "(inverse Herfindahl index). Lower = more concentrated."
))
top_pair = max(
    ((fa, fb, matrix.loc[fa, fb]) for i, fa in enumerate(selected) for fb in selected[i + 1 :]),
    key=lambda p: p[2],
)
k4.metric(f"Biggest overlap · {top_pair[0]} ↔ {top_pair[1]}", f"{top_pair[2]:.0f}%")

if pairs:
    lines = [f"- **{a}** and **{b}** share **{v:.0f}%** of their money in the same stocks." for a, b, v in pairs]
    st.warning("**Possible duplication**\n\n" + "\n".join(lines) + "\n\nYou may be paying two fees for roughly the same exposure.", icon="⚠️")
else:
    st.success(f"No pair of your funds overlaps by more than {REDUNDANT_AT:.0f}%.", icon="✅")

left, right = st.columns([3, 2], gap="large")
with left:
    st.subheader("What you really own")
    st.caption("Your 15 biggest stock positions once every fund is opened up. Each color shows which fund it comes from.")
    st.plotly_chart(exposure_chart(exposure, selected, colors), width="stretch", config={"displayModeBar": False})
with right:
    st.subheader("How much each pair overlaps")
    st.caption("Share of money invested in the same stocks, in the same amounts, by both funds.")
    st.plotly_chart(overlap_heatmap(matrix), width="stretch", config={"displayModeBar": False})

st.subheader("Compare two funds")
c1, c2 = st.columns(2)
fa = c1.selectbox("Fund A", selected, index=0)
fb = c2.selectbox("Fund B", [f for f in selected if f != fa], index=0)
pair = pair_overlap(fa, holdings[fa], fb, holdings[fb])
m1, m2, m3 = st.columns(3)
m1.metric("Weight overlap", f"{pair.weight_overlap:.1f}%")
m2.metric(f"{fa} stocks also in {fb}", f"{pair.common_count} of {pair.count_a}", f"{pair.share_of_a:.0f}%", delta_color="off")
m3.metric(f"{fb} stocks also in {fa}", f"{pair.common_count} of {pair.count_b}", f"{pair.share_of_b:.0f}%", delta_color="off")
st.dataframe(
    pair.common.rename(columns={"weight_a": f"Weight in {fa}", "weight_b": f"Weight in {fb}", "overlap": "Overlap"}),
    hide_index=True,
    width="stretch",
    height=280,
    column_config={
        "ticker": "Ticker",
        "name": "Company",
        f"Weight in {fa}": st.column_config.NumberColumn(format="%.2f%%"),
        f"Weight in {fb}": st.column_config.NumberColumn(format="%.2f%%"),
        "Overlap": st.column_config.ProgressColumn(format="%.2f%%", min_value=0, max_value=float(pair.common["overlap"].max()) if len(pair.common) else 1.0),
    },
)

with st.expander("Full look-through table"):
    table = exposure.rename(columns={"ticker": "Ticker", "name": "Company", "exposure": "Portfolio %", "funds_holding": "Held by # funds"})
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        column_config={c: st.column_config.NumberColumn(format="%.3f%%") for c in ["Portfolio %", *selected]},
    )
    st.download_button("Download CSV", table.to_csv(index=False).encode(), "look_through.csv", "text/csv")
