"""
Tagmarshal GPS Signal Heatmap
=============================
Pulls round fixes from the Tagmarshal dashboard API, computes the transmission
delay (Diff = Received - Recorded) and recording interval for every fix, and
plots them on a satellite map of the course to reveal where device signal is
weakest.

Because devices do NOT buffer fixes, a large Diff (or a large Interval gap)
appears on the FIRST fix transmitted AFTER the device regains signal. The
outage therefore happened somewhere between the previous fix and that fix, so
the app can optionally spread the "badness" weight along that whole segment
instead of pinning it to a single point.

Run:  streamlit run app.py
"""

import math
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests
import streamlit as st
import folium
from folium.plugins import HeatMap
from streamlit_folium import st_folium

# ---------------------------------------------------------------- page setup
st.set_page_config(
    page_title="GPS Signal Heatmap",
    page_icon="📡",
    layout="wide",
)

# ------------------------------------------------------------ brand styling
# Tagmarshal Brand Guide CI 2025:
#   Green #89BF40 · Gray #313131 · Dark gradient #30383D→#191D21
#   Accents: Orange #FF9933, Yellow #FFD700, Red #E93939
#   Headings: Barlow Condensed SemiBold 600 (all-caps) · Body: Roboto 400
TM_GREEN = "#89BF40"
TM_GRAY = "#313131"
TM_ORANGE = "#FF9933"
TM_YELLOW = "#FFD700"
TM_RED = "#E93939"

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:ital,wght@0,600;1,600&family=Roboto:wght@400;700&display=swap');

html, body, [class*="css"], p, li, label, .stMarkdown {
    font-family: 'Roboto', sans-serif;
}
h1, h2, h3, h4, h5,
[data-testid="stMetricLabel"], .stButton button, .stDownloadButton button {
    font-family: 'Barlow Condensed', sans-serif !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.02em;
}
h1, h2, h3 { color: #F5F5F5; }

/* Hide Streamlit chrome: menu, footer badge, toolbar, deploy/manage buttons */
#MainMenu, footer, header [data-testid="stToolbar"],
[data-testid="stStatusWidget"], .stAppDeployButton,
[data-testid="manage-app-button"],
a[href*="streamlit.io/cloud"], .viewerBadge_container__r5tak,
[class*="viewerBadge"] {
    visibility: hidden !important;
    display: none !important;
}

/* Green title block, echoing the brand book section headers */
.tm-header {
    background: linear-gradient(135deg, #30383D 0%, #191D21 100%);
    border-bottom: 4px solid #89BF40;
    padding: 22px 28px 18px 28px;
    border-radius: 6px;
    margin-bottom: 14px;
}
.tm-header h1 {
    font-family: 'Barlow Condensed', sans-serif;
    font-weight: 600;
    font-style: italic;
    text-transform: uppercase;
    font-size: 44px;
    line-height: 1.05;
    margin: 0;
    color: #FFFFFF;
}
.tm-header h1 .tm-green { color: #89BF40; }
.tm-header p {
    color: #C9CDD1;
    margin: 8px 0 0 0;
    font-size: 15px;
    max-width: 860px;
}

/* Metric values in Tagmarshal green */
[data-testid="stMetricValue"] {
    font-family: 'Barlow Condensed', sans-serif;
    font-weight: 600;
    color: #89BF40;
}

/* Buttons: green fill, dark text, like brand CTAs */
.stButton button[kind="primary"], .stDownloadButton button {
    background-color: #89BF40 !important;
    color: #191D21 !important;
    border: none !important;
}
.stButton button[kind="primary"]:hover, .stDownloadButton button:hover {
    background-color: #78A838 !important;
}

/* Sidebar headers get the green treatment */
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: #89BF40;
}
</style>

<div class="tm-header">
  <h1>GPS Signal <span class="tm-green">Heatmap</span></h1>
  <p>Pulls every round's fixes for a date range, measures the delay between
  device-recorded time and server-received time, and maps where on the course
  the signal drops out.</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Connection")
    base_url = st.text_input(
        "API base URL (region host + course slug)",
        value="https://lon1.tagmarshal.golf/dumbarnielinks",
        help="Same base the dashboard uses, e.g. "
             "https://lon1.tagmarshal.golf/<course-slug>",
    ).rstrip("/")

    user_token = st.text_input(
        "UserToken (JWT)",
        type="password",
        help=(
            "Grab this from the dashboard while logged in: "
            "DevTools → Application → Local Storage → "
            "dashboard.tagmarshal.golf → key 'auth.userToken' "
            "(or copy the UserToken request header from the Network tab). "
            "It is only kept in this browser session."
        ),
    )

    st.header("Date range")
    today = date.today()
    start_d = st.date_input("Start date", value=today)
    end_d = st.date_input("End date", value=today)

    max_rounds = st.number_input(
        "Max rounds to fetch", min_value=1, max_value=500, value=50,
        help="Safety cap — each round is one API call for its fixes.",
    )
    req_delay = st.slider(
        "Delay between requests (s)", 0.0, 2.0, 0.2, 0.1,
        help="Be gentle on the server when pulling many rounds.",
    )

    fetch_btn = st.button("🔄 Fetch rounds & fixes", type="primary",
                          use_container_width=True)


# ---------------------------------------------------------------- API helpers
def _headers(token: str) -> dict:
    return {
        "Accept": "application/json, text/plain, */*",
        "UserToken": token,
        "Origin": "https://dashboard.tagmarshal.golf",
        "Referer": "https://dashboard.tagmarshal.golf/",
        "User-Agent": "Mozilla/5.0 (signal-heatmap-tool)",
    }


def fetch_rounds(base: str, token: str, start: date, end: date,
                 cap: int) -> list[dict]:
    """Fetch all rounds between two dates (paginated)."""
    rounds, page, per_page = [], 1, 100
    while len(rounds) < cap:
        r = requests.get(
            f"{base}/rounds",
            params={
                "startDate": start.isoformat(),
                "endDate": end.isoformat(),
                "page": page,
                "records": per_page,
                "sort": "startTime+asc,tag+desc",
            },
            headers=_headers(token),
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        batch = data.get("rounds", [])
        rounds.extend(batch)
        total = data.get("totalRecords", len(rounds))
        if len(rounds) >= total or not batch:
            break
        page += 1
    return rounds[:cap]


def fetch_fixes(base: str, token: str, round_id: str) -> list[dict]:
    r = requests.get(
        f"{base}/fixes/roundFixes/{round_id}",
        headers=_headers(token),
        timeout=60,
    )
    r.raise_for_status()
    out = r.json()
    return out if isinstance(out, list) else []


# ---------------------------------------------------------------- parsing
def _parse_ts(s):
    """Parse timestamps like '2026-07-05 08:13:52' (a few fallbacks)."""
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(str(s).strip(), fmt)
        except ValueError:
            continue
    return None


def fixes_to_df(all_fixes: dict[str, list[dict]],
                round_meta: dict[str, dict]) -> pd.DataFrame:
    """Flatten raw fixes into a tidy DataFrame with computed diff/interval."""
    rows = []
    for rid, fixes in all_fixes.items():
        meta = round_meta.get(rid, {})
        prev_rec = None
        prev_lat = prev_lon = None
        for f in fixes:
            lat, lon = f.get("latitude"), f.get("longitude")
            try:
                lat, lon = float(lat), float(lon)
            except (TypeError, ValueError):
                continue
            rec = _parse_ts(f.get("recordedTime"))
            rcv = _parse_ts(f.get("receivedTime"))

            # Diff: prefer computing from raw timestamps (robust);
            # fall back to the API's pre-formatted string.
            diff_s = None
            if rec and rcv:
                diff_s = max((rcv - rec).total_seconds(), 0.0)
            interval_s = None
            if rec and prev_rec:
                interval_s = max((rec - prev_rec).total_seconds(), 0.0)

            rows.append({
                "round_id": rid,
                "tag": meta.get("tag"),
                "device_id": meta.get("deviceId"),
                "fix_id": f.get("_id"),
                "recorded": rec,
                "received": rcv,
                "diff_s": diff_s,
                "interval_s": interval_s,
                "location": f.get("location") or "Unknown",
                "lat": lat,
                "lon": lon,
                "prev_lat": prev_lat,
                "prev_lon": prev_lon,
                "accuracy": f.get("accuracy"),
                "signal_strength": f.get("lastSignalStrength"),
                "signal_quality": f.get("lastSignalQuality")
                                  or f.get("lastSignalSuality"),
                "cached": f.get("cached"),
            })
            prev_rec = rec or prev_rec
            prev_lat, prev_lon = lat, lon
    df = pd.DataFrame(rows)
    if not df.empty:
        df["diff_s"] = pd.to_numeric(df["diff_s"], errors="coerce")
        df["interval_s"] = pd.to_numeric(df["interval_s"], errors="coerce")
    return df


# ---------------------------------------------------------------- fetch flow
if fetch_btn:
    if not user_token:
        st.error("Paste your UserToken first — the API rejects requests "
                 "without it.")
        st.stop()
    try:
        with st.spinner("Fetching round list…"):
            rounds = fetch_rounds(base_url, user_token, start_d, end_d,
                                  int(max_rounds))
    except requests.HTTPError as e:
        st.error(f"Rounds request failed ({e.response.status_code}). "
                 "Check the base URL and that your token hasn't expired.")
        st.stop()
    except requests.RequestException as e:
        st.error(f"Network error fetching rounds: {e}")
        st.stop()

    if not rounds:
        st.warning("No rounds found for that date range.")
        st.stop()

    st.info(f"Found **{len(rounds)}** rounds — fetching fixes for each…")
    all_fixes, meta, failed = {}, {}, []
    prog = st.progress(0.0)
    for i, rnd in enumerate(rounds):
        rid = rnd.get("id")
        meta[rid] = rnd
        try:
            all_fixes[rid] = fetch_fixes(base_url, user_token, rid)
        except requests.RequestException:
            failed.append(rid)
        prog.progress((i + 1) / len(rounds),
                      text=f"Round {i + 1}/{len(rounds)} "
                           f"(tag {rnd.get('tag', '?')})")
        if req_delay:
            time.sleep(req_delay)
    prog.empty()
    if failed:
        st.warning(f"{len(failed)} round(s) failed to fetch and were skipped.")

    df = fixes_to_df(all_fixes, meta)
    if df.empty:
        st.warning("No usable fixes with coordinates were returned.")
        st.stop()
    st.session_state["df"] = df
    st.session_state["n_rounds"] = len(rounds)

# ---------------------------------------------------------------- analysis UI
df = st.session_state.get("df")
if df is None:
    st.info("⬅️ Enter your connection details and click **Fetch rounds & "
            "fixes** to begin. Your token stays in this browser session only.")
    st.stop()

st.success(
    f"Loaded **{len(df):,} fixes** across **{df['round_id'].nunique()}** "
    f"rounds ({df['tag'].nunique()} tags)."
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Median diff", f"{df['diff_s'].median():.0f} s")
c2.metric("95th pct diff", f"{df['diff_s'].quantile(0.95):.0f} s")
c3.metric("Max diff", f"{df['diff_s'].max():.0f} s")
c4.metric("Fixes with diff > 10 s",
          f"{(df['diff_s'] > 10).sum():,}")

st.divider()

# ------- controls
left, right = st.columns([1, 3])
with left:
    st.subheader("Heatmap settings")
    metric = st.radio(
        "Signal metric",
        ["Diff (received − recorded)", "Interval (gap between fixes)"],
        help="Diff shows transmission delay; Interval shows recording gaps. "
             "Both spike where the device loses signal.",
    )
    metric_col = "diff_s" if metric.startswith("Diff") else "interval_s"

    default_thresh = 5 if metric_col == "diff_s" else 40
    thresh = st.slider(
        "Only include fixes where metric ≥ (s)",
        0, 300, default_thresh,
        help="Filters out healthy fixes so the heatmap highlights problem "
             "areas instead of the whole cart path.",
    )
    spread = st.checkbox(
        "Spread weight along segment from previous fix",
        value=True,
        help="Devices don't buffer, so a delayed fix means the outage "
             "happened somewhere between the previous fix and this one. "
             "This interpolates the weight along that line.",
    )
    log_weight = st.checkbox(
        "Log-scale weights", value=True,
        help="Stops one giant outage from washing out everything else.",
    )
    radius = st.slider("Heat radius (px)", 5, 40, 15)
    blur = st.slider("Heat blur (px)", 5, 40, 12)
    show_markers = st.checkbox("Show worst fixes as clickable markers",
                               value=True)
    n_markers = st.slider("Number of worst-fix markers", 10, 200, 50)

    tags = sorted(df["tag"].dropna().unique(), key=str)
    sel_tags = st.multiselect("Filter by tag", tags, default=tags)

# ------- filtered data
fdf = df[df["tag"].isin(sel_tags)].copy()
bad = fdf[fdf[metric_col] >= thresh].dropna(subset=[metric_col])

with left:
    st.metric("Fixes in heatmap", f"{len(bad):,}")


def _weight(v: float) -> float:
    return math.log1p(v) if log_weight else v


# ------- build heat points (optionally interpolated along the outage segment)
heat_points = []
for _, r in bad.iterrows():
    w = _weight(r[metric_col])
    if spread and pd.notna(r["prev_lat"]) and pd.notna(r["prev_lon"]):
        steps = 6
        for k in range(steps + 1):
            t = k / steps
            heat_points.append([
                r["prev_lat"] + (r["lat"] - r["prev_lat"]) * t,
                r["prev_lon"] + (r["lon"] - r["prev_lon"]) * t,
                w / (steps + 1),
            ])
    else:
        heat_points.append([r["lat"], r["lon"], w])

# ------- map
with right:
    center = [fdf["lat"].mean(), fdf["lon"].mean()]
    m = folium.Map(location=center, zoom_start=16, max_zoom=20,
                   tiles=None, control_scale=True)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/"
              "World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri — World Imagery",
        name="Satellite",
        max_zoom=20,
    ).add_to(m)

    # faint layer of ALL fixes for context (coverage footprint)
    ctx = folium.FeatureGroup(name="All fixes (context)", show=False)
    for _, r in fdf.sample(min(len(fdf), 4000), random_state=1).iterrows():
        folium.CircleMarker([r["lat"], r["lon"]], radius=1, weight=0,
                            fill=True, fill_opacity=0.25,
                            fill_color=TM_GREEN).add_to(ctx)
    ctx.add_to(m)

    if heat_points:
        # Gradient follows Tagmarshal color symbolism:
        # green = on pace/good → yellow → orange = delayed → red = worst
        HeatMap(
            heat_points, name=f"Signal heatmap ({metric_col})",
            radius=radius, blur=blur, min_opacity=0.25, max_zoom=19,
            gradient={0.25: TM_GREEN, 0.55: TM_YELLOW,
                      0.8: TM_ORANGE, 1.0: TM_RED},
        ).add_to(m)

    if show_markers and not bad.empty:
        worst = bad.nlargest(n_markers, metric_col)
        mk = folium.FeatureGroup(name="Worst fixes")
        for _, r in worst.iterrows():
            folium.CircleMarker(
                [r["lat"], r["lon"]], radius=5, color=TM_RED,
                fill=True, fill_opacity=0.85,
                popup=folium.Popup(
                    f"<b>{r['location']}</b><br>"
                    f"Tag {r['tag']} — round {r['round_id'][:8]}…<br>"
                    f"Diff: {r['diff_s']:.0f}s | "
                    f"Interval: {'' if pd.isna(r['interval_s']) else f'{r.interval_s:.0f}s'}<br>"
                    f"Recorded: {r['recorded']}",
                    max_width=260),
            ).add_to(mk)
        mk.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    st_folium(m, height=650, use_container_width=True,
              returned_objects=[])

st.divider()

# ------- problem-area tables
st.subheader("Worst areas by course location")
loc = (fdf.dropna(subset=["diff_s"])
       .groupby("location")
       .agg(fixes=("fix_id", "count"),
            avg_diff_s=("diff_s", "mean"),
            p95_diff_s=("diff_s", lambda s: s.quantile(0.95)),
            max_diff_s=("diff_s", "max"),
            delayed_fixes=("diff_s", lambda s: (s >= thresh).sum()))
       .sort_values("p95_diff_s", ascending=False)
       .round(1))
st.dataframe(loc, use_container_width=True)

with st.expander("Per-round summary"):
    rd = (fdf.groupby(["round_id", "tag", "device_id"])
          .agg(fixes=("fix_id", "count"),
               avg_diff_s=("diff_s", "mean"),
               max_diff_s=("diff_s", "max"),
               max_interval_s=("interval_s", "max"))
          .sort_values("max_diff_s", ascending=False)
          .round(1))
    st.dataframe(rd, use_container_width=True)

st.download_button(
    "⬇️ Download combined fixes CSV",
    df.to_csv(index=False).encode(),
    file_name="all_round_fixes.csv",
    mime="text/csv",
)
