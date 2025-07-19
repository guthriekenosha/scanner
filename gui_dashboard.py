# gui_dashboard.py
import streamlit as st
import pandas as pd
import os
from streamlit_autorefresh import st_autorefresh
import plotly.graph_objs as go
from datetime import datetime
from datetime import timedelta
import numpy as np
import matplotlib
matplotlib.use("Agg")
import pytz
st.markdown(
    "<style> .css-18e3th9 { padding-top: 1rem; } .block-container { padding-top: 1rem; } </style>",
    unsafe_allow_html=True
)


# --- Candle loader for real OHLC data from Blofin API ---
import requests

def load_candles(symbol, timeframe):
    resolution_map = {
        "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
        "30m": "30m", "1h": "1H", "4h": "4H", "1d": "1D"
    }
    resolution = resolution_map.get(timeframe, "1m")

    url = "https://openapi.blofin.com/api/v1/market/candles"
    params = {
        "instId": symbol,
        "bar": resolution,
        "limit": 50
    }
    try:
        response = requests.get(url, params=params)
        data = response.json()
        if data["code"] != "0":
            return None
        if not data.get("data"):
            return None
        candles = pd.DataFrame(data["data"], columns=[
            "timestamp", "open", "high", "low", "close", "volume", "volCcy", "volCcyQuote", "confirm"
        ])
        candles["timestamp"] = pd.to_datetime(candles["timestamp"], unit="ms")
        candles = candles.astype({
            "open": float,
            "high": float,
            "low": float,
            "close": float
        })
        return candles
    except Exception as e:
        print(f"Error fetching candles for {symbol}: {e}")
        return None

st.set_page_config(layout="wide")
# Auto-refresh every 60 seconds
st_autorefresh(interval=60000, key="refresh")

import gspread
from google.oauth2.service_account import Credentials

import json
# Load Google Sheet
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(json.loads(os.environ["GOOGLE_CREDS_JSON"]), scopes=scope)
client = gspread.authorize(creds)
today_str = datetime.now().strftime("Signal Log %Y-%m-%d")
try:
    sheet = client.open(today_str).sheet1
except Exception as e:
    st.warning(f"⚠️ Could not find today's sheet ({today_str}). Attempting to load most recent sheet...")
    try:
        # Get all spreadsheets accessible by the service account
        sheet_titles = [f.title for f in client.list_spreadsheet_files()]
        sorted_titles = sorted([s for s in sheet_titles if s.startswith("Signal Log")], reverse=True)
        if not sorted_titles:
            st.error("❌ No Signal Log sheets found.")
            st.stop()
        most_recent = sorted_titles[0]
        sheet = client.open(most_recent).sheet1
        st.success(f"✅ Loaded fallback sheet: {most_recent}")
    except Exception as inner_e:
        st.error(f"❌ Failed to load fallback sheet: {inner_e}")
        st.stop()
data = sheet.get_all_records()
df = pd.DataFrame(data)

st.sidebar.title("🔍 Filters")

df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert("US/Eastern")
# Sidebar date pickers for filtering by date range
start_date = st.sidebar.date_input(
    "Start Date",
    value=pd.Timestamp.now(tz="US/Eastern").date() - pd.Timedelta(days=3)
)
end_date = st.sidebar.date_input(
    "End Date",
    value=pd.Timestamp.now(tz="US/Eastern").date()
)
# Convert start_date and end_date to datetime.date before filtering
start_date = start_date.date()
end_date = end_date.date()
df = df[(df["timestamp"].dt.date >= start_date) & (df["timestamp"].dt.date <= end_date)]

min_score = st.sidebar.slider("Minimum Confidence Score", 0, 10, 4)

# Optional: Signal expiration override slider
expire_minutes = st.sidebar.slider("⏳ Max Signal Age (minutes)", 5, 240, 60)

current = df.drop_duplicates(subset=["symbol", "timeframe"], keep="first")
filtered = current[current["score"] >= min_score]

# Remove signals older than expire_minutes
now = pd.Timestamp.now(tz="UTC").astimezone(pytz.timezone("US/Eastern"))
filtered = filtered[(now - filtered["timestamp"]) <= pd.Timedelta(minutes=expire_minutes)]

# Add trend column before filtering trends
filtered.loc[:, "trend"] = np.where(filtered["ema21"] > filtered["ema50"], "📈 Uptrend", "📉 Downtrend")

# Setup type badge based on reason
def get_setup_badge(reason):
    reason = str(reason).lower()
    if "early" in reason:
        return "🔵 Early Breakout"
    elif "pullback" in reason:
        return "🟠 Pullback Rebound"
    elif "1m" in reason:
        return "⚪ 1m Hint"
    elif "breakout" in reason:
        return "🟢 Breakout"
    return "⚪ Unknown"

filtered.loc[:, "setup_type_badge"] = filtered["notes"].apply(get_setup_badge)

# Add type icons before filtering types
filtered.loc[:, "type_icon"] = filtered["type"].map({"long": "🟢 Long", "short": "🔴 Short"})

setup_types = ["All"] + list(filtered["setup_type_badge"].dropna().unique())
selected_setup = st.sidebar.multiselect("🧩 Setup Type", setup_types, default=["All"])

trends = ["All"] + list(filtered["trend"].dropna().unique())
selected_trend = st.sidebar.multiselect("📈 Trend", trends, default=["All"])

types = ["All"] + list(filtered["type_icon"].dropna().unique())
selected_type = st.sidebar.multiselect("📍 Type", types, default=["All"])

signal_modes = ["All", "🟡 Anticipation", "🟢 Confirmation"]
selected_mode = st.sidebar.multiselect("🎯 Signal Mode", signal_modes, default=["All"])

st.sidebar.markdown("### 🔝 Most Frequent Signals")
top_symbols = df["symbol"].value_counts().head(5)
st.sidebar.bar_chart(top_symbols)

# Show only the most recent signal per symbol + timeframe
# current = df.drop_duplicates(subset=["symbol", "timeframe"], keep="first")
# filtered = current[current["score"] >= min_score]

central = pytz.timezone("US/Central")
now = pd.Timestamp.now(tz="UTC").astimezone(central)

# Sidebar override for expiration (obsolete, now handled above)
# if expire_minutes < 240:
#     filtered = filtered[now - filtered["timestamp"] <= pd.Timedelta(minutes=expire_minutes)]

if "cycle_index" not in st.session_state:
    st.session_state.cycle_index = 0

if "All" not in selected_setup:
    filtered = filtered[filtered["setup_type_badge"].isin(selected_setup)]

if "All" not in selected_trend:
    filtered = filtered[filtered["trend"].isin(selected_trend)]

if "All" not in selected_type:
    filtered = filtered[filtered["type_icon"].isin(selected_type)]

if "All" not in selected_mode:
    if "🟡 Anticipation" in selected_mode and "🟢 Confirmation" not in selected_mode:
        filtered = filtered[filtered["notes"].str.contains("Early|Hint", case=False, na=False)]
    elif "🟢 Confirmation" in selected_mode and "🟡 Anticipation" not in selected_mode:
        filtered = filtered[~filtered["notes"].str.contains("Early|Hint", case=False, na=False)]

if len(filtered) > 0:
    st.session_state.cycle_index = (st.session_state.cycle_index + 1) % len(filtered)
else:
    st.session_state.cycle_index = 0

# filtered.loc[:, "type_icon"] = filtered["type"].map({"long": "🟢 Long", "short": "🔴 Short"})
filtered["stars"] = filtered["score"].apply(lambda s: "⭐" * int(s))

# Optionally highlight signals about to expire
filtered["age_minutes"] = (now - filtered["timestamp"]).dt.total_seconds() / 60
filtered["age_minutes"] = filtered["age_minutes"].astype(int)
filtered["expires_soon"] = filtered["age_minutes"] > (expire_minutes * 0.8)

def format_duration(minutes):
    hours = int(minutes) // 60
    mins = int(minutes) % 60
    return f"{hours}h {mins}m" if hours else f"{mins}m"

filtered["signal_age"] = filtered["age_minutes"].apply(format_duration)

# Added signal_mode column based on notes and price_from_breakout
def determine_signal_mode(row):
    notes = str(row["notes"]).lower()
    price_from_breakout = row.get("price_from_breakout", None)
    if price_from_breakout is not None:
        if price_from_breakout >= -0.5:
            return "🟢 Confirmation"
        else:
            return "🟡 Anticipation"
    # fallback to previous logic
    if "early" in notes or "hint" in notes:
        return "🟡 Anticipation"
    else:
        return "🟢 Confirmation"

filtered["signal_mode"] = filtered.apply(determine_signal_mode, axis=1)

filtered = filtered.sort_values(by=["score", "rsi"], ascending=False)

st.markdown("### 🧠 Signal Summary")
col1, col2, col3, col4 = st.columns(4)
col1.metric("📊 Total Signals", len(df))
col2.metric("🟢 Current Displayed", len(filtered))
col3.metric("⏱️ Latest Signal (CST)", df['timestamp'].max().strftime("%H:%M:%S"))
col4.metric("⚡ Top Symbol", df['symbol'].mode()[0] if not df['symbol'].empty else "N/A")

st.markdown(f"### Current Signals ({len(filtered)} displayed)")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Format bottom_bounce_score, rsi_bounce_signal, ema_reclaim, and support_sweep_reversal in df before display
if 'bottom_bounce_score' in filtered.columns:
    filtered['bottom_bounce_score'] = filtered['bottom_bounce_score'].apply(lambda x: f"🟢 {x:.2f}" if not pd.isna(x) else '')
if 'rsi_bounce_signal' in filtered.columns:
    filtered['rsi_bounce_signal'] = filtered['rsi_bounce_signal'].apply(lambda x: '🔻' if x else '')
if 'ema_reclaim' in filtered.columns:
    filtered['ema_reclaim'] = filtered['ema_reclaim'].apply(lambda x: '📈' if x else '')
if 'support_sweep_reversal' in filtered.columns:
    filtered['support_sweep_reversal'] = filtered['support_sweep_reversal'].apply(lambda x: '✅' if x else '❌')

# Live price change % from most recent candle
def get_live_price_change(row):
    candles = load_candles(row["symbol"], row["timeframe"])
    if candles is None or candles.empty:
        return "N/A"
    latest_close = candles["close"].iloc[-1]
    change_pct = (latest_close - row["price"]) / row["price"] * 100
    arrow = "▲" if change_pct > 0 else "▼"
    color = "green" if change_pct > 0 else "red"
    return f"{arrow} {change_pct:.2f}%"

filtered["price_change_pct"] = filtered.apply(get_live_price_change, axis=1)

# TP Zones (2x, 3x, 5x RR from breakout)
breakout_level = filtered["price"] - filtered["price_from_breakout"]
filtered["tp1"] = breakout_level + (filtered["price"] - breakout_level) * 2
filtered["tp2"] = breakout_level + (filtered["price"] - breakout_level) * 3
filtered["tp3"] = breakout_level + (filtered["price"] - breakout_level) * 5

# Add bounce-related fields
filtered["bottom_bounce_score"] = filtered.get("bottom_bounce_score", 0)
filtered["rsi_bounce_signal"] = filtered.get("rsi_bounce_signal", False)
filtered["ema_reclaim"] = filtered.get("ema_reclaim", False)
filtered["support_sweep_reversal"] = filtered.get("support_sweep_reversal", False)
filtered["simulated_bounce_pnl"] = filtered.get("simulated_bounce_pnl", 0.0)
filtered["confidence_stars"] = filtered.get("confidence_stars", "")

# Adjust display of signal_mode badges to match new logic
def display_signal_mode_badge(mode):
    if mode == "🟢 Confirmation":
        return "🟢 Confirmation"
    elif mode == "🟡 Anticipation":
        return "🟡 Anticipation"
    else:
        return mode

filtered["signal_mode"] = filtered["signal_mode"].apply(display_signal_mode_badge)

display_columns = [
    'timestamp', 'symbol', 'timeframe', 'type_icon', 'setup_type_badge',
    'trend', 'signal_mode', 'price', 'price_from_breakout', 'price_change_pct',
    'tp1', 'tp2', 'tp3', 'rsi', 'ema21', 'ema50', 'score', 'stars', 'signal_age',
    'notes',
    'bottom_bounce_score', 'rsi_bounce_signal', 'ema_reclaim', 'simulated_bounce_pnl', 'support_sweep_reversal'
]

styled_table = filtered[display_columns].style.background_gradient(subset=["score"], cmap="Reds") \
  .applymap(lambda x: "color: red;" if isinstance(x, str) and "RSI" in x else "", subset=["notes"]) \
  .applymap(lambda x: "color: green;" if isinstance(x, str) and "Breakout" in x else "", subset=["setup_type_badge"]) \
  .applymap(lambda x: "color: blue;" if isinstance(x, str) and "Pullback" in x else "", subset=["setup_type_badge"]) \
  .applymap(lambda x: "color: gray;" if isinstance(x, str) and "1m" in x else "", subset=["setup_type_badge"])

st.dataframe(styled_table)

st.markdown("### 📈 Live Candle Snapshots")

if len(filtered) > 0:
    row = filtered.iloc[st.session_state.cycle_index]
    rows_to_show = [row]
else:
    st.warning("No matching signals to display based on current filters.")
    rows_to_show = []

for row in rows_to_show:
    label = f"{row['symbol']} [{row['timeframe']}]"
    if row["signal_mode"] == "🟢 Confirmation":
        label += " ✅"
    with st.expander(label):
        candles = load_candles(row["symbol"], row["timeframe"])
        if candles is not None:
            fig = go.Figure()

            for i in range(len(candles)):
                frame = go.Candlestick(
                    x=candles["timestamp"][:i+1],
                    open=candles["open"][:i+1],
                    high=candles["high"][:i+1],
                    low=candles["low"][:i+1],
                    close=candles["close"][:i+1],
                    name="Price"
                )
                fig.add_trace(frame)

            fig.update_layout(
                title=f"{row['symbol']} Real Candle Chart",
                xaxis_title="Time",
                yaxis_title="Price",
                height=300,
                xaxis_rangeslider_visible=False,
                updatemenus=[dict(
                    type="buttons",
                    showactive=False,
                    buttons=[dict(label="▶ Play",
                                  method="animate",
                                  args=[None, {"frame": {"duration": 250, "redraw": True},
                                               "fromcurrent": True,
                                               "transition": {"duration": 0}}])]
                )],
                sliders=[{
                    "steps": [{"args": [[f.name], {"frame": {"duration": 0, "redraw": True},
                                                  "mode": "immediate"}],
                               "label": str(candles['timestamp'].iloc[i]),
                               "method": "animate"} for i, f in enumerate(fig.frames)],
                    "transition": {"duration": 0},
                    "x": 0.1,
                    "len": 0.9
                }]
            )

            fig.frames = [
                go.Frame(data=[go.Candlestick(
                    x=candles["timestamp"][:k+1],
                    open=candles["open"][:k+1],
                    high=candles["high"][:k+1],
                    low=candles["low"][:k+1],
                    close=candles["close"][:k+1]
                )], name=str(candles["timestamp"].iloc[k]))
                for k in range(len(candles))
            ]

            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning(f"No candle data found for {row['symbol']} [{row['timeframe']}]")

st.markdown("---")

st.markdown("### 🛠️ Smart Alerts Panel")
for _, row in filtered.iterrows():
    if row["rsi"] > 80:
        st.error(f"🔺 RSI EXTREME on {row['symbol']} ({row['timeframe']}) — RSI: {row['rsi']:.2f}")
    elif row["rsi"] > 70:
        st.warning(f"🔺 RSI overbought on {row['symbol']} ({row['timeframe']}) — RSI: {row['rsi']:.2f}")
    elif row["rsi"] < 30:
        st.info(f"🔻 RSI oversold on {row['symbol']} ({row['timeframe']}) — RSI: {row['rsi']:.2f}")

if st.button("🔄 Refresh Now"):
    st.rerun()