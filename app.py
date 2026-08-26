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
    initial_sidebar_state="expanded",
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

/* Hide Streamlit chrome: menu, footer badge, deploy/manage buttons —
   but NOT the sidebar open/close arrow */
#MainMenu, footer,
[data-testid="stStatusWidget"], .stAppDeployButton,
[data-testid="stAppDeployButton"], [data-testid="manage-app-button"],
a[href*="streamlit.io/cloud"], .viewerBadge_container__r5tak,
[class*="viewerBadge"] {
    visibility: hidden !important;
    display: none !important;
}
/* Always keep the sidebar toggle arrow visible and clickable */
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"],
[data-testid="stExpandSidebarButton"] {
    visibility: visible !important;
    display: flex !important;
    z-index: 999999 !important;
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
        "Max rounds to fetch", min_value=1, max_value=5000, value=200,
        step=50,
        help="Safety cap — each round is one API call for its fixes. "
             "A few hundred is fine; several thousand will take a while.",
    )
    if max_rounds > 800:
        st.caption(
            f"⏱️ ~{max_rounds * 0.35 / 60:.0f}–{max_rounds * 0.9 / 60:.0f} min "
            "to fetch at this size. Keep the tab open while it runs."
        )
    req_delay = st.slider(
        "Delay between requests (s)", 0.0, 2.0, 0.15, 0.05,
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
    rounds, page, per_page = [], 1, 200
    while len(rounds) < cap and page <= 200:
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
        # Hole number pulled out of labels like "Hole 7 Fairway" for grouping
        df["hole"] = pd.to_numeric(
            df["location"].str.extract(r"Hole\s*(\d+)", expand=False),
            errors="coerce")
        df["hour"] = df["recorded"].apply(
            lambda t: t.hour if pd.notna(t) and hasattr(t, "hour") else None)
        df["date"] = df["recorded"].apply(
            lambda t: t.date() if pd.notna(t) and hasattr(t, "date") else None)
        df["tag_num"] = pd.to_numeric(df["tag"], errors="coerce")
    return df


def sort_tags(values) -> list:
    """Tags in true numeric order (1, 2, 10 — not 1, 10, 2)."""
    def key(v):
        try:
            return (0, float(str(v).strip()), "")
        except (TypeError, ValueError):
            return (1, 0.0, str(v))
    return sorted(values, key=key)


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


def fmt_dur(seconds) -> str:
    """Seconds → compact human duration."""
    if seconds is None or pd.isna(seconds):
        return "—"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


# The normal recording cadence, inferred from the data itself. Anything
# well above this is the device having gone quiet, not a design choice.
_iv = df["interval_s"].dropna()
NOMINAL_IV = float(_iv.median()) if len(_iv) else 25.0
OUTAGE_IV = max(NOMINAL_IV * 3, NOMINAL_IV + 30)   # gap = lost signal
outages_all = df[df["interval_s"] >= OUTAGE_IV]
lost_time_all = float((outages_all["interval_s"] - NOMINAL_IV).sum())
span_s = float(df["interval_s"].sum()) or 1.0

m1, m2, m3, m4, m5, m6 = st.columns(6)
m1.metric("Median diff", f"{df['diff_s'].median():.0f}s")
m2.metric("95th pct diff", f"{df['diff_s'].quantile(0.95):.0f}s")
m3.metric("Worst diff", fmt_dur(df["diff_s"].max()))
m4.metric("Outage events", f"{len(outages_all):,}",
          help=f"Gaps ≥ {OUTAGE_IV:.0f}s between fixes "
               f"(normal cadence is ~{NOMINAL_IV:.0f}s).")
m5.metric("Total time lost", fmt_dur(lost_time_all),
          help="Sum of every gap beyond the normal recording interval.")
m6.metric("Coverage health", f"{100 * (1 - lost_time_all / span_s):.1f}%",
          help="Share of tracked time the devices were reporting normally.")

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
    # One control instead of separate radius + blur: spread sets the zone
    # size and blur is derived from it (tight blur = sharper, more vibrant).
    spread_px = st.slider(
        "Hot zone size", 5, 45, 18,
        help="How far each problem fix bleeds across the map. Smaller = "
             "pinpoint dead spots, larger = broad problem areas.",
    )
    intensity = st.slider(
        "Intensity", 0.5, 3.0, 1.6, 0.1,
        help="Boosts the colour of moderate problems so they don't wash out "
             "next to the single worst outage.",
    )
    radius = spread_px
    blur = max(3, int(spread_px * 0.40))

    show_markers = st.checkbox("Show worst fixes as clickable markers",
                               value=True)
    n_markers = st.slider("Number of worst-fix markers", 10, 200, 50)
    show_lines = st.checkbox(
        "Show outage lines (last good fix → delayed fix)",
        value=True,
        help="Draws a line from the last fix before the delay to the first "
             "delayed fix — the path along which the device had no signal. "
             "Line color shows severity.",
    )

    # ---- tag filter: pick as many as you like, map only redraws on Apply
    all_tags = sort_tags(df["tag"].dropna().unique())
    if "sel_tags" not in st.session_state:
        st.session_state["sel_tags"] = all_tags
    # drop any tags that no longer exist after a fresh fetch
    st.session_state["sel_tags"] = [t for t in st.session_state["sel_tags"]
                                    if t in all_tags] or all_tags

    with st.form("tag_filter", border=True):
        st.markdown("**Filter by tag**")
        picked = st.multiselect(
            "Tags", all_tags, default=st.session_state["sel_tags"],
            label_visibility="collapsed",
            help="Select as many tags as you want — the map only redraws "
                 "when you hit Apply.",
        )
        fa, fb = st.columns(2)
        applied = fa.form_submit_button("✅ Apply tags", type="primary",
                                        use_container_width=True)
        reset = fb.form_submit_button("↺ All tags",
                                      use_container_width=True)
    if applied:
        st.session_state["sel_tags"] = picked or all_tags
    if reset:
        st.session_state["sel_tags"] = all_tags

    sel_tags = st.session_state["sel_tags"]
    st.caption(f"Showing {len(sel_tags)} of {len(all_tags)} tags")

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

# Stretch weights across the full colour range, then apply the intensity
# curve. Normalising against the max alone would leave everything bunched
# at the top (all red) whenever the mildest problem is already severe.
if heat_points:
    ws = [p[2] for p in heat_points]
    wmin, wmax = min(ws), max(ws)
    rng = (wmax - wmin) or 1.0
    gamma = 1.0 / max(intensity, 0.1)
    heat_points = [
        [p[0], p[1], 0.12 + 0.88 * min(1.0, ((p[2] - wmin) / rng) ** gamma)]
        for p in heat_points
    ]

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
            radius=radius, blur=blur,
            min_opacity=min(0.85, 0.30 * intensity),
            max_zoom=19,
            gradient={0.10: "#2E7D32", 0.30: TM_GREEN, 0.50: TM_YELLOW,
                      0.70: TM_ORANGE, 0.88: TM_RED, 1.0: "#A04B9D"},
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

    if show_lines and not bad.empty:
        # Line from last fix BEFORE the delay to the first delayed fix —
        # the stretch where the device was silent. Colored by severity.
        seg = bad.dropna(subset=["prev_lat", "prev_lon"])
        seg = seg.nlargest(min(len(seg), 400), metric_col)
        if not seg.empty:
            vmax = float(seg[metric_col].max()) or 1.0
            ln = folium.FeatureGroup(name="Outage lines")
            for _, r in seg.iterrows():
                frac = r[metric_col] / vmax
                color = (TM_RED if frac >= 0.66
                         else TM_ORANGE if frac >= 0.33 else TM_YELLOW)
                folium.PolyLine(
                    [[r["prev_lat"], r["prev_lon"]], [r["lat"], r["lon"]]],
                    color=color, weight=3, opacity=0.9,
                    popup=folium.Popup(
                        f"<b>Signal gap — {r['location']}</b><br>"
                        f"Tag {r['tag']} — round {r['round_id'][:8]}…<br>"
                        f"Diff: {r['diff_s']:.0f}s | Interval: "
                        f"{'' if pd.isna(r['interval_s']) else f'{r.interval_s:.0f}s'}<br>"
                        f"Last good fix → delayed fix at {r['recorded']}",
                        max_width=280),
                ).add_to(ln)
                # small dots at each end: green = last good, red = delayed
                folium.CircleMarker([r["prev_lat"], r["prev_lon"]], radius=3,
                                    color=TM_GREEN, fill=True,
                                    fill_opacity=1).add_to(ln)
                folium.CircleMarker([r["lat"], r["lon"]], radius=3,
                                    color=color, fill=True,
                                    fill_opacity=1).add_to(ln)
            ln.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    st_folium(m, height=650, use_container_width=True,
              returned_objects=[])

st.divider()

# =================================================================
#                            ANALYTICS
# =================================================================
st.subheader("Analytics")

# Outage events within the current filter, used across several tabs
out = fdf[fdf["interval_s"] >= OUTAGE_IV].copy()
out["lost_s"] = out["interval_s"] - NOMINAL_IV

t_hole, t_loc, t_dev, t_time, t_out, t_dist = st.tabs(
    ["By hole", "By location", "By device / tag", "By time of day",
     "Outage log", "Distribution"])

# ---------------------------------------------------------- by hole
with t_hole:
    hs = fdf.dropna(subset=["hole"]).copy()
    if hs.empty:
        st.info("No hole information in these fixes.")
    else:
        oh = out.dropna(subset=["hole"])
        hole_tbl = (hs.groupby("hole")
                    .agg(fixes=("fix_id", "count"),
                         median_diff_s=("diff_s", "median"),
                         p95_diff_s=("diff_s", lambda s: s.quantile(0.95)),
                         max_diff_s=("diff_s", "max"),
                         max_gap_s=("interval_s", "max")))
        lost_by_hole = oh.groupby("hole")["lost_s"].sum()
        ev_by_hole = oh.groupby("hole")["fix_id"].count()
        hole_tbl["outages"] = ev_by_hole.reindex(hole_tbl.index).fillna(0)
        hole_tbl["time_lost_s"] = (lost_by_hole.reindex(hole_tbl.index)
                                   .fillna(0))
        # Severity: lost seconds per hour of play on that hole
        hrs = hs.groupby("hole")["interval_s"].sum() / 3600.0
        hole_tbl["lost_s_per_hr"] = (hole_tbl["time_lost_s"]
                                     / hrs.reindex(hole_tbl.index)
                                     .replace(0, float("nan")))
        hole_tbl = hole_tbl.round(1)
        hole_tbl.index = hole_tbl.index.astype(int)
        hole_tbl = hole_tbl.sort_index()

        st.markdown("**Signal loss per hole** — seconds lost per hour played "
                    "(normalises for holes that simply see more traffic)")
        st.bar_chart(hole_tbl["lost_s_per_hr"], color=TM_RED, height=260)

        worst = hole_tbl["lost_s_per_hr"].dropna()
        if not worst.empty:
            top = worst.nlargest(3)
            st.markdown("Worst holes: " + " · ".join(
                f"**Hole {int(h)}** ({v:.0f}s/hr)" for h, v in top.items()))
        st.dataframe(hole_tbl.sort_values("lost_s_per_hr", ascending=False),
                     use_container_width=True)

# ------------------------------------------------------ by location
with t_loc:
    loc = (fdf.dropna(subset=["diff_s"])
           .groupby("location")
           .agg(fixes=("fix_id", "count"),
                median_diff_s=("diff_s", "median"),
                p95_diff_s=("diff_s", lambda s: s.quantile(0.95)),
                max_diff_s=("diff_s", "max"),
                delayed_fixes=("diff_s", lambda s: (s >= thresh).sum())))
    loc["pct_delayed"] = (100 * loc["delayed_fixes"] / loc["fixes"])
    lost_by_loc = out.groupby("location")["lost_s"].sum()
    loc["time_lost_s"] = lost_by_loc.reindex(loc.index).fillna(0)
    loc = loc.round(1).sort_values("time_lost_s", ascending=False)
    st.markdown("**Where the time is being lost** (top 15 spots)")
    st.bar_chart(loc["time_lost_s"].head(15), color=TM_ORANGE, height=280)
    st.dataframe(loc, use_container_width=True)

# ----------------------------------------------------- by device/tag
with t_dev:
    st.caption("A tag that is bad everywhere points at the device or SIM; "
               "a tag that is only bad where others are too points at "
               "course coverage.")
    dev = (fdf.groupby(["tag", "device_id"])
           .agg(rounds=("round_id", "nunique"),
                fixes=("fix_id", "count"),
                median_diff_s=("diff_s", "median"),
                p95_diff_s=("diff_s", lambda s: s.quantile(0.95)),
                max_diff_s=("diff_s", "max"),
                max_gap_s=("interval_s", "max"))
           .reset_index())
    lost_by_tag = out.groupby("tag")["lost_s"].sum()
    ev_by_tag = out.groupby("tag")["fix_id"].count()
    dev["outages"] = dev["tag"].map(ev_by_tag).fillna(0)
    dev["time_lost_s"] = dev["tag"].map(lost_by_tag).fillna(0)
    played = fdf.groupby("tag")["interval_s"].sum() / 3600.0
    dev["lost_s_per_hr"] = (dev["time_lost_s"]
                            / dev["tag"].map(played).replace(0, float("nan")))
    dev["_k"] = pd.to_numeric(dev["tag"], errors="coerce")
    dev = dev.sort_values(["_k", "tag"]).drop(columns="_k").round(1)
    st.dataframe(dev.set_index("tag"), use_container_width=True)

    fleet_med = dev["lost_s_per_hr"].median()
    if pd.notna(fleet_med) and fleet_med > 0:
        flagged = dev[dev["lost_s_per_hr"] > 2.5 * fleet_med]
        if not flagged.empty:
            st.warning(
                "Tags losing far more time than the fleet median "
                f"({fleet_med:.0f}s/hr) — worth checking the hardware: "
                + ", ".join(f"**{t}**" for t in flagged["tag"].head(10)))

# ---------------------------------------------------- by time of day
with t_time:
    hrs = fdf.dropna(subset=["hour"]).copy()
    if hrs.empty:
        st.info("No timestamps available for a time-of-day breakdown.")
    else:
        by_hr = (hrs.groupby("hour")
                 .agg(fixes=("fix_id", "count"),
                      median_diff_s=("diff_s", "median"),
                      p95_diff_s=("diff_s", lambda s: s.quantile(0.95))))
        lost_hr = out.dropna(subset=["hour"]).groupby("hour")["lost_s"].sum()
        by_hr["time_lost_s"] = lost_hr.reindex(by_hr.index).fillna(0)
        by_hr.index = by_hr.index.astype(int)
        st.markdown("**95th-percentile delay by hour** — a rising curve "
                    "through the day suggests network congestion rather "
                    "than course geography")
        st.line_chart(by_hr["p95_diff_s"], color=TM_YELLOW, height=260)
        st.dataframe(by_hr.round(1), use_container_width=True)

        if fdf["date"].nunique() > 1:
            st.markdown("**Time lost per day**")
            per_day = (out.dropna(subset=["date"])
                       .groupby("date")["lost_s"].sum())
            st.bar_chart(per_day, color=TM_RED, height=240)

# -------------------------------------------------------- outage log
with t_out:
    st.caption(f"Every gap of {OUTAGE_IV:.0f}s or more between consecutive "
               f"fixes (normal cadence ≈ {NOMINAL_IV:.0f}s).")
    if out.empty:
        st.success("No outages over the threshold in this selection.")
    else:
        log = (out.sort_values("lost_s", ascending=False)
               [["recorded", "tag", "location", "interval_s", "diff_s",
                 "lat", "lon", "round_id"]]
               .rename(columns={"interval_s": "gap_s",
                                "lost_s": "time_lost_s"})
               .head(500).round(1))
        st.dataframe(log, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇️ Download outage log CSV",
            out.to_csv(index=False).encode(),
            file_name="outage_log.csv", mime="text/csv")

# ------------------------------------------------------ distribution
with t_dist:
    d = fdf["diff_s"].dropna()
    if d.empty:
        st.info("No diff values to chart.")
    else:
        bins = [0, 2, 5, 10, 20, 30, 60, 120, 300, 600, float("inf")]
        labels = ["0–2s", "2–5s", "5–10s", "10–20s", "20–30s", "30–60s",
                  "1–2m", "2–5m", "5–10m", "10m+"]
        cut = pd.cut(d, bins=bins, labels=labels, right=False)
        st.markdown("**How many fixes fall into each delay band**")
        st.bar_chart(cut.value_counts().reindex(labels).fillna(0),
                     color=TM_GREEN, height=280)
        q = d.quantile([0.5, 0.75, 0.9, 0.95, 0.99]).round(1)
        q.index = ["50th", "75th", "90th", "95th", "99th"]
        cq1, cq2 = st.columns([1, 2])
        cq1.dataframe(q.rename("diff_s"), use_container_width=True)
        cq2.caption(
            "A long tail with a healthy median means coverage is fine "
            "except in specific dead zones — check the map and the "
            "per-hole tab. A high median means a fleet-wide or carrier "
            "problem instead."
        )

st.divider()
d1, d2 = st.columns(2)
d1.download_button(
    "⬇️ Download all fixes CSV",
    df.to_csv(index=False).encode(),
    file_name="all_round_fixes.csv",
    mime="text/csv", use_container_width=True,
)
d2.download_button(
    "⬇️ Download filtered fixes CSV",
    fdf.to_csv(index=False).encode(),
    file_name="filtered_fixes.csv",
    mime="text/csv", use_container_width=True,
)
