# Changelog

Notable changes, newest first. This file starts at v4.2 — earlier
versions (v1 through v4.1) went through a long iterative build and
weren't tracked formally, so they're not reconstructed here rather than
risk getting the details wrong. Broadly: v1–v3.2 were the original
delay-heatmap tool; v3.3 dropped the Tagmarshal branding for a plain
technical look; v3.4–v3.9 added the Network coverage, GPS accuracy and
Buffered fixes views, the drill-down and "where to look" suggestion
tabs, and client export; v4.0 introduced the landing-page-into-sidebar
flow. From here on, changes are logged properly.

## v4.2

**Fixed**
- Network coverage crashed with a `TypeError` whenever a round had a
  fix with a missing cell ID, network, or location — `shrink()` (added
  to cut memory use on large pulls) casts those columns to pandas
  `category` dtype, and a categorical column rejects `.fillna()` with
  any value that isn't already one of its known categories. Fixed by
  casting to `object` first in the four places this was reachable
  (`build_category_map`'s three fills, and the network-change count in
  `render_network_view`). `tests/test_app.py` now deliberately includes
  rows with missing values in these columns so this class of bug can't
  silently come back.
- The landing page briefly showed a literal `</div>` with a copy icon
  instead of rendering the hero correctly. Cause: the hero's descriptive
  paragraph is conditional (hidden on the landing page, shown once data
  is loaded) — when it collapsed to an empty string, it left a blank
  line inside the surrounding HTML, and Python-Markdown's parser treats
  a blank line as the end of a raw-HTML block, so the indented closing
  tags after it were parsed as a code block and shown literally instead
  of as HTML. Fixed by switching the hero and the landing info panel
  from `st.markdown(..., unsafe_allow_html=True)` to `st.html()`, which
  never goes through Markdown parsing and has no such failure mode.
- Tutorial dialog "stuck on each point": Back/Next were triggering a
  full-page rerun, which recomputed the entire dashboard — every chart
  and map — behind the modal on every click. The dashboard now renders
  nothing at all while the tutorial is open, so even a full rerun has
  nothing expensive left to do. Also fixed: dismissing the dialog via
  its native close button (rather than Finish) used to leave it stuck
  reopening on the next click, since only Finish updated the
  `tour_open` flag — added an `on_dismiss` handler.

**Added**
- Optional password gate: set `APP_PASSWORD` in Streamlit secrets to
  put a single shared password in front of the whole app. Off by
  default. See `SECURITY.md`.
- `tests/test_app.py` — a pytest regression suite using Streamlit's
  `AppTest` harness. Covers all four views with gapped data, both
  landing-page branches, the password gate, the tutorial's dashboard
  short-circuit, and the headline card layout.
- `SECURITY.md`, `.streamlit/secrets.toml.example`,
  `requirements-dev.txt`.

**Changed**
- The headline metric row is reordered so the three percentage cards
  (Within 2s / 5s / 120s) sit consecutively instead of being split
  across two rows — easier to compare at a glance.
- README.md rewritten; it had drifted well behind the app (referenced a
  request-delay slider and other controls removed several versions
  ago).

## v4.1

- Tutorial: diagnosed as triggering a full dashboard rebuild per click
  (first attempt used `st.rerun(scope="fragment")`, which this
  Streamlit version doesn't honour inside `st.dialog` content — see the
  proper fix above in v4.2, where the dashboard is skipped instead).
- Landing page rebuilt as two columns: the connect form on the left, a
  new panel on the right carrying the explanation that used to sit
  alone above an empty page, plus feature bullets and a pointer to
  Tutorial.
- Removed the "Choose the figures shown" headline-card picker — all
  eight cards always show now.

## v4.0

- Landing page introduced: the connection form renders on the main page
  until a dataset is fetched, then moves into the sidebar, which
  auto-expands — the hand-off reads as a transition rather than a reset.
- "Saved courses" removed — it could only persist the course name and
  URL, never the token, which made it more confusing than useful.
