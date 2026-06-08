---
name: demo-zone-builder
description: >-
  Generate realistic Slack demo conversations from a natural-language request and
  upload them to demo-zone.tinyspeck.com. Use when the user asks to build, generate,
  or create a demo Slack channel/conversation/account-channel, or to populate a
  demo-zone demo with messages, threads, and reactions.
---

# Demo Zone Builder

Turn a request like *"build an account channel for Acme Corp — strategic tone, an
upcoming opportunity, Adam/Jenny/Frank, and Adam has unanswered requests"* into a
schema-correct demo and upload it to demo-zone.

You own the whole flow: collect credentials, generate the JSON, preview it, and drive
`demo_upload.py` to upload it. The user should never have to hand-write JSON or
copy-paste CLI invocations unless they want to.

## Files in this skill

- `SCHEMA.md` — the demo-zone `conversations_actions` schema. **This is the source
  of truth, maintained by the demo-zone dev team.** When in doubt, read it.
- `../../../demo_upload.py` — the CLI that validates, resolves names→IDs, and uploads.
  (Repo root; path is relative to this skill file.)

Always read `SCHEMA.md` before generating if you are unsure about a field.

---

## STEP 0 — Intake (do this first, before generating anything)

Before writing any conversation, collect two things from the user:

1. **The demo-zone URL** for the demo they want to populate
   (e.g. `https://demo-zone.tinyspeck.com/demo-builder/<id>`). This carries the demo
   ID and lets the CLI resolve the workspace.
2. **A bearer token** saved to the keychain (tokens last ~1 hour).

Ask for both up front. Then offer to show them how if they're unsure — say something
like:

> "To upload this I'll need the **demo-zone URL** for your demo and a current
> **bearer token**. Do you have both handy, or would you like me to **show you how**
> to get them?"

**If they choose "show me how", walk them through it:**

*Getting the demo URL:*
- Open [demo-zone.tinyspeck.com](https://demo-zone.tinyspeck.com), open (or create)
  the demo you want to populate, and copy the URL from the address bar. It looks like
  `https://demo-zone.tinyspeck.com/demo-builder/<id>`.

*Getting a bearer token:*
1. In Chrome on demo-zone, open DevTools (⌘+⌥+I) → **Network** tab.
2. Click anything on the page so a request fires.
3. Find any request to `/api/v2/` → click it → **Headers**.
4. Copy the value after `Authorization: Bearer ` (it starts with `eyJ…`).

Then save the token for them:
```bash
python3 demo_upload.py login   # paste the eyJ… token when prompted
```

Confirm the token is valid before spending effort generating — `login` rejects an
expired or malformed token. Once you have a saved token and a demo URL, continue.

> You can still **generate and preview** a conversation without these (the files are
> written to disk regardless). You only need them for the upload step. But collecting
> them first avoids losing work to an expired token.

---

## Channel naming convention

Demos live in a Slack channel. If the user names one, use it. Otherwise **create a
name** following `purpose-subject`:

| Purpose prefix | Use for | Examples |
|---|---|---|
| `acct-` | An account / customer channel | `acct-acme-corp`, `acct-salesforce` |
| `help-` | A support / help channel | `help-laptops`, `help-product-feature` |
| `announce-` | Announcements | `announce-all`, `announce-q2-launch` |

Lowercase, hyphenated, no spaces. Keep it short and descriptive. **The JSON and
markdown files are named after the channel** — `acct-acme-corp.json` and
`acct-acme-corp.md` — not after the company.

If the channel doesn't exist in the workspace yet, create it (see Process step 6).

## The payload shape

Top-level object (see SCHEMA.md for the authoritative table):

```json
{
  "name": "Acme Corp Account",
  "workspace_uid": "<filled by the CLI from the demo URL — you may omit it>",
  "conversations_actions": [ /* action objects */ ]
}
```

There is **no top-level `channel`** field — `channel` lives on every individual
action. Include a human-readable `name` for the demo. Omit `id`/`workspace_uid`; the
CLI fills them from the `--url` you pass at upload time.

## Action rules (must follow — these mirror SCHEMA.md)

**Exact type strings:** `"Message"`, `"Thread"`, `"Bulk Reaction"`, `"File"`,
`"Invite Users"`, `"Reaction"`. Never `post_message`, `thread_reply`, etc.

**Exact field names:** `channel`, `client_uuid`, `referenced_client_uuid`, `sender`,
`fake_bot_id`, `text`, `reaction_emoji`, `reaction_count`, `delay`.

**Per-action requirements:**
- Every action has a `channel` — the channel name, e.g. `"acct-acme-corp"`.
- `Message` / `Thread`: need `text` and exactly one of `sender` or `fake_bot_id` —
  **never both**.
- `Thread`: needs `referenced_client_uuid` pointing to the parent message's
  `client_uuid`, which must appear **earlier** in the array.
- `Bulk Reaction`: needs `referenced_client_uuid`, `reaction_emoji` (no colons),
  and `reaction_count` > 0. It takes **neither** `sender` nor `fake_bot_id`.
- `delay`: **always set `0`.** (The schema permits 0–300, but our convention is 0 so
  the whole conversation lands at once.)

**client_uuid:** give a stable, human-readable `client_uuid` (e.g. `"msg-1"`,
`"thread-1"`) to **any action that something else references**. The CLI auto-fills
`client_uuid` only for actions nothing points at — so a parent message that is
missing one will break its replies. When in doubt, set it explicitly.

**Resolution:** use plain names for `sender` (username), `fake_bot_id` (bot name),
and `channel` (channel name). The CLI resolves them to IDs at upload time, so you
never need UUIDs.

### Minimal correct example

```json
{
  "name": "Acme Corp Account",
  "conversations_actions": [
    { "type": "Message", "channel": "acct-acme-corp", "client_uuid": "msg-1",
      "fake_bot_id": "Service Cloud for Slack",
      "text": "Account opened: Acme Corp — $2M opportunity", "delay": 0 },
    { "type": "Message", "channel": "acct-acme-corp", "client_uuid": "msg-2",
      "sender": "adam",
      "text": "Reviewed the contract — need legal on section 3.2 before we move.",
      "delay": 0 },
    { "type": "Thread", "channel": "acct-acme-corp", "client_uuid": "thread-1",
      "sender": "jenny", "referenced_client_uuid": "msg-2",
      "text": "On it — legal feedback by EOD.", "delay": 0 },
    { "type": "Bulk Reaction", "channel": "acct-acme-corp",
      "referenced_client_uuid": "msg-2", "reaction_emoji": "fire",
      "reaction_count": 3, "delay": 0 }
  ]
}
```

See `examples/acct-acme-corp.json` and `examples/acct-acme-corp.md` for a complete,
valid demo and its readable preview.

## Process

### 1. Intake
Complete **STEP 0** above — demo URL + saved token (with the "show me how" path if
they need it).

### 2. Understand the request
Pull out: account/company, tone (strategic, urgent, casual, celebratory…),
participants, and any specific beats ("unanswered requests", "reference an
opportunity", "show a timeline"). Decide the **channel name** using the convention
above. If a critical detail is missing and you can't pick a sensible default, ask —
otherwise proceed and state the assumptions you made.

### 3. Generate the conversation
Write a natural Slack flow:
- **Open** with context — a bot notification or scene-setting human message.
- **3–6 messages** carrying the narrative and the requested beats.
- **Threads** for side conversations / replies.
- **Bulk Reactions** on a few key messages (`thumbsup`, `fire`, `eyes`,
  `white_check_mark`, `rocket`).
- **Close** with next steps or a resolution.
Keep it Slack-natural, not a formal report. Use Slack bold (`*like this*`) for key
facts. All `delay: 0`.

### 4. Write the files (before any network call)
Name the files after the **channel**. Write the JSON to `<channel-name>.json` in the
working directory **first** — this preserves the work even if the token has expired.
Optionally also write a readable `<channel-name>.md` preview (top-level messages flush
left; threads and reactions indented two spaces). Keep the `.md` and `.json` in sync.

### 5. Self-validate
Run the validator (no network, catches schema mistakes locally):
```bash
python3 demo_upload.py validate <channel-name>.json
```
Fix anything it reports and re-run until it says OK.

### 6. Create the channel if it doesn't exist yet
Check `channels`, and create the channel if needed:
```bash
python3 demo_upload.py channels --workspace <uid>
python3 demo_upload.py create-channel <channel-name> --workspace <uid> --invite adam,jenny,frank
```
Get the workspace UID from a `list`/`users`/`channels` call or from the user.

### 7. Preview the final payload (dry run), then upload
```bash
python3 demo_upload.py upload <channel-name>.json --url <demo-url> --dry-run
```
Show the user what would be sent. When they confirm, upload for real:
```bash
python3 demo_upload.py upload <channel-name>.json --url <demo-url>
```
Uploads **append** by default. If the user wants to overwrite the demo's existing
actions, add `--replace`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `validate` reports BOTH sender and fake_bot_id | Keep exactly one. |
| `referenced_client_uuid matches no client_uuid` | The parent's `client_uuid` is missing or misspelled. |
| `referenced_client_uuid is defined later` | Move the parent message earlier in the array. |
| `Unknown user/bot/channel` at upload | Run `users` / `bots` / `channels --workspace <uid>` to see valid names. |
| Token expired / 401 | `python3 demo_upload.py login` with a fresh token. |
| Duplicated conversation after re-upload | Uploads append; use `--replace` to overwrite instead. |
