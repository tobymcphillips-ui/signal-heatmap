# GPS Signal Heatmap — Tagmarshal Course Coverage Analyzer

A Streamlit app that pulls every round's GPS fixes from the Tagmarshal
dashboard API, measures the **Diff** (server-received time minus
device-recorded time) and the **Interval** (gap between consecutive fixes),
and plots them as a heatmap over a satellite image of the course so you can
see exactly where on the course devices lose signal.

## How it talks to the dashboard

The app uses the same API the dashboard itself calls (discovered from the
HAR capture of the site):

| Purpose | Endpoint |
|---|---|
| List rounds | `GET {base}/rounds?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&page=N&records=100&sort=startTime+asc,tag+desc` |
| Fixes for a round | `GET {base}/fixes/roundFixes/{roundId}` |
| Fixes CSV export | `GET {base}/fixes/roundFixes/{roundId}?action=export` |

`{base}` is the region host plus course slug, e.g.
`https://lon1.tagmarshal.golf/dumbarnielinks`.

Both endpoints require a `UserToken` header containing your login JWT.

### Getting your UserToken

1. Log in at `dashboard.tagmarshal.golf` as usual.
2. Open DevTools (F12) → **Application** tab → **Local Storage** →
   `https://dashboard.tagmarshal.golf`.
3. Copy the value of the `auth.userToken` key (a long `eyJ...` string).
   Alternatively, open the **Network** tab, click any request to
   `lon1.tagmarshal.golf`, and copy the `UserToken` request header.
4. Paste it into the app's sidebar. It is held only in your Streamlit
   session — never written to disk.

Tokens expire (yours carries an `expiresAt` claim), so refresh it when
requests start returning 401.

## Install & run

```bash
pip install -r requirements.txt
streamlit run app.py
```

## How the signal analysis works

- **Diff** is computed directly from each fix's `recordedTime` and
  `receivedTime` timestamps, so it doesn't depend on the API's pre-formatted
  "26 secs" strings.
- **Interval** is the time between consecutive recorded fixes within a round.
- Devices **do not buffer fixes**. When a device loses signal, nothing is
  transmitted until coverage returns — so the large Diff/Interval shows up on
  the *first fix after* the outage. The outage actually happened somewhere
  along the path between the previous fix and that fix. The
  **"Spread weight along segment"** option interpolates the heat weight along
  that line, which paints the whole dead zone rather than just its exit
  point.
- The threshold slider hides healthy fixes (small diffs are normal transport
  latency) so the heatmap shows only genuine problem areas.
- Log-scaled weights stop one extreme outage (e.g. a device left in a
  clubhouse) from drowning out the rest of the map.

## Map

Satellite imagery comes from the free Esri World Imagery tile service, with
layers for:

- the signal heatmap (Diff or Interval weighted),
- the N worst fixes as clickable red markers with full details,
- an optional faint dot layer of *all* fixes for coverage context.

## Outputs

- **Worst areas by course location** — fixes grouped by the `location` label
  (e.g. "Hole 7 Fairway") ranked by 95th-percentile diff.
- **Per-round summary** — spot a single misbehaving device vs. a real
  coverage hole.
- **Download combined fixes CSV** — the full flattened dataset for Excel/GIS.

## Notes & etiquette

- Each round is one API call; the request-delay slider keeps the load gentle
  when pulling a big date range.
- This uses your own authenticated session against your own course's data.
  Keep the token private — anyone holding it can read your dashboard data.
- If your course lives on a different region server (not `lon1`), just change
  the base URL accordingly.
