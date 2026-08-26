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
import altair as alt
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

    st.header("SIM data (optional)")
    st.caption(
        "The dashboard API doesn't expose SIM details. Each server/course "
        "export only covers its own SIMs, so upload as many as you like — "
        "IMEIs are globally unique, so they merge into one fleet-wide map. "
        "Build it once and re-upload the combined file next time."
    )
    sim_files = st.file_uploader(
        "SIM exports", type=["csv", "xlsx", "xls"],
        accept_multiple_files=True, label_visibility="collapsed")

    IMEI_RE = r"^\d{14,16}$"
    ICCID_RE = r"^\d{18,22}$"
    PROV_WORDS = ("provider", "carrier", "network", "operator", "sim",
                  "apn", "mno")

    def _read_any(f) -> pd.DataFrame:
        if f.name.lower().endswith((".xlsx", ".xls")):
            return pd.read_excel(f, dtype=str).fillna("")
        return pd.read_csv(f, dtype=str).fillna("")

    def _clean_num(s: pd.Series) -> pd.Series:
        # Excel loves turning IMEIs into 8.6e14 or adding a trailing .0
        return (s.astype(str).str.strip()
                .str.replace(r"\.0$", "", regex=True)
                .str.replace(r"[^\d]", "", regex=True))

    def _find_col(dfx: pd.DataFrame, pattern: str):
        """Column whose values mostly look like the pattern (content, not
        just header text — export headers differ between servers)."""
        best, best_hit = None, 0.0
        for c in dfx.columns:
            v = _clean_num(dfx[c])
            v = v[v != ""]
            if len(v) < max(3, 0.2 * len(dfx)):
                continue
            hit = v.str.match(pattern).mean()
            if hit > 0.5 and hit > best_hit:
                best, best_hit = c, hit
        return best

    def _find_provider(dfx: pd.DataFrame):
        for c in dfx.columns:
            if any(w in c.lower().replace(" ", "").replace("_", "")
                   for w in PROV_WORDS):
                vals = dfx[c].astype(str).str.strip()
                vals = vals[vals != ""]
                # a provider column is text with few distinct values
                if len(vals) and not vals.str.match(r"^\d+$").all() \
                        and vals.nunique() <= max(12, 0.3 * len(vals)):
                    return c
        return None

    frames, notes = [], []
    for f in sim_files or []:
        try:
            raw = _read_any(f)
        except Exception as e:                    # noqa: BLE001
            st.error(f"{f.name}: couldn't read ({e})")
            continue
        if raw.empty:
            continue
        imei_c = _find_col(raw, IMEI_RE)
        prov_c = _find_provider(raw)
        iccid_c = _find_col(raw, ICCID_RE)
        if imei_c is None:
            with st.expander(f"⚠️ {f.name} — pick columns manually"):
                cols = list(raw.columns)
                imei_c = st.selectbox(f"IMEI column ({f.name})", cols,
                                      key=f"i_{f.name}")
                prov_c = st.selectbox(f"Provider column ({f.name})", cols,
                                      key=f"p_{f.name}")
        part = pd.DataFrame({"_imei": _clean_num(raw[imei_c])})
        if prov_c is not None:
            part["sim_provider"] = (raw[prov_c].astype(str).str.strip()
                                    .replace("", "Unknown"))
        elif iccid_c is not None:
            # No provider column — group by ICCID issuer prefix so fleets
            # still separate, even without proper names.
            part["sim_provider"] = ("ICCID "
                                    + _clean_num(raw[iccid_c]).str[:7])
            notes.append(f"{f.name}: no provider column, grouped by ICCID "
                         "prefix")
        else:
            part["sim_provider"] = "Unknown"
        part["sim_source"] = f.name
        part = part[part["_imei"] != ""]
        frames.append(part)
        notes.append(f"{f.name}: {len(part):,} SIMs"
                     + (f" · {part['sim_provider'].nunique()} providers"
                        if prov_c is not None else ""))

    sim_map = None
    if frames:
        sim_map = pd.concat(frames, ignore_index=True)
        dupes = int(sim_map.duplicated("_imei").sum())
        sim_map = sim_map.drop_duplicates("_imei", keep="last")
        st.success(
            f"**{len(sim_map):,} SIMs** from {len(frames)} file(s) · "
            f"{sim_map['sim_provider'].nunique()} providers"
            + (f" · {dupes} duplicate IMEI(s) merged" if dupes else ""))
        for n in notes:
            st.caption(n)
        st.download_button(
            "⬇️ Save combined SIM list",
            sim_map.rename(columns={"_imei": "IMEI"})
            .to_csv(index=False).encode(),
            file_name="sim_master_list.csv", mime="text/csv",
            use_container_width=True,
            help="Upload just this one file next time instead of every "
                 "server export.")
    st.session_state["sim_map"] = (
        sim_map[["_imei", "sim_provider"]] if sim_map is not None else None)
    st.session_state["sim_src"] = sim_map


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

# ---- join SIM provider on IMEI, if a SIM export was supplied
sim_map = st.session_state.get("sim_map")
HAS_SIM = False
if sim_map is not None and not sim_map.empty:
    df = df.drop(columns=["sim_provider"], errors="ignore")
    df["_imei"] = (df["device_id"].astype(str).str.strip()
                   .str.replace(r"\.0$", "", regex=True)
                   .str.replace(r"[^\d]", "", regex=True))
    df = df.merge(sim_map, on="_imei", how="left").drop(columns="_imei")
    df["sim_provider"] = df["sim_provider"].fillna("Unmatched")
    matched = 100 * (df["sim_provider"] != "Unmatched").mean()
    HAS_SIM = True
    if matched == 0:
        st.warning(
            "None of the uploaded SIM exports contain this course's IMEIs — "
            "you'll need the export from the server this course sits on. "
            f"Example device here: `{df['device_id'].dropna().iloc[0]}`"
            if df["device_id"].notna().any() else "")
    elif matched < 100:
        missing = (df.loc[df["sim_provider"] == "Unmatched", "tag"]
                   .dropna().unique())
        st.caption(
            f"SIM data matched {matched:.0f}% of fixes by IMEI. "
            f"{len(missing)} tag(s) unmatched — add that server's export "
            "to cover them.")


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


# ---- what counts as a healthy fix (your standard, not an arbitrary one)
IDEAL_S = 2.0      # 1–2s is the target
OK_S = 5.0         # under 5s is no cause for concern
MAX_S = 120.0      # the most you'll tolerate before it's a real problem
NOMINAL_IV = float(df["interval_s"].dropna().median() or 25.0)
OUTAGE_IV = max(NOMINAL_IV * 3, NOMINAL_IV + 30)   # a real signal gap


def health_pct(series) -> float:
    """Share of fixes delivered inside the acceptable delay."""
    s = series.dropna()
    return 100.0 * (s <= OK_S).mean() if len(s) else float("nan")


def within_max(series) -> float:
    """Share of fixes inside the maximum tolerated delay."""
    s = series.dropna()
    return 100.0 * (s <= MAX_S).mean() if len(s) else float("nan")


def health_label(pct: float) -> str:
    if pd.isna(pct):
        return "—"
    return ("Excellent" if pct >= 99 else "Good" if pct >= 95
            else "Fair" if pct >= 90 else "Poor")


def bar_labeled(data: pd.DataFrame, x: str, y: str, *, x_title="",
                y_title="", sort=None, color=TM_RED, log=False,
                height=300, fmt=",.0f", label_angle=0):
    """Bar chart with the value printed above each bar and readable
    horizontal axis labels. Optional symlog scale so a bar of 8,000 doesn't
    flatten a bar of 10 into nothing."""
    scale = alt.Scale(type="symlog") if log else alt.Scale(type="linear")
    enc_x = alt.X(f"{x}:N", sort=sort, title=x_title,
                  axis=alt.Axis(labelAngle=label_angle, labelLimit=200))
    base = alt.Chart(data)
    bars = base.mark_bar(color=color, cornerRadiusTopLeft=2,
                         cornerRadiusTopRight=2).encode(
        x=enc_x,
        y=alt.Y(f"{y}:Q", title=y_title, scale=scale),
        tooltip=list(data.columns),
    )
    text = base.mark_text(dy=-7, color="#F5F5F5", fontSize=11,
                          fontWeight="bold").encode(
        x=enc_x, y=alt.Y(f"{y}:Q", scale=scale),
        text=alt.Text(f"{y}:Q", format=fmt),
    )
    return (bars + text).properties(height=height)


outages_all = df[df["interval_s"] >= OUTAGE_IV]
overall_health = health_pct(df["diff_s"])
pct_within_max = within_max(df["diff_s"])
over_max = int((df["diff_s"] > MAX_S).sum())
pct_ideal = 100.0 * (df["diff_s"].dropna() <= IDEAL_S).mean()

m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
m1.metric("Median diff", f"{df['diff_s'].median():.0f}s",
          help=f"Target is {IDEAL_S:.0f}s or under.")
m2.metric("95th pct diff", f"{df['diff_s'].quantile(0.95):.0f}s")
m3.metric("Worst diff", fmt_dur(df["diff_s"].max()))
m4.metric(f"Within {IDEAL_S:.0f}s (ideal)", f"{pct_ideal:.1f}%")
m5.metric("Coverage health", f"{overall_health:.1f}%",
          delta=health_label(overall_health), delta_color="off",
          help=f"Share of fixes delivered within {OK_S:.0f}s. Anything "
               f"under that is no cause for concern; {IDEAL_S:.0f}s or "
               "less is ideal.")
m6.metric(f"Within {MAX_S:.0f}s (max allowed)", f"{pct_within_max:.1f}%",
          help=f"{MAX_S:.0f}s is the most you tolerate without concern. "
               "This is the number to watch for genuine problems.")
m7.metric(f"Over {MAX_S:.0f}s", f"{over_max:,}",
          help="Fixes that breached the maximum allowed delay.")

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

    # Three slider ranges, because a course with 8s delays and one with
    # 40-minute blackouts need very different resolution on this control.
    SCALES = {
        "Good": {"max": 300, "step": 1, "def_diff": 5, "def_iv": 40,
                 "note": "Fine detail up to 5 min — normal courses."},
        "Average": {"max": 1000, "step": 5, "def_diff": 30, "def_iv": 60,
                    "note": "Up to ~17 min — patchy coverage."},
        "Bad": {"max": 10000, "step": 50, "def_diff": 150, "def_iv": 300,
                "note": "Up to ~2¾ h — severe blackouts or stalled "
                        "devices."},
    }
    scale_name = st.radio(
        "Tracking quality range", list(SCALES), horizontal=True, index=0,
        help="Sets how far the threshold slider below reaches. Start on "
             "Good; move up only if the worst delays are off the scale.",
    )
    sc = SCALES[scale_name]
    # Default must sit on a step boundary or the slider snaps oddly
    raw_def = sc["def_diff"] if metric_col == "diff_s" else sc["def_iv"]
    default_thresh = int(round(raw_def / sc["step"]) * sc["step"])
    worst = float(df[metric_col].max() or 0)
    thresh = st.slider(
        f"Only include fixes where metric ≥ (s) — up to {sc['max']:,}s",
        0, sc["max"], min(default_thresh, sc["max"]), step=sc["step"],
        help="Filters out healthy fixes so the heatmap highlights problem "
             "areas instead of the whole cart path. " + sc["note"],
    )
    if worst > sc["max"]:
        st.caption(f"⚠️ Worst value here is {worst:,.0f}s — beyond this "
                   "range. Switch to "
                   f"**{'Average' if worst <= 1000 else 'Bad'}** to reach it.")

    with st.expander("🎛️ Map display settings", expanded=False):
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
        # One control instead of separate radius + blur: spread sets the
        # zone size, blur derives from it (tight blur = sharper, vibrant).
        spread_px = st.slider(
            "Hot zone size", 5, 45, 18,
            help="How far each problem fix bleeds across the map. Smaller = "
                 "pinpoint dead spots, larger = broad problem areas.",
        )
        intensity = st.slider(
            "Intensity", 0.5, 3.0, 1.6, 0.1,
            help="Boosts the colour of moderate problems so they don't wash "
                 "out next to the single worst outage.",
        )
        show_markers = st.checkbox("Show worst fixes as clickable markers",
                                   value=True)
        n_markers = st.slider("Number of worst-fix markers", 10, 200, 50)
        show_lines = st.checkbox(
            "Show outage lines (last good fix → delayed fix)",
            value=True,
            help="Draws a line from the last fix before the delay to the "
                 "first delayed fix — the path along which the device had "
                 "no signal. Line color shows severity.",
        )
    radius = spread_px
    blur = max(3, int(spread_px * 0.40))

    # ---- tag / SIM filter: pick freely, map only redraws on Apply
    all_tags = sort_tags(df["tag"].dropna().unique())
    if "sel_tags" not in st.session_state:
        st.session_state["sel_tags"] = all_tags
    # drop any tags that no longer exist after a fresh fetch
    st.session_state["sel_tags"] = [t for t in st.session_state["sel_tags"]
                                    if t in all_tags] or all_tags

    all_sims = (sorted(df["sim_provider"].dropna().unique())
                if HAS_SIM else [])
    if HAS_SIM:
        keep = [s for s in st.session_state.get("sel_sims", all_sims)
                if s in all_sims]
        st.session_state["sel_sims"] = keep or all_sims

    with st.form("tag_filter", border=True):
        if HAS_SIM:
            st.markdown("**Filter by SIM provider**")
            picked_sims = st.multiselect(
                "SIM providers", all_sims,
                default=st.session_state["sel_sims"],
                label_visibility="collapsed",
                help="Compare fleets — e.g. show only Onomondo tags.")
            sim_only = st.checkbox(
                "Limit the tag list to those SIMs", value=True,
                help="Tags not on the selected SIMs are excluded even if "
                     "ticked below.")
        st.markdown("**Filter by tag**")
        picked = st.multiselect(
            "Tags", all_tags, default=st.session_state["sel_tags"],
            label_visibility="collapsed",
            help="Select as many tags as you want — the map only redraws "
                 "when you hit Apply.",
        )
        fa, fb = st.columns(2)
        applied = fa.form_submit_button("✅ Apply filters", type="primary",
                                        use_container_width=True)
        reset = fb.form_submit_button("↺ Show all",
                                      use_container_width=True)
    if applied:
        st.session_state["sel_tags"] = picked or all_tags
        if HAS_SIM:
            st.session_state["sel_sims"] = picked_sims or all_sims
            st.session_state["sim_only"] = sim_only
    if reset:
        st.session_state["sel_tags"] = all_tags
        if HAS_SIM:
            st.session_state["sel_sims"] = all_sims

    sel_tags = st.session_state["sel_tags"]
    sel_sims = st.session_state.get("sel_sims", all_sims)
    st.caption(f"Showing {len(sel_tags)} of {len(all_tags)} tags"
               + (f" · {len(sel_sims)} of {len(all_sims)} SIM providers"
                  if HAS_SIM else ""))

# ------- filtered data
fdf = df[df["tag"].isin(sel_tags)].copy()
if HAS_SIM and st.session_state.get("sim_only", True):
    fdf = fdf[fdf["sim_provider"].isin(sel_sims)]
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


def delayed_rate(s):
    """% of fixes that missed the acceptable delay."""
    s = s.dropna()
    return 100.0 * (s > OK_S).mean() if len(s) else float("nan")


# ---- focus the whole analytics section on a delay band
FOCUS = {
    "All fixes": None,
    f"Ideal (≤{IDEAL_S:.0f}s)": lambda s: s <= IDEAL_S,
    f"Fine (≤{OK_S:.0f}s)": lambda s: s <= OK_S,
    f"Delayed (>{OK_S:.0f}s)": lambda s: s > OK_S,
    f"Tolerated ({OK_S:.0f}–{MAX_S:.0f}s)":
        lambda s: (s > OK_S) & (s <= MAX_S),
    f"Over limit (>{MAX_S:.0f}s)": lambda s: s > MAX_S,
    "Custom range…": "custom",
}
A_SCALES = {"Good": (300, 1), "Average": (1000, 5), "Bad": (10000, 50)}

fc1, fc2 = st.columns([1, 2])
focus_name = fc1.selectbox(
    "Focus analytics on", list(FOCUS), index=0,
    help="Narrows every tab below to fixes in this delay band — so you can "
         "ask 'where do the really bad ones happen?' without the healthy "
         "fixes drowning them out.")
rule = FOCUS[focus_name]

if rule == "custom":
    with fc2:
        cs1, cs2 = st.columns([1, 2])
        a_scale = cs1.radio("Range", list(A_SCALES), horizontal=True,
                            index=0, key="a_scale")
        a_max, a_step = A_SCALES[a_scale]
        lo, hi = cs2.slider(
            "Delay between (s)", 0, a_max, (0, a_max), step=a_step,
            help="Only fixes whose delay falls inside this window.")
    rule = (lambda s, lo=lo, hi=hi: (s >= lo) & (s <= hi))
    focus_label = f"{lo:,}–{hi:,}s"
else:
    focus_label = focus_name

# adf = the analytics subset. fdf stays whole so we can still show what
# share of each group the focused fixes represent.
if rule is None:
    adf = fdf
else:
    adf = fdf[rule(fdf["diff_s"].fillna(-1))]

FOCUSED = rule is not None

if FOCUSED:
    n_focus, n_all = len(adf), len(fdf)
    share = 100 * n_focus / max(n_all, 1)
    if adf.empty:
        st.warning(f"No fixes fall in **{focus_label}** — widen the focus.")
        st.stop()
    f1, f2, f3, f4 = st.columns(4)
    f1.metric("Fixes in focus", f"{n_focus:,}")
    f2.metric("Share of all fixes", f"{share:.2f}%")
    f3.metric("Median in focus", f"{adf['diff_s'].median():.0f}s")
    f4.metric("Worst in focus", fmt_dur(adf["diff_s"].max()))
    st.info(f"Every tab below is limited to **{focus_label}** "
            f"({n_focus:,} of {n_all:,} fixes). Percentage columns are "
            "relative to this subset; **focus_fixes** and **pct_of_group** "
            "show the counts against the unfiltered totals.")

# Signal gaps within the current filter (used by several tabs)
out = adf[adf["interval_s"] >= OUTAGE_IV].copy()


def focus_counts(key: str) -> pd.DataFrame:
    """Focused fix count per group, plus what share of that group's
    total fixes it represents — the honest denominator."""
    tot = fdf.groupby(key)["fix_id"].count().rename("group_fixes")
    got = adf.groupby(key)["fix_id"].count().rename("focus_fixes")
    j = pd.concat([tot, got], axis=1).fillna(0)
    j["pct_of_group"] = (100 * j["focus_fixes"]
                         / j["group_fixes"].replace(0, float("nan")))
    return j.round(1)


_tab_names = ["Delay distribution", "By hole", "By location", "By round",
              "By device / tag", "By time of day", "Gap log"]
if HAS_SIM:
    _tab_names.insert(4, "By SIM")
_tabs = st.tabs(_tab_names)
_T = dict(zip(_tab_names, _tabs))
t_dist = _T["Delay distribution"]
t_hole = _T["By hole"]
t_loc = _T["By location"]
t_round = _T["By round"]
t_dev = _T["By device / tag"]
t_time = _T["By time of day"]
t_out = _T["Gap log"]
t_sim = _T.get("By SIM")

# ------------------------------------------------------ distribution
with t_dist:
    d = adf["diff_s"].dropna()
    if d.empty:
        st.info("No diff values to chart.")
    else:
        # Bands built around your standards: ≤2s ideal, ≤5s fine,
        # ≤120s tolerated, anything beyond that is a real problem.
        bins = [0, 1, 2, 5, 10, 30, 60, 120, 300, float("inf")]
        labels = ["0–1s", "1–2s", "2–5s", "5–10s", "10–30s", "30–60s",
                  "60–120s", "2–5m", "5m+"]
        grades = {"0–1s": "ideal (≤2s)", "1–2s": "ideal (≤2s)",
                  "2–5s": "fine (≤5s)"}
        cut = pd.cut(d, bins=bins, labels=labels, right=True,
                     include_lowest=True)
        counts = cut.value_counts().reindex(labels).fillna(0).astype(int)
        dist = pd.DataFrame({
            "band": labels,
            "fixes": counts.values,
            "share": (100 * counts.values / max(counts.sum(), 1)).round(2),
            "grade": [grades.get(b, "tolerated (≤120s)")
                      if b in ("5–10s", "10–30s", "30–60s", "60–120s")
                      or b in grades else "over limit (>120s)"
                      for b in labels],
        })

        cc1, cc2 = st.columns([3, 1])
        log_scale = cc2.toggle(
            "Log scale", value=True,
            help="Keeps small bands visible next to bands in the thousands.")
        cc1.markdown(
            f"**Delay bands** — bars run shortest to longest delay. "
            f"Green is inside your {OK_S:.0f}s target, yellow is still "
            f"within the {MAX_S:.0f}s limit, red has breached it.")

        scale = alt.Scale(type="symlog") if log_scale else alt.Scale()
        enc_x = alt.X("band:N", sort=labels, title="Delay band",
                      axis=alt.Axis(labelAngle=0))
        base = alt.Chart(dist)
        bars = base.mark_bar(cornerRadiusTopLeft=2,
                             cornerRadiusTopRight=2).encode(
            x=enc_x,
            y=alt.Y("fixes:Q", title="Fixes", scale=scale),
            color=alt.Color("grade:N", scale=alt.Scale(
                domain=["ideal (≤2s)", "fine (≤5s)", "tolerated (≤120s)",
                        "over limit (>120s)"],
                range=[TM_GREEN, "#B7D67A", TM_YELLOW, TM_RED]),
                legend=alt.Legend(title=None, orient="top")),
            tooltip=["band", "fixes", "share", "grade"],
        )
        text = base.mark_text(dy=-8, color="#F5F5F5", fontSize=12,
                              fontWeight="bold").encode(
            x=enc_x, y=alt.Y("fixes:Q", scale=scale),
            text=alt.Text("fixes:Q", format=","))
        st.altair_chart((bars + text).properties(height=320),
                        use_container_width=True)

        q = d.quantile([0.5, 0.75, 0.9, 0.95, 0.99]).round(1)
        q.index = ["50th (median)", "75th", "90th", "95th", "99th"]
        qq1, qq2 = st.columns([1, 2])
        qq1.dataframe(q.rename("diff (s)"), use_container_width=True)
        qq2.dataframe(dist.set_index("band"), use_container_width=True)

# ---------------------------------------------------------- by hole
with t_hole:
    hs = adf.dropna(subset=["hole"]).copy()
    if hs.empty:
        st.info("No hole information in these fixes.")
    else:
        hole_tbl = (hs.groupby("hole")
                    .agg(fixes=("fix_id", "count"),
                         median_diff_s=("diff_s", "median"),
                         p95_diff_s=("diff_s", lambda s: s.quantile(0.95)),
                         max_diff_s=("diff_s", "max"),
                         max_gap_s=("interval_s", "max"),
                         health_pct=("diff_s", health_pct),
                         within_max_pct=("diff_s", within_max),
                         pct_delayed=("diff_s", delayed_rate)))
        gaps = out.dropna(subset=["hole"]).groupby("hole")["fix_id"].count()
        hole_tbl["signal_gaps"] = (gaps.reindex(hole_tbl.index)
                                   .fillna(0).astype(int))
        if FOCUSED:
            fc = focus_counts("hole").reindex(hole_tbl.index)
            hole_tbl["focus_fixes"] = fc["focus_fixes"].fillna(0).astype(int)
            hole_tbl["pct_of_group"] = fc["pct_of_group"]
        hole_tbl = hole_tbl.round(1)
        hole_tbl.index = hole_tbl.index.astype(int)
        hole_tbl = hole_tbl.sort_index()

        ch = hole_tbl.reset_index().rename(columns={"hole": "Hole"})
        ch["Hole"] = ch["Hole"].astype(str)
        order = list(ch["Hole"])

        y_col = "pct_of_group" if FOCUSED else "pct_delayed"
        y_lbl = (f"% of hole's fixes in {focus_label}" if FOCUSED
                 else f"% of fixes over {OK_S:.0f}s")
        st.markdown(
            (f"**Share of each hole's fixes falling in {focus_label}** "
             "(holes in playing order)") if FOCUSED else
            (f"**Percentage of fixes arriving later than {OK_S:.0f}s, "
             "hole by hole** (holes in playing order)"))
        cols = ["Hole", y_col, "fixes", "p95_diff_s"]
        if FOCUSED:
            cols.insert(2, "focus_fixes")
        st.altair_chart(
            bar_labeled(ch[cols], "Hole", y_col, x_title="Hole",
                        y_title=y_lbl, sort=order, color=TM_ORANGE,
                        fmt=".1f", height=300),
            use_container_width=True)

        worst = hole_tbl[y_col].dropna().nlargest(3)
        if not worst.empty and worst.iloc[0] > 0:
            st.markdown("Worst holes: " + " · ".join(
                f"**Hole {int(h)}** ({v:.1f}%)" for h, v in worst.items()))
        st.dataframe(hole_tbl.sort_values(y_col, ascending=False),
                     use_container_width=True)

# ------------------------------------------------------ by location
with t_loc:
    loc = (adf.dropna(subset=["diff_s"])
           .groupby("location")
           .agg(fixes=("fix_id", "count"),
                median_diff_s=("diff_s", "median"),
                p95_diff_s=("diff_s", lambda s: s.quantile(0.95)),
                max_diff_s=("diff_s", "max"),
                health_pct=("diff_s", health_pct),
                within_max_pct=("diff_s", within_max),
                pct_delayed=("diff_s", delayed_rate)))
    gl = out.groupby("location")["fix_id"].count()
    loc["signal_gaps"] = gl.reindex(loc.index).fillna(0).astype(int)
    if FOCUSED:
        fc = focus_counts("location").reindex(loc.index)
        loc["focus_fixes"] = fc["focus_fixes"].fillna(0).astype(int)
        loc["pct_of_group"] = fc["pct_of_group"]
    loc = loc.round(1)
    # Only rank spots with enough fixes to mean anything
    _rank_col = "pct_of_group" if FOCUSED else "pct_delayed"
    ranked = (loc[loc["fixes"] >= 20]
              .sort_values(_rank_col, ascending=False).head(15))
    if ranked.empty:
        ranked = loc.sort_values(_rank_col, ascending=False).head(15)
    cl = ranked.reset_index()
    y_col = "pct_of_group" if FOCUSED else "pct_delayed"
    st.markdown(
        (f"**Worst 15 spots by share of their fixes in {focus_label}** "
         "(20+ fixes only)") if FOCUSED else
        (f"**Worst 15 spots by share of fixes over {OK_S:.0f}s** "
         "(sorted worst first, 20+ fixes only)"))
    lcols = ["location", y_col, "fixes"]
    if FOCUSED:
        lcols.append("focus_fixes")
    st.altair_chart(
        bar_labeled(cl[lcols], "location", y_col, x_title="",
                    y_title=(f"% in {focus_label}" if FOCUSED
                             else f"% over {OK_S:.0f}s"),
                    sort=list(cl["location"]), color=TM_ORANGE,
                    fmt=".1f", height=340, label_angle=-35),
        use_container_width=True)
    st.dataframe(loc.sort_values(y_col, ascending=False),
                 use_container_width=True)

# --------------------------------------------------------- by round
with t_round:
    st.caption("Round IDs as they appear in the dashboard — open any of "
               "them at dashboard.tagmarshal.golf/fixes/<round id>.")
    rnd = (adf.groupby(["round_id", "tag", "device_id"])
           .agg(date=("date", "first"),
                start=("recorded", "min"),
                end=("recorded", "max"),
                fixes=("fix_id", "count"),
                median_diff_s=("diff_s", "median"),
                p95_diff_s=("diff_s", lambda s: s.quantile(0.95)),
                max_diff_s=("diff_s", "max"),
                max_gap_s=("interval_s", "max"),
                health_pct=("diff_s", health_pct),
                within_max_pct=("diff_s", within_max),
                pct_delayed=("diff_s", delayed_rate))
           .reset_index())
    gr = out.groupby("round_id")["fix_id"].count()
    rnd["signal_gaps"] = rnd["round_id"].map(gr).fillna(0).astype(int)
    if FOCUSED:
        fc = focus_counts("round_id")
        rnd["focus_fixes"] = (rnd["round_id"].map(fc["focus_fixes"])
                              .fillna(0).astype(int))
        rnd["pct_of_group"] = rnd["round_id"].map(fc["pct_of_group"])
    rnd["_k"] = pd.to_numeric(rnd["tag"], errors="coerce")
    rnd = rnd.sort_values(["date", "_k", "start"]).drop(columns="_k").round(1)

    rc1, rc2 = st.columns([1, 1])
    sort_by = rc1.selectbox(
        "Sort rounds by",
        ["Worst health first", "Most delayed first", "Biggest gap first",
         "Chronological", "Tag order"], index=0)
    rnd_view = {
        "Worst health first": rnd.sort_values("health_pct"),
        "Most delayed first": rnd.sort_values("pct_delayed",
                                              ascending=False),
        "Biggest gap first": rnd.sort_values("max_gap_s", ascending=False),
        "Chronological": rnd.sort_values("start"),
        "Tag order": rnd.assign(
            _k=pd.to_numeric(rnd["tag"], errors="coerce")
        ).sort_values(["_k", "start"]).drop(columns="_k"),
    }[sort_by]
    rc2.metric("Rounds in view", f"{len(rnd_view):,}")

    st.dataframe(
        rnd_view, use_container_width=True, hide_index=True,
        column_config={
            "round_id": st.column_config.TextColumn("Round ID", width=200),
            "health_pct": st.column_config.ProgressColumn(
                "Health %", min_value=0, max_value=100, format="%.1f"),
        })
    st.download_button(
        "⬇️ Download per-round summary CSV",
        rnd_view.to_csv(index=False).encode(),
        file_name="round_summary.csv", mime="text/csv")

# ----------------------------------------------------- by device/tag
with t_dev:
    st.caption("A tag that is bad everywhere points at the device or SIM; "
               "a tag that is only bad where others are too points at "
               "course coverage.")
    dev = (adf.groupby(["tag", "device_id"])
           .agg(rounds=("round_id", "nunique"),
                fixes=("fix_id", "count"),
                median_diff_s=("diff_s", "median"),
                p95_diff_s=("diff_s", lambda s: s.quantile(0.95)),
                max_diff_s=("diff_s", "max"),
                max_gap_s=("interval_s", "max"),
                health_pct=("diff_s", health_pct),
                within_max_pct=("diff_s", within_max),
                pct_delayed=("diff_s", delayed_rate))
           .reset_index())
    gt = out.groupby("tag")["fix_id"].count()
    dev["signal_gaps"] = dev["tag"].map(gt).fillna(0).astype(int)
    if FOCUSED:
        fc = focus_counts("tag")
        dev["focus_fixes"] = (dev["tag"].map(fc["focus_fixes"])
                              .fillna(0).astype(int))
        dev["pct_of_group"] = dev["tag"].map(fc["pct_of_group"])
    dev["_k"] = pd.to_numeric(dev["tag"], errors="coerce")
    dev = dev.sort_values(["_k", "tag"]).drop(columns="_k").round(1)

    ct = dev.copy()
    ct["tag"] = ct["tag"].astype(str)
    st.markdown(f"**Health by tag** — % of fixes inside {OK_S:.0f}s "
                "(tags in numeric order)")
    st.altair_chart(
        bar_labeled(ct[["tag", "health_pct", "fixes", "rounds"]],
                    "tag", "health_pct", x_title="Tag",
                    y_title="Health %", sort=list(ct["tag"]),
                    color=TM_GREEN, fmt=".1f", height=300),
        use_container_width=True)
    st.dataframe(dev.set_index("tag"), use_container_width=True,
                 column_config={"health_pct": st.column_config.ProgressColumn(
                     "Health %", min_value=0, max_value=100, format="%.1f")})

    fleet = dev["pct_delayed"].median()
    if pd.notna(fleet) and fleet > 0:
        flagged = dev[dev["pct_delayed"] > 2.5 * fleet]
        if not flagged.empty:
            st.warning(
                f"Tags delayed far more often than the fleet median "
                f"({fleet:.1f}%) — worth checking the hardware: "
                + ", ".join(f"**{t}**" for t in flagged["tag"].head(10)))

# ----------------------------------------------------------- by SIM
if t_sim is not None:
    with t_sim:
        st.caption("Compares SIM fleets on the same course. If one provider "
                   "is consistently worse across the same holes, the "
                   "problem is the connectivity layer rather than the "
                   "course or the devices.")
        sim = (adf.groupby("sim_provider")
               .agg(tags=("tag", "nunique"),
                    rounds=("round_id", "nunique"),
                    fixes=("fix_id", "count"),
                    median_diff_s=("diff_s", "median"),
                    p95_diff_s=("diff_s", lambda s: s.quantile(0.95)),
                    max_diff_s=("diff_s", "max"),
                    health_pct=("diff_s", health_pct),
                    within_max_pct=("diff_s", within_max),
                    pct_delayed=("diff_s", delayed_rate)))
        gs = out.groupby("sim_provider")["fix_id"].count()
        sim["signal_gaps"] = gs.reindex(sim.index).fillna(0).astype(int)
        if FOCUSED:
            fc = focus_counts("sim_provider").reindex(sim.index)
            sim["focus_fixes"] = fc["focus_fixes"].fillna(0).astype(int)
            sim["pct_of_group"] = fc["pct_of_group"]
        sim = sim.round(1).sort_values("health_pct", ascending=False)

        cs = sim.reset_index()
        st.markdown(f"**Health by SIM provider** — % of fixes inside "
                    f"{OK_S:.0f}s")
        st.altair_chart(
            bar_labeled(cs[["sim_provider", "health_pct", "fixes", "tags"]],
                        "sim_provider", "health_pct", x_title="",
                        y_title="Health %", sort=list(cs["sim_provider"]),
                        color=TM_GREEN, fmt=".1f", height=300),
            use_container_width=True)
        st.dataframe(
            sim, use_container_width=True,
            column_config={
                "health_pct": st.column_config.ProgressColumn(
                    "Health %", min_value=0, max_value=100, format="%.1f"),
                "within_max_pct": st.column_config.ProgressColumn(
                    f"Within {MAX_S:.0f}s %", min_value=0, max_value=100,
                    format="%.1f")})

        # Same holes, different SIMs — isolates provider from geography
        both = adf.dropna(subset=["hole"])
        if both["sim_provider"].nunique() > 1:
            piv = (both.pivot_table(index="hole", columns="sim_provider",
                                    values="diff_s", aggfunc=delayed_rate)
                   .round(1))
            piv.index = piv.index.astype(int)
            st.markdown(f"**% of fixes over {OK_S:.0f}s, hole by hole, "
                        "split by SIM provider**")
            st.dataframe(piv.sort_index(), use_container_width=True)

        st.markdown("**Which tags are on which SIM**")
        tag_sim = (adf.groupby(["sim_provider", "tag"])
                   .agg(fixes=("fix_id", "count"),
                        health_pct=("diff_s", health_pct))
                   .reset_index())
        tag_sim["_k"] = pd.to_numeric(tag_sim["tag"], errors="coerce")
        tag_sim = (tag_sim.sort_values(["sim_provider", "_k", "tag"])
                   .drop(columns="_k").round(1))
        st.dataframe(tag_sim, use_container_width=True, hide_index=True)

# ---------------------------------------------------- by time of day
with t_time:
    hrs = adf.dropna(subset=["hour"]).copy()
    if hrs.empty:
        st.info("No timestamps available for a time-of-day breakdown.")
    else:
        by_hr = (hrs.groupby("hour")
                 .agg(fixes=("fix_id", "count"),
                      median_diff_s=("diff_s", "median"),
                      p95_diff_s=("diff_s", lambda s: s.quantile(0.95)),
                      pct_delayed=("diff_s", delayed_rate))
                 .round(1).reset_index())
        by_hr["hour_lbl"] = by_hr["hour"].astype(int).map(
            lambda h: f"{h:02d}:00")
        st.markdown(f"**Share of fixes over {OK_S:.0f}s by hour** — a curve "
                    "that climbs through the day points at network "
                    "congestion rather than course geography")
        st.altair_chart(
            bar_labeled(by_hr[["hour_lbl", "pct_delayed", "fixes",
                               "p95_diff_s"]],
                        "hour_lbl", "pct_delayed", x_title="Hour",
                        y_title=f"% over {OK_S:.0f}s",
                        sort=list(by_hr["hour_lbl"]), color=TM_YELLOW,
                        fmt=".1f", height=280),
            use_container_width=True)
        st.dataframe(by_hr.drop(columns="hour_lbl").set_index("hour"),
                     use_container_width=True)

        if adf["date"].nunique() > 1:
            per_day = (adf.dropna(subset=["date"]).groupby("date")
                       .agg(fixes=("fix_id", "count"),
                            pct_delayed=("diff_s", delayed_rate))
                       .round(1).reset_index())
            per_day["day"] = per_day["date"].astype(str)
            st.markdown("**By day**")
            st.altair_chart(
                bar_labeled(per_day[["day", "pct_delayed", "fixes"]],
                            "day", "pct_delayed", x_title="",
                            y_title=f"% over {OK_S:.0f}s",
                            sort=list(per_day["day"]), color=TM_RED,
                            fmt=".1f", height=260, label_angle=-35),
                use_container_width=True)

# ----------------------------------------------------------- gap log
with t_out:
    st.caption(f"Every gap of {OUTAGE_IV:.0f}s or more between consecutive "
               f"fixes (normal cadence ≈ {NOMINAL_IV:.0f}s). The device was "
               "silent between the previous fix and this one.")
    if out.empty:
        st.success("No signal gaps over the threshold in this selection.")
    else:
        log = (out.sort_values("interval_s", ascending=False)
               [["recorded", "tag", "location", "interval_s", "diff_s",
                 "round_id", "lat", "lon"]]
               .rename(columns={"interval_s": "gap_s"})
               .head(500).round(1))
        st.dataframe(log, use_container_width=True, hide_index=True,
                     column_config={"round_id": st.column_config.TextColumn(
                         "Round ID", width=200)})
        st.download_button(
            "⬇️ Download gap log CSV",
            out.to_csv(index=False).encode(),
            file_name="signal_gap_log.csv", mime="text/csv")

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
