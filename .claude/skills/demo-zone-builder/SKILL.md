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

You own the whole flow. The user describes what they want; you generate the JSON,
preview it, and drive `demo_upload.py` to upload it. The user should never have to
hand-write JSON or copy-paste CLI invocations unless they want to.

## Files in this skill

- `SCHEMA.md` — the demo-zone `conversations_actions` schema. **This is the source
  of truth, maintained by the demo-zone dev team.** When in doubt, read it.
- `../../../demo_upload.py` — the CLI that validates, resolves names→IDs, and uploads.
  (Repo root; path is relative to this skill file.)

Always read `SCHEMA.md` before generating if you are unsure about a field.

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
action. Include `name`. Omit `id`/`workspace_uid`; the CLI fills them from the
`--url` you pass at upload time.

## Action rules (must follow — these mirror SCHEMA.md)

**Exact type strings:** `"Message"`, `"Thread"`, `"Bulk Reaction"`, `"File"`,
`"Invite Users"`, `"Reaction"`. Never `post_message`, `thread_reply`, etc.

**Exact field names:** `channel`, `client_uuid`, `referenced_client_uuid`, `sender`,
`fake_bot_id`, `text`, `reaction_emoji`, `reaction_count`, `delay`.

**Per-action requirements:**
- Every action has a `channel` (the channel name, e.g. `"acme-corp-account"`).
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
    { "type": "Message", "channel": "acme-corp-account", "client_uuid": "msg-1",
      "fake_bot_id": "Service Cloud for Slack",
      "text": "Account opened: Acme Corp — $2M opportunity", "delay": 0 },
    { "type": "Message", "channel": "acme-corp-account", "client_uuid": "msg-2",
      "sender": "adam",
      "text": "Reviewed the contract — need legal on section 3.2 before we move.",
      "delay": 0 },
    { "type": "Thread", "channel": "acme-corp-account", "client_uuid": "thread-1",
      "sender": "jenny", "referenced_client_uuid": "msg-2",
      "text": "On it — legal feedback by EOD.", "delay": 0 },
    { "type": "Bulk Reaction", "channel": "acme-corp-account",
      "referenced_client_uuid": "msg-2", "reaction_emoji": "fire",
      "reaction_count": 3, "delay": 0 }
  ]
}
```

## Process

### 1. Understand the request
Pull out: account/company, tone (strategic, urgent, casual, celebratory…),
participants, channel name (infer one, e.g. `acme-corp-account`), and any specific
beats ("unanswered requests", "reference an opportunity", "show a timeline"). If a
critical detail is missing and you can't pick a sensible default, ask — otherwise
proceed and state the assumptions you made.

### 2. Generate the conversation
Write a natural Slack flow:
- **Open** with context — a bot notification or scene-setting human message.
- **3–6 messages** carrying the narrative and the requested beats.
- **Threads** for side conversations / replies.
- **Bulk Reactions** on a few key messages (`thumbsup`, `fire`, `eyes`,
  `white_check_mark`, `rocket`).
- **Close** with next steps or a resolution.
Keep it Slack-natural, not a formal report. Use Slack bold (`*like this*`) for key
facts. All `delay: 0`.

### 3. Write the files (before any network call)
Write the JSON to `<channel_name>.json` in the working directory **first** — this
preserves the work even if the token has expired. Optionally also write a readable
`<channel_name>.md` preview (top-level messages flush left; threads and reactions
indented two spaces). Keep the `.md` and `.json` in sync if you write both.

### 4. Self-validate
Run the validator (no network, catches schema mistakes locally):
```bash
python3 demo_upload.py validate <channel_name>.json
```
Fix anything it reports and re-run until it says OK.

### 5. Make sure the user is logged in
Check / refresh the token:
```bash
python3 demo_upload.py login   # only if needed; tokens last ~1 hour
```
If the user hasn't given you a demo URL yet, ask for it now (it carries the demo ID
and lets the CLI resolve the workspace).

### 6. Preview the final payload (dry run), then upload
```bash
python3 demo_upload.py upload <channel_name>.json --url <demo-url> --dry-run
```
Show the user what would be sent. When they confirm, upload for real:
```bash
python3 demo_upload.py upload <channel_name>.json --url <demo-url>
```
Uploads **append** by default. If the user wants to overwrite the demo's existing
actions, add `--replace`.

### 7. If a channel doesn't exist yet
```bash
python3 demo_upload.py create-channel <name> --workspace <uid> --invite adam,jenny,frank
```
Get the workspace UID from a `list`/`users` call or from the user.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `validate` reports BOTH sender and fake_bot_id | Keep exactly one. |
| `referenced_client_uuid matches no client_uuid` | The parent's `client_uuid` is missing or misspelled. |
| `referenced_client_uuid is defined later` | Move the parent message earlier in the array. |
| `Unknown user/bot/channel` at upload | Run `users` / `bots` / `channels --workspace <uid>` to see valid names. |
| Token expired / 401 | `python3 demo_upload.py login` with a fresh token. |
| Duplicated conversation after re-upload | Uploads append; use `--replace` to overwrite instead. |
