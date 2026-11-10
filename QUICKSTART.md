# GPS Signal Heatmap — quick start

A tool for finding where on a golf course the tracking units struggle to
reach the network.

**New to it?** Open the app and press **Tutorial**, top-left, for a short
walkthrough of what each part does.

---

## The idea in one paragraph

Every tracking unit records its position and sends it to the server. Two
timestamps come back with each fix: when the unit *recorded* it, and when
the server *received* it. The gap between them is the **diff**. Where
mobile coverage is weak the diff grows, because the unit cannot get its
position out. Map the diff across the course and the weak spots show
themselves.

---

The app follows your browser's light or dark setting — there is no switch
inside it.

## 1. Connect

The first screen is a landing page asking for the same two things every
time:

- **API base URL** — the region host plus the course slug, e.g.
  `https://lon1.tagmarshal.golf/course-slug`. It is the same address the
  dashboard itself calls.
- **UserToken** — your dashboard login, as a token:
  1. Open `dashboard.tagmarshal.golf` and sign in
  2. Press **F12** → **Application** tab
  3. **Local Storage** → `https://dashboard.tagmarshal.golf`
  4. Copy the value of **`auth.userToken`** (a long `eyJ...` string)

  Once it's fetched, the sidebar (which this form moves into — see below)
  shows how many days that token has left. They last about 30 days, then
  you fetch a new one the same way.

## 2. Fetch

Choose the dates and press **Fetch rounds & fixes**.

- Rounds already fetched are reused, so an interrupted pull picks up where
  it stopped rather than starting over.
- Refreshing the page restores the last dataset instead of downloading it
  again.
- Large pulls are happier run on your own machine than on Streamlit Cloud.
- Once fetching finishes, the page transitions: the landing form tucks
  itself into the sidebar on the left — still holding what you typed — and
  the main area fills with the dashboard. Everything in the sidebar
  (dates, SIM upload) stays editable from there for the rest
  of the session.

## 3. Choose a view

| View | What it answers |
|---|---|
| **Delay diagnostics** | Where on the course do fixes arrive late? |
| **Network coverage** | Which operator and cell was each unit on? |
| **GPS accuracy** | How tight was the position fix? |
| **Buffered fixes** | Where did units store data and send it late? |

Next to the views, **Diff / Interval** decides what is being measured.
Diff is how late a fix arrived; Interval is how long the unit went between
fixes. The whole page follows whichever you pick.

## 4. Read the figures

The three "Within" cards are the same measurement at three marks — the
share of fixes that arrived within 2, 5 and 120 seconds.

- **within 2s** — the target
- **within 5s** — comfortable, no cause for concern
- **within 120s** — the most worth tolerating; past this it is a real
  problem

Alongside them: the median and worst value, how many fixes breached 120s,
and the total fixes and rounds in view.

## 5. Read the map

Warm colours mark slow fixes. Start with **Minimum delay to show** at
120s so the healthy fixes drop away and only trouble is left.

The lines run from the last good fix to the first delayed one — the
stretch where the unit was silent. Units do not buffer by default, so a
long delay appears on the first fix *after* coverage returned, not during
the outage.

## 6. Narrow it down

- **Drill down** — pick any set of holes, zones or tags and see everything
  about them.
- **Where to look** (under *More*) — does it for you. It raises the
  cut-off until the problem stops covering the whole course, then names
  the zone or the unit responsible, with how far above normal it sits.

## 7. Send it to a client

**Export for a client** at the bottom produces a branded one-page map with
no jargon and one headline figure. Inside *Drill down*, the **Send to
client** tab does the same for just the holes or tags you selected, with
its own map of that area.

The Excel workbook alongside it keeps the detailed numbers for internal
use.

---

## HDOP and SNR (GPS accuracy)

Open **GPS accuracy** — it starts on the **HDOP/SNR** tab (the metres view
is the **Accuracy** tab beside it).

- **HDOP** is the *Signal Quality* column on the replay fixes — lower is
  better. **SNR** is *Signal Strength* — higher is better.
- There are two sets of limits: a **Fix threshold** and a **Geo
  threshold**. Each has an HDOP box (*invalid above*) and an SNR box
  (*invalid below*). They start at Fix HDOP 1.2 / SNR 18 and Geo HDOP 0.8 / SNR 21 —
  change them if your devices are configured differently. They are remembered
  while you move between views.
- A fix is **invalid** when its HDOP is above the limit **or** its SNR is
  below it. A value sitting exactly on the limit passes. A fix that
  carried neither reading is left out rather than counted as good or bad.
- **A fix must pass both tests to be valid** — if either one fails, it is
  invalid.
- The map has three modes under **Show**:
  - **Valid / invalid** — green where fixes pass both tests, red where
    they fail. A grid square turns red once the share of failing fixes in
    it reaches the **Flag a square at** setting (25% to start; lower it to
    catch small pockets, raise it to see only places that are bad
    throughout).
  - **HDOP only** and **SNR only** — each reading coloured by quality,
    green for the best through yellow to orange for the poorest that still
    passes. Anything **over the limit is red, larger and ringed**, so a
    breach never depends on telling two shades apart. The key under the
    map gives the actual values at each end of the colour scale and the
    share of fixes over the limit.
  - **Against** picks whether the Fix or the Geo limits are used.
  - Use the layer box on the map to show the red layer on its own.
- Below the map, **Hole**, **Tag**, **Zone** and **Distribution** work like
  the delay diagnostics tabs; **Distribution** shows where the readings sit
  against both limits, which helps when choosing them.
- Readings are rounded to 1 decimal before they are compared, because the
  dashboard sends values like 0.6000000238418579 for 0.6 — without that, a
  limit of 0.6 would fail a reading of 0.6. Enter limits to 1 decimal.

What the pattern tells you: mostly SNR failures point at sky view or an
antenna; mostly HDOP failures point at satellite geometry (trees,
buildings, a steep hole); one tag far worse than the rest is that unit.

## Cell IDs: hex and decimal

The dashboard reports Cell ID and LAC in **hexadecimal** (`0448B810`,
`6FD5`). Tower databases such as OpenCelliD use **decimal**. The Cell
inventory and Handover log show both side by side (*Cell ID (hex)* and
*Cell ID (decimal)*, likewise for LAC), and map popups give both. The
*Hex / decimal converter* on the Cell inventory tab converts any value
either way.

When you add a tower list, cells are matched in decimal, so the
dashboard's hex IDs are converted first. A tower list whose IDs contain
letters is treated as hex.

## Reading the results

- **One zone far worse than the rest** → a coverage hole. Check the site
  for what changed: new buildings, tree growth, a mast outage.
- **One tag far worse than the rest** → that unit or its SIM, not the
  course.
- **Everything mildly bad, spread evenly** → carrier or configuration, not
  geography. Check the time-of-day view: a curve that climbs through the
  day points at congestion.
- **Accuracy poor but delays fine** → sky blockage rather than a network
  problem. Trees and steep terrain do this.

## If something goes wrong

| Symptom | Likely cause |
|---|---|
| "Oh no. Error running app." | The container wedged — reboot from Manage app |
| 401 errors on fetch | Token expired; fetch a new one |
| Fetch stops partway | Laptop slept. Press fetch again; it resumes |
| Map blank, rest fine | Satellite tile service rate-limited |
