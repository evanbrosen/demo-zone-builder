# Demo Zone Builder

Generate realistic Slack demo conversations from a plain-English request and upload
them to [demo-zone.tinyspeck.com](https://demo-zone.tinyspeck.com).

It's two pieces:

- **A Claude Code skill** (`.claude/skills/demo-zone-builder/`) that turns a request
  like *"build an account channel for Acme — strategic, Adam/Jenny/Frank, Adam has
  unanswered requests"* into a schema-correct demo JSON, validates it, and drives the
  uploader for you.
- **A CLI** (`demo_upload.py`) — stdlib-only Python, no `pip install`. Handles token
  storage, name→ID resolution, validation, and upload.

> **Requirements:** macOS (token is stored in the login keychain) and Python 3.
> Access to a demo-zone workspace.

## Setup

```bash
git clone git@github.com:evanbrosen/demo-zone-builder.git
cd demo-zone-builder
```

Open the folder in Claude Code — the skill auto-loads from `.claude/skills/`.

## Quick start

### 1. Save a bearer token

Tokens expire after ~1 hour.

1. Open [demo-zone.tinyspeck.com](https://demo-zone.tinyspeck.com) in Chrome.
2. DevTools (⌘+⌥+I) → **Network** → click any request to `/api/v2/` → **Headers**.
3. Copy the value after `Authorization: Bearer ` (starts with `eyJ…`).
4. Save it:

```bash
python3 demo_upload.py login
```

### 2. Ask Claude to build a demo

> "Generate an account channel for Acme Corp. Strategic tone, reference an upcoming
> opportunity, use Adam, Jenny, and Frank, and make sure Adam has unanswered requests."

Claude asks for the demo URL and token first (and offers to show you how to get them
if you're unsure), then writes a JSON file named after the channel — e.g.
`acct-acme-corp.json` — plus an optional `.md` preview, validates it, shows a dry-run
of the final payload, and uploads once you confirm.

> **Channel naming:** channels (and the files) follow `purpose-subject` —
> `acct-acme-corp`, `help-laptops`, `announce-all`. If you don't name one, Claude
> picks a sensible name.

### 3. (Or do it by hand)

```bash
python3 demo_upload.py validate acct-acme-corp.json
python3 demo_upload.py upload  acct-acme-corp.json --url <demo-url> --dry-run
python3 demo_upload.py upload  acct-acme-corp.json --url <demo-url>
```

## Commands

```bash
python3 demo_upload.py login                                 # save/refresh token (keychain)
python3 demo_upload.py validate demo.json                    # check against the schema, no network
python3 demo_upload.py upload demo.json --url <demo-url>     # upload (appends to the demo)
python3 demo_upload.py upload demo.json --url <demo-url> --dry-run   # preview payload, no upload
python3 demo_upload.py upload demo.json --url <demo-url> --replace   # overwrite existing actions
python3 demo_upload.py list      --workspace <uid>           # list demos
python3 demo_upload.py users     --workspace <uid>           # list users
python3 demo_upload.py bots      --workspace <uid>           # list bots
python3 demo_upload.py channels  --workspace <uid>           # list channels
python3 demo_upload.py create-channel <name> --workspace <uid> --invite user1,user2
```

You pass **names**, not IDs — `sender`, `fake_bot_id`, and `channel` accept plain
usernames / bot names / channel names and the CLI resolves them. UUIDs and Slack
channel IDs are passed through untouched.

## How it works

- **Append by default.** Uploads add to the demo's existing actions; nothing is
  overwritten unless you pass `--replace`. Re-running without `--replace` duplicates.
- **Files first.** The skill writes JSON to disk before any network call, so a stale
  token never costs you the generated conversation.
- **Validation is local.** `validate` (and `upload`, automatically) checks type
  strings, sender/bot rules, thread reference integrity, reaction fields, and delay
  range *before* anything hits the API.
- **Token in the keychain.** Stored under the `demo-builder-cli` service; never written
  to disk in plaintext.

## The schema

`.claude/skills/demo-zone-builder/SCHEMA.md` is the `conversations_actions` reference,
maintained by the demo-zone dev team — the source of truth. The skill and the CLI
validator both follow it. Key points:

- Action types: `Message`, `Thread`, `Bulk Reaction`, `File`, `Invite Users`, `Reaction`.
- Every action has a `channel`. Use exactly one of `sender` / `fake_bot_id` on messages.
- `Thread` / `Bulk Reaction` reference a parent via `referenced_client_uuid`, which must
  point to a `client_uuid` defined earlier in the array.
- See `examples/` for a complete, valid demo (`.json`) and its readable preview (`.md`).

## Files

```
demo-zone-builder/
├── .claude/skills/demo-zone-builder/
│   ├── SKILL.md      # the skill Claude loads
│   └── SCHEMA.md     # demo-zone schema (source of truth)
├── demo_upload.py    # the CLI
├── examples/         # a valid demo + markdown preview
└── README.md
```
