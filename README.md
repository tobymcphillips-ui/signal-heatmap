# GPS Signal Heatmap — Tagmarshal Course Coverage Analyzer

Pulls every round's GPS fixes from the Tagmarshal dashboard API, measures
how long each fix took to reach the server, and maps where on the course
that delay grows — which is where mobile coverage is weak.

For how to actually *use* the app, see **[QUICKSTART.md](QUICKSTART.md)**.
This file is about running and developing it.

## Install & run

```bash
pip install -r requirements.txt
streamlit run app.py
```

The first screen is a landing page asking for the course's API address
and your dashboard token — nothing is fetched until you submit it. See
QUICKSTART.md for where to find both.

## Project layout

```
app.py                          the whole app — one Streamlit script
requirements.txt                runtime dependencies
QUICKSTART.md                   how to use the app, for a new user
SECURITY.md                     what the app stores, the password gate
CHANGELOG.md                    notable changes by version
.streamlit/config.toml          theme
.streamlit/secrets.toml.example optional password gate — copy & fill in
.gitignore                      excludes the local fetch cache and secrets
```

## How it talks to the dashboard

The app uses the same API the dashboard itself calls:

| Purpose | Endpoint |
|---|---|
| List rounds | `GET {base}/rounds?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&page=N&records=200&sort=startTime+asc,tag+desc` |
| Fixes for a round | `GET {base}/fixes/roundFixes/{roundId}` |

`{base}` is the region host plus course slug, e.g.
`https://lon1.tagmarshal.golf/course-slug`. Every request needs a
`UserToken` header — see QUICKSTART.md for where to find it. The app
never stores it; see SECURITY.md for the full picture.

## How the signal analysis works

- **Diff** is computed from each fix's `recordedTime` and `receivedTime`
  timestamps directly, not the API's pre-formatted "26 secs" strings.
- **Interval** is the time between consecutive recorded fixes in a round.
- Devices do **not** buffer fixes by default — when one loses signal,
  nothing is sent until coverage returns, so a large Diff or Interval
  shows up on the *first* fix after the outage, not during it. The map's
  outage lines run from the last good fix to that one, which is the
  stretch where the device was actually silent.
- Three thresholds, all adjustable: 2s (ideal), 5s (comfortable), 120s
  (the point a delay becomes a real problem). The three headline
  percentage cards and most of the analytics are built around these.
- A **Buffered fixes** view exists for when buffering does get turned on
  somewhere — it reads the `cached` flag on each fix.
- **Network coverage** and **GPS accuracy** are separate views reading
  the cell/MCC-MNC, accuracy, HDOP and SNR columns, when the dashboard
  sends them. HDOP is the fixes table's *Signal Quality* and SNR is
  *Signal Strength*; the HDOP/SNR tab tests them against a Fix and a Geo
  threshold you enter. A fix must pass both tests: HDOP above its limit
  or SNR below its limit makes it invalid. The map shows valid/invalid in
  green/red, or HDOP-only / SNR-only as a colour scale with breaches in red.

## Memory

A few thousand rounds is millions of rows. `shrink()` (in app.py) casts
repeated-value columns to pandas `category` dtype and measurements to
`float32` to keep a large pull inside a hosted app's memory limit —
**this is why the test suite deliberately includes rows with missing
values in those columns**: a categorical column raises a `TypeError` on
`.fillna()` with a value outside its known categories, but only when a
real gap exists in the data, which a tidy hand-written fixture won't
produce by accident. See `CHANGELOG.md` (v4.2).

## Theme

Dark only. `.streamlit/config.toml` pins just the dark base and sets no
colours, on purpose: Streamlit's own widgets (tags, radios, sliders, tab
underlines, form buttons) keep Streamlit's default accents, which is how
v4.6 looks on the deployment. The cyan and navy are the app's own panels,
buttons and charts, drawn from the palette in `app.py`.

Do not add `primaryColor` and friends to the config unless you want every
native widget recoloured: v5.5 forced a cyan theme and everything went
blue. A test keeps the config to the dark base only.

## Changing the app

Several past bugs (a pandas dtype mismatch, a Markdown-parsing edge case)
only showed up on real data shapes that a quick click-through didn't hit.
Before deploying a change, load a real pull and visit every view, and
make sure the data you test with has genuine gaps in it (missing cell IDs,
networks, HDOP/SNR) — see CHANGELOG.md for what went wrong and why.

## Notes & etiquette

- Each round is one API call. A large pull is read load on Tagmarshal's
  own production servers — avoid running one during peak play hours, and
  prefer running big pulls locally rather than on a hosted instance.
- This uses your own authenticated session against your own course's
  data. Keep your token private.
- Satellite imagery is the free Esri World Imagery tile service — fine
  for personal/internal use, not licensed for a redistributed product.
