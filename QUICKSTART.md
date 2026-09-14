# GPS Signal Heatmap — quick start

A tool for finding where on a golf course the tracking units struggle to
reach the network.

**New to it?** Open the app and press **Explore with sample data**. That
loads a made-up course with real-looking problems, so you can click around
everything without connecting to anything. The **Walkthrough** button in
the sidebar steps through what each part does.

---

## The idea in one paragraph

Every tracking unit records its position and sends it to the server. Two
timestamps come back with each fix: when the unit *recorded* it, and when
the server *received* it. The gap between them is the **diff**. Where
mobile coverage is weak the diff grows, because the unit cannot get its
position out. Map the diff across the course and the weak spots show
themselves.

---

## 1. Connect

In the sidebar:

- **API base URL** — the region host plus the course slug, e.g.
  `https://lon1.tagmarshal.golf/course-slug`. It is the same address the
  dashboard itself calls.
- **UserToken** — your dashboard login, as a token:
  1. Open `dashboard.tagmarshal.golf` and sign in
  2. Press **F12** → **Application** tab
  3. **Local Storage** → `https://dashboard.tagmarshal.golf`
  4. Copy the value of **`auth.userToken`** (a long `eyJ...` string)

  The sidebar shows how many days that token has left. They last about 30
  days, then you fetch a new one the same way.

## 2. Fetch

Choose the dates and press **Fetch rounds & fixes**.

- Rounds already fetched are reused, so an interrupted pull picks up where
  it stopped rather than starting over.
- Refreshing the page restores the last dataset instead of downloading it
  again.
- Large pulls are happier run on your own machine than on Streamlit Cloud.

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

Use **Choose the figures shown** to swap which cards appear.

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
