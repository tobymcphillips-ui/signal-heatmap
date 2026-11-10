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

## v5.3

**Added**
- Course-only maps. Every map now shows the satellite image only where
  the fixes are and fills the rest with the page's dark colour, like the
  dashboard map. The area comes from all the loaded fixes (so it does not
  change with filters), ignores stray fixes, and sits under the markers
  and heat layer. New sidebar panel *Map style*: *Show only the course*
  (on by default) and *Course margin (m)* (default 70). Also applies to
  the maps in the client report.

**Changed**
- Dark only. The light palette, the browser-theme detection and the
  Appearance switch are removed, and `config.toml` pins the dark theme as
  in v4.6 (so Streamlit 1.36 is enough again).

## v5.2

**Restored**
- The Appearance (Auto / Dark / Light) switch in the sidebar, exactly as
  in v4.6. It was the only visible difference between v5.0 and the v4.6
  look: a pixel comparison of the two in a dark browser matches
  everywhere else. Auto follows the browser. Forcing the opposite theme
  restyles the app's panels, charts and maps, but Streamlit's own table
  grids keep following the browser.

## v5.0

**Fixed**
- Light and dark mode. The theme in `config.toml` was pinned dark while
  the app's own panels followed the browser, so a browser set to light
  showed white cards on a dark page, a white-on-white title, and
  unreadable values. The config now has `[theme.light]` and `[theme.dark]`
  sections so Streamlit follows the browser too, and dark mode keeps the
  exact v4.6 colours. A test checks the app palette and the config agree.
- In light mode the hero title was hard-coded white and the primary
  button text was hard-coded near-black on a dark accent; both now follow
  the theme.

**Added**
- Cell ID and LAC are shown in hex (as the dashboard sends them) and
  decimal side by side in the Cell inventory and Handover log, and in
  map popups.
- A Hex / decimal converter on the Cell inventory tab (either direction,
  accepts a `0x` prefix).

**Changed**
- Tower lists are now matched in decimal, so the dashboard's hex cell IDs
  match an OpenCelliD export (previously they could not).
- Removed the Appearance (Auto / Dark / Light) selector: it restyled the
  app's panels but not Streamlit's table grids, so forcing the opposite
  theme to the browser's mixed light and dark. Follow the browser
  setting instead.

**Requires**
- Streamlit 1.52 or later.

## v4.9

**Changed**
- Back to the v4.6 look. The v4.7 restyle (IBM Carbon theme) is withdrawn:
  the stylesheet, `config.toml` and `requirements.txt` are identical to
  v4.6 again, including the Appearance selector.

**Fixed** (carried over from v4.8)
- Network coverage said "0 a network" even though every fix had a cell
  ID. The replay page sends MCC/MNC zero-padded to four digits each
  (`0214/0007`); the parser only accepted a 3-digit MCC. It now reads
  `0214/0007`, `214/07`, `214-07`, `21407` and the split-column form
  alike, and treats `0/0` or anything outside the 200-999 MCC range as
  not reported rather than as a network.

**Added**
- Operators for Spain (Movistar, Vodafone, Orange, Yoigo) and the main
  markets in France, Germany, Italy, Portugal, the Netherlands, Belgium,
  Switzerland and Austria. Any code not in the table still shows as
  "Unknown network (xxx-yy)" with the code.

## v4.6

**Changed**
- Default thresholds are now **Fix**: HDOP 1.2, SNR 18 and **Geo**: HDOP
  0.8, SNR 21 (they were placeholders). Still editable, and still
  remembered while you move between views.

## v4.5

**Changed**
- HDOP and SNR readings are rounded to **1 decimal place** (v4.4 used 4).
  That is all the precision the limits need, and it still removes the
  float32 noise in what the dashboard sends. The HDOP limit boxes go back
  to 0.1 steps with one decimal, and the map key and popups show one
  decimal. A side effect: HDOP readings that sit close together (0.52 and
  0.63, say) collapse to 0.5 and 0.6, so the HDOP colour scale steps
  rather than blends when the readings span a narrow range.

## v4.4

**Added**
- HDOP/SNR map modes. **Show** now offers *Valid / invalid* (green where a
  fix passes both tests, red where it fails — a fix must pass both),
  *HDOP only* and *SNR only*. The single-metric modes colour each reading
  from green (best) through yellow to orange (poorest that still passes),
  and draw anything over its limit red, larger and ringed, in its own
  "Over limit" layer. A key under the map shows the values at each end of
  the scale and the share over the limit. **Against** chooses the Fix or
  Geo limits.
- *Flag a square at (% failing)* — a grid square is drawn red once that
  share of its fixes fail.

**Fixed**
- Readings are now rounded to 4 decimals when read. The dashboard sends
  float32 values widened to doubles (0.6 arrives as 0.6000000238418579),
  which made a reading of 0.6 fail a limit of 0.6. (v4.3 stored them at
  full precision and would have had this problem.)
- HDOP limit boxes step in 0.05 and show two decimals, since real HDOP
  values are often below 1.

**Changed**
- Valid is now green and Invalid red (v4.3 used cyan and magenta).

## v4.3

**Added**
- **HDOP/SNR** sub-tab under GPS accuracy, and it is the one that opens
  first (the existing metres view is now the **Accuracy** sub-tab). It
  reads the replay fixes' Signal Quality (HDOP) and Signal Strength (SNR)
  as numbers — `-` means absent — and tests them against two sets of
  limits you enter: a **Fix threshold** and a **Geo threshold**, each with
  an HDOP limit (invalid above) and an SNR limit (invalid below). The
  comparisons are strict, so a value exactly on a limit passes, and a
  fix with neither reading is left out rather than counted either way.
- A map of where the invalid fixes are (aggregate grid, selected tags, or
  a single round's route), switchable between the two threshold sets, with
  a layer key to show Invalid on its own.
- Hole, Tag, Zone and Distribution analytics for the same, in the style of
  the delay diagnostics page: invalid % per hole in playing order, per tag
  with a flag on tags failing far more than the fleet, worst zones, and
  HDOP/SNR histograms with both thresholds drawn on them. Fail-reason
  columns show whether HDOP or SNR is doing the failing.
- Threshold boxes keep their values when you move to another view and back.

**Changed**
- HDOP and SNR are stored as full-precision numbers (not the float32 used
  for delays): the tests are strict, and float32 would push a reading
  sitting exactly on a limit over it.
- Saved datasets are now versioned, so one saved before HDOP/SNR existed
  is refetched (quickly, from the per-round cache) instead of being
  restored without those columns.

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
