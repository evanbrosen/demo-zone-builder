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

**Locating the CLI.** The commands below say `python3 demo_upload.py …`, which works
when the working directory is the repo root. If a file named `LOCAL.md` sits next to
this `SKILL.md`, read it first — it provides a machine-specific absolute path to use
instead (for globally-installed / symlinked setups where the repo isn't the CWD). No
`LOCAL.md` → assume you're in the repo root and use `python3 demo_upload.py` as written.

---

## STEP 0 — Intake (do this FIRST, using the AskUserQuestion tool)

**Run the whole intake through the `AskUserQuestion` tool — the on-screen
selectable-options UI — not free-text prose.** This is a strong, standing preference:
present choices the user can click. AskUserQuestion always adds a free-text "Other"
field automatically, so even the values that aren't multiple-choice (the demo URL and
token) are collected inside the same flow via "Other".

AskUserQuestion allows at most **4 questions per call**, so do **two quick rounds**.

### Round 1 — credentials + framing (one AskUserQuestion call)

1. **Demo URL** — header "Demo URL". Options: "Paste it now" (the user types the
   `https://demo-zone.tinyspeck.com/demo-builder/<id>` URL into Other), and
   "Show me how to get it". If they pick show-me-how, explain: open the demo in
   demo-zone and copy the URL from the address bar — then ask again.
2. **Bearer token** — header "Token". Options: "Paste it now" (token typed into
   Other), "Already saved it", and "Show me how". Show-me-how steps: in Chrome on
   demo-zone, DevTools (⌘+⌥+I) → Network → click any `/api/v2/` request → Headers →
   copy the value after `Authorization: Bearer ` (starts with `eyJ…`).
3. **Channel** — header "Channel". Options: "Create a new channel", "Post to an
   existing channel" (which one → Other), following the naming convention below.
4. **Tone** — header "Tone". Options: "Strategic", "Casual", "Urgent",
   "Celebratory" (or Other).

**Then save the token immediately and non-interactively.** Never run bare `login`
(it hangs waiting for a keypress you can't send). Pipe it via stdin:
```bash
printf %s 'eyJ…the-token…' | python3 demo_upload.py login --stdin
```
A success message confirms the token is valid. (Or the user can save it themselves:
tell them to run `! python3 demo_upload.py login` and paste it, so it never appears in
a tool call.)

### Round 2 — audience + write mode (one AskUserQuestion call)

Ask only what's still relevant:

1. **Channel audience** *(only if creating a new channel)* — header "Invite".
   Options: "Everyone in the workspace" and "Only the people in the conversation".
   (This maps to `create-channel`: empty `--invite` invites everyone; listing
   usernames invites only those.)
2. **Write mode** — header "Mode". Options: "Append to the demo" (default) and
   "Replace existing messages" (`--replace`).

Once you have a saved token and the demo URL, continue. You may still draft and
preview a conversation before all of this — but collect credentials before the
channel-creation and upload steps.

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

If the channel doesn't exist in the workspace yet, create it (see Process step 7).

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
action. Include a `name` as a label, but note the upload **never renames an existing
demo** — it keeps the demo's current server-side name regardless of what you put here.
Omit `id`/`workspace_uid`; the CLI fills them from the `--url` you pass at upload time.

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

Follow this order exactly. The two rules people get wrong: **fetch the real roster
before writing any names**, and **preview in chat before writing any file**.

### 1. Intake
Complete **STEP 0** above via AskUserQuestion, and save the token.

### 2. Fetch the roster FIRST — never guess names
Before writing a single message, pull the real users and bots from the workspace so
you only ever use names that exist (guessing and failing on upload is not acceptable):
```bash
python3 demo_upload.py roster --url <demo-url>
```
Pick `sender` values from the USERNAME column and `fake_bot_id` values from the bot
NAME column. If the user named participants that aren't in the roster, tell them and
pick the closest real users (or ask) — do not invent usernames.

### 3. Decide the channel name
Use the user's channel choice from intake, or derive one with the `purpose-subject`
convention above. The JSON/MD files will be named after this channel.

### 4. Draft and PREVIEW in chat (before writing any file)
Compose the conversation and **show it to the user as a readable preview in the chat
first** — do not write files yet. A natural Slack flow:
- **Open** with context — a bot notification or scene-setting human message.
- **3–6 messages** carrying the narrative and the requested beats.
- **Threads** for side conversations / replies.
- **Bulk Reactions** on a few key messages (`thumbsup`, `fire`, `eyes`,
  `white_check_mark`, `rocket`).
- **Close** with next steps or a resolution.

Keep it Slack-natural, not a formal report. Use Slack bold (`*like this*`) for key
facts. All `delay: 0`. Use only roster names. Ask the user to confirm or request
edits. **Only once they approve do you move on to writing files.**

### 5. Write the files (after approval, before the network upload)
Name the files after the **channel**. Write `<channel-name>.json` (and optionally a
matching `<channel-name>.md` of the approved preview). Writing before the upload call
preserves the work if the token expires mid-flow.

### 6. Self-validate
```bash
python3 demo_upload.py validate <channel-name>.json
```
Fix anything it reports and re-run until it says OK.

### 7. Create the channel if it doesn't exist yet
Check existing channels, and create it if needed. Use the **audience** answer from
intake — omit `--invite` to invite everyone, or pass the participants' usernames to
invite only them (empty `invites` = everyone is the API's behavior):
```bash
python3 demo_upload.py channels --url <demo-url>
# everyone:
python3 demo_upload.py create-channel <channel-name> --url <demo-url>
# only participants:
python3 demo_upload.py create-channel <channel-name> --url <demo-url> --invite adam,jenny,frank
```

### 8. Dry-run, then upload
```bash
python3 demo_upload.py upload <channel-name>.json --url <demo-url> --dry-run
```
Show what would be sent; on confirmation, upload for real:
```bash
python3 demo_upload.py upload <channel-name>.json --url <demo-url>
```
Append is the default; add `--replace` only if the user chose replace in intake.

> **The demo's name is never changed.** The `name` in your JSON is just a label for
> the generated conversation; the upload preserves whatever the existing demo is
> already called. Do not try to rename a demo.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `validate` reports BOTH sender and fake_bot_id | Keep exactly one. |
| `referenced_client_uuid matches no client_uuid` | The parent's `client_uuid` is missing or misspelled. |
| `referenced_client_uuid is defined later` | Move the parent message earlier in the array. |
| `Unknown user/bot/channel` at upload | You skipped step 2 — run `roster --url <demo-url>` and use only real names. |
| Token expired / 401 | Re-save a fresh token: `printf %s '<token>' \| python3 demo_upload.py login --stdin`. |
| Duplicated conversation after re-upload | Uploads append; use `--replace` to overwrite instead. |
