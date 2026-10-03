# Security notes

## What this app stores

**Nothing, by default.** The one credential it needs — your Tagmarshal
`UserToken` — is typed into the sidebar each session and lives only in
that browser tab's memory. It is never written to disk, never logged,
and never sent anywhere except straight to the Tagmarshal API itself. A
page refresh clears it; you paste it in again.

The only things that *do* persist across sessions, in a local
`.signal_data/` folder:

| What | Why | How long |
|---|---|---|
| Fetched round fixes | So an interrupted pull resumes, and a refresh restores your last dataset instead of re-downloading it | 7 days, then cleared automatically |

Both are pure Tagmarshal telemetry (coordinates, timestamps, device IDs)
— no tokens, no passwords, nothing that grants access on its own.

An earlier version of this app also offered to remember a list of course
names and API URLs ("saved courses"). It was removed, specifically
because it could only store half of what you need to reconnect — the
URL, never the token — which made it more confusing than useful.

## Putting a password in front of the app

The app URL itself is **public** once deployed — anyone with the link
can open it. That's fine for a small team, but if you'd rather require a
shared password before the page loads at all:

1. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`
   (for local runs), or open **Settings → Secrets** on Streamlit Cloud
   for a deployed app.
2. Set `APP_PASSWORD = "something only your team knows"`.
3. Reload the app. It now shows a bare password prompt before anything
   else renders, and unlocks for that browser session once the password
   matches.

Leave `APP_PASSWORD` unset (the default) and the app behaves exactly as
it always has — no prompt, no change.

This is a single shared password, not per-user accounts — enough to keep
casual visitors out, not a substitute for real authentication if this
ever needs to hold genuinely sensitive data.

## What a visitor can and can't do

Even with the URL (and the password, if you've set one):

- They **cannot** see your Tagmarshal data without also having a valid
  token of their own — the app has none stored to lend them.
- They **cannot** modify, delete, or redeploy the app. Account-level
  controls (GitHub, Streamlit Cloud) are separate from anything this
  code does, and nothing in the app exposes them.
- They **can** see the UI, and if they have their own valid token, pull
  their own course's data through it — the app is a thin client over the
  Tagmarshal API, not a store of anyone's credentials.

## Dependencies

`requirements.txt` pins loose minimum versions rather than exact ones,
so Streamlit Cloud installs current releases. Run
`pip list --outdated` locally now and then, and re-run the test suite
(`pytest tests/`) after any bump — a pandas or Streamlit upgrade has
broken this app's behaviour before without raising at import time (see
`CHANGELOG.md`, v4.1).

## Reporting a problem

This is an internal tool, not a public product — if you find something
that looks like a real security issue (not just a bug), raise it
directly rather than filing a public GitHub issue.
