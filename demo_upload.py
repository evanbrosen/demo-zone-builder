#!/usr/bin/env python3
"""
demo_upload.py — build and upload Slack demo scripts to demo-zone.tinyspeck.com

Standard-library only. macOS (token is stored in the login keychain).

COMMON COMMANDS:
  python3 demo_upload.py login                                        Save Bearer token to keychain
  python3 demo_upload.py validate demo.json                          Check a demo JSON against the schema (no network)
  python3 demo_upload.py upload demo.json --url <demo-url>           Upload a demo JSON file
  python3 demo_upload.py upload demo.json --url <demo-url> --dry-run Resolve + validate + preview, no PUT
  python3 demo_upload.py upload demo.json --url <demo-url> --replace Replace the demo's actions instead of appending
  python3 demo_upload.py channels --workspace <uid>                   List channels in a workspace
  python3 demo_upload.py create-channel deal-room --workspace <uid> --invite jennifer_hynes,jay_service
  python3 demo_upload.py users --workspace <uid>                      List users
  python3 demo_upload.py bots --workspace <uid>                       List bots
  python3 demo_upload.py list --workspace <uid>                       List existing demos

HUMAN-FRIENDLY UPLOAD FORMAT (the CLI resolves these to IDs for you):
  - "sender":      username (e.g. "jennifer_hynes") or TeamUser UID passthrough
  - "fake_bot_id": bot name (e.g. "Slackbot") or bot UID passthrough
  - "channel":     channel name (e.g. "deal-room") or Slack ID passthrough (e.g. "C0B2274JF98")
  - "client_uuid": omit to auto-generate (only safe on actions nothing references)
  - "id":          taken from --url; or include in the JSON to update an existing demo

GETTING A FRESH TOKEN (tokens expire ~1 hour):
  1. Open demo-zone.tinyspeck.com in Chrome
  2. DevTools -> Network -> any /api/v2/ request -> Headers
  3. Copy the value after "Authorization: Bearer "
  4. Run: python3 demo_upload.py login
"""

import argparse
import base64
import json
import re
import subprocess
import sys
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path

API_BASE         = "https://demo-zone.tinyspeck.com/api/v2"
KEYCHAIN_SERVICE = "demo-builder-cli"
KEYCHAIN_ACCOUNT = "token"

# Schema source of truth: .claude/skills/demo-zone-builder/SCHEMA.md
VALID_TYPES   = {"Message", "Thread", "Bulk Reaction", "File", "Invite Users", "Reaction"}
TYPES_NEED_TEXT   = {"Message", "Thread"}
TYPES_NEED_REF    = {"Thread", "Bulk Reaction", "Reaction"}
MAX_DELAY     = 300

# Common wrong type strings -> the value the schema actually wants. Used only to
# produce a more helpful validation error, never to silently rewrite input.
TYPE_HINTS = {
    "message": "Message", "post_message": "Message", "bot_message": "Message",
    "thread": "Thread", "thread_reply": "Thread",
    "reaction": "Reaction", "add_reaction": "Bulk Reaction",
    "bulk reaction": "Bulk Reaction",
}


def get_workspace_uid(override=None):
    if override:
        return override
    sys.exit("Workspace UID required. Pass --workspace <uid>.")


# -- Keychain ------------------------------------------------------------------

def keychain_save(token):
    subprocess.run(
        ["security", "delete-generic-password",
         "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT],
        capture_output=True,
    )
    subprocess.run(
        ["security", "add-generic-password",
         "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w", token],
        check=True, capture_output=True,
    )


def keychain_load():
    result = subprocess.run(
        ["security", "find-generic-password",
         "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


# -- JWT helpers ---------------------------------------------------------------

def jwt_exp(token):
    try:
        seg = token.split(".")[1]
        seg += "=" * (4 - len(seg) % 4)
        return json.loads(base64.urlsafe_b64decode(seg)).get("exp", 0)
    except Exception:
        return 0


def token_is_expired(token):
    exp = jwt_exp(token)
    return bool(exp) and time.time() > exp


def get_token():
    token = keychain_load()
    if not token:
        sys.exit("No token saved. Run:\n  python3 demo_upload.py login")
    if token_is_expired(token):
        sys.exit(
            "Token expired. Run:\n  python3 demo_upload.py login\n\n"
            "Get a fresh token: Chrome DevTools -> any /api/v2/ request -> Authorization header."
        )
    remaining = jwt_exp(token) - int(time.time())
    if remaining < 300:
        print(f"Warning: token expires in {remaining}s — consider refreshing soon.")
    return token


# -- HTTP helpers --------------------------------------------------------------

def api_get(path, token):
    req = urllib.request.Request(
        f"{API_BASE}/{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"API error {e.code} GET /{path}: {e.read().decode()}")


def api_post(path, payload, token):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{API_BASE}/{path}",
        data=body, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"API error {e.code} POST /{path}: {e.read().decode()}")


def api_put(path, payload, token):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{API_BASE}/{path}",
        data=body, method="PUT",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        if e.code == 401:
            sys.exit(f"401 Unauthorized. Run: python3 demo_upload.py login\n\n{body}")
        sys.exit(f"API error {e.code} PUT /{path}: {body}")


# -- User / bot / channel resolution ------------------------------------------

def load_users(workspace_uid, token):
    """Returns {username -> id, display_name_lower -> id, uuid -> uuid} mapping."""
    data = api_get(f"workspace/{workspace_uid}/users?include_connect_users=true", token)
    mapping = {}
    for u in data:
        uid = u.get("id")
        if not uid:
            continue
        username = (u.get("username") or "").lower()
        display  = (u.get("display_name") or "").lower()
        if username:
            mapping[username] = uid
        if display:
            mapping[display] = uid
        mapping[uid] = uid
    return mapping


def load_bots(workspace_uid, token):
    """Returns {bot_name_lower -> id, uuid -> uuid} mapping."""
    data = api_get(f"bots?workspace_id={workspace_uid}", token)
    mapping = {}
    for b in data:
        bid = b.get("id")
        if not bid:
            continue
        name = (b.get("name") or "").lower()
        if name:
            mapping[name] = bid
        mapping[bid] = bid
    return mapping


def load_channels(workspace_uid, token):
    """Returns {channel_name_lower -> id, slack_id -> slack_id} mapping."""
    data = api_get(f"workspace/{workspace_uid}/conversations", token)
    convos = data.get("conversations", data) if isinstance(data, dict) else data
    mapping = {}
    for c in convos:
        cid = c.get("id")
        if not cid:
            continue
        name = (c.get("name") or "").lower()
        if name:
            mapping[name] = cid
        mapping[cid] = cid
    return mapping


def _is_uuid(s):
    return bool(re.match(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", s, re.I
    ))


def _is_slack_channel_id(s):
    # Slack conversation IDs: C/G/D + 8-11 uppercase alphanumerics (e.g. C0B2274JF98).
    return bool(re.match(r"^[CGD][A-Z0-9]{6,}$", s))


def resolve(value, mapping, kind):
    if value is None:
        return None
    if _is_uuid(value) or _is_slack_channel_id(value):
        key = value
    else:
        key = value.lower()
    if key not in mapping:
        sys.exit(
            f"Unknown {kind}: '{value}'.\n"
            f"Run 'python3 demo_upload.py {kind}s --workspace <uid>' to see available options."
        )
    return mapping[key]


# -- Validation ----------------------------------------------------------------

def validate_demo(demo):
    """Validate against SCHEMA.md. Returns a list of human-readable error strings.

    Runs on the raw (pre-resolution) JSON, so it checks structure/relationships,
    not whether names exist in the workspace (that happens during resolve()).
    """
    errors = []
    actions = demo.get("conversations_actions")
    if actions is None:
        return ["Top-level 'conversations_actions' array is missing."]
    if not isinstance(actions, list):
        return ["'conversations_actions' must be an array."]

    # First pass: collect every client_uuid that is declared.
    declared = set()
    for a in actions:
        cu = a.get("client_uuid")
        if cu:
            declared.add(cu)

    # referenced_client_uuid must point to a client_uuid declared earlier (ordering matters).
    seen_so_far = set()

    for i, a in enumerate(actions):
        where = f"action[{i}]"
        if not isinstance(a, dict):
            errors.append(f"{where}: not an object.")
            continue

        atype = a.get("type", "Message")
        if atype not in VALID_TYPES:
            hint = TYPE_HINTS.get(str(atype).lower())
            suffix = f" Did you mean '{hint}'?" if hint else ""
            errors.append(f"{where}: invalid type '{atype}'. "
                          f"Allowed: {sorted(VALID_TYPES)}.{suffix}")

        if not a.get("channel"):
            errors.append(f"{where}: missing required 'channel'.")

        # Sender vs bot: never both. Message/Thread need exactly one.
        has_sender = bool(a.get("sender"))
        has_bot    = bool(a.get("fake_bot_id"))
        if has_sender and has_bot:
            errors.append(f"{where}: has BOTH 'sender' and 'fake_bot_id' — use exactly one.")
        if atype in TYPES_NEED_TEXT and not (has_sender or has_bot):
            errors.append(f"{where} ({atype}): needs a 'sender' or 'fake_bot_id'.")

        # Text required for Message/Thread.
        if atype in TYPES_NEED_TEXT and not (a.get("text") or "").strip():
            errors.append(f"{where} ({atype}): 'text' is required and must be non-empty.")

        # Reference integrity for types that point at a parent.
        ref = a.get("referenced_client_uuid")
        if atype in TYPES_NEED_REF:
            if not ref:
                errors.append(f"{where} ({atype}): missing 'referenced_client_uuid'.")
            elif ref not in declared:
                errors.append(f"{where} ({atype}): referenced_client_uuid '{ref}' "
                              f"matches no client_uuid in this demo.")
            elif ref not in seen_so_far:
                errors.append(f"{where} ({atype}): referenced_client_uuid '{ref}' "
                              f"is defined later — parents must come first.")

        # Bulk Reaction specifics.
        if atype == "Bulk Reaction":
            if not a.get("reaction_emoji"):
                errors.append(f"{where} (Bulk Reaction): missing 'reaction_emoji'.")
            count = a.get("reaction_count")
            if not isinstance(count, int) or count <= 0:
                errors.append(f"{where} (Bulk Reaction): 'reaction_count' must be an int > 0.")

        # Delay range (SCHEMA.md: 0-300).
        delay = a.get("delay", 0)
        if not isinstance(delay, int) or delay < 0 or delay > MAX_DELAY:
            errors.append(f"{where}: 'delay' must be an int between 0 and {MAX_DELAY}.")

        cu = a.get("client_uuid")
        if cu:
            seen_so_far.add(cu)

    return errors


# -- Demo preparation ----------------------------------------------------------

def prepare_demo(demo, users, bots, channels):
    """Resolve names -> IDs and fill missing client_uuids.

    Auto-generates a client_uuid only for actions that nothing references; if an
    action without a client_uuid is referenced by something, that's caught in
    validation (we can't invent a stable key after the fact).
    """
    actions = []
    for action in demo.get("conversations_actions", []):
        a = dict(action)

        if not a.get("client_uuid"):
            a["client_uuid"] = str(uuid.uuid4())

        if a.get("sender"):
            a["sender"] = resolve(a["sender"], users, "user")

        if a.get("fake_bot_id"):
            a["fake_bot_id"] = resolve(a["fake_bot_id"], bots, "bot")

        if a.get("channel"):
            a["channel"] = resolve(a["channel"], channels, "channel")

        actions.append(a)

    return {**demo, "conversations_actions": actions}


# -- Commands ------------------------------------------------------------------

def cmd_login():
    print("Paste your Bearer token (Chrome DevTools -> any /api/v2/ request -> Authorization header).")
    print("Starts with 'eyJ...'  Press Enter when done.\n")
    token = input("Token: ").strip()
    if token.startswith("Bearer "):
        token = token[len("Bearer "):]
    if not token.startswith("eyJ"):
        sys.exit("Doesn't look like a JWT — make sure you copied the full token.")
    if token_is_expired(token):
        sys.exit("That token is already expired. Grab a fresh one.")
    keychain_save(token)
    remaining = jwt_exp(token) - int(time.time())
    print(f"Token saved. Expires in ~{remaining // 60} minutes.")


def cmd_validate(json_path):
    path = Path(json_path)
    if not path.exists():
        sys.exit(f"File not found: {json_path}")
    try:
        demo = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON: {e}")
    errors = validate_demo(demo)
    n = len(demo.get("conversations_actions", []))
    if errors:
        print(f"{len(errors)} validation error(s) in {path.name} ({n} actions):\n")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    print(f"OK — {path.name} is valid ({n} actions).")


def cmd_users(workspace_uid):
    token = get_token()
    data = api_get(f"workspace/{workspace_uid}/users?include_connect_users=true", token)
    print(f"{len(data)} users in workspace {workspace_uid}\n")
    print(f"{'USERNAME':<30} {'DISPLAY NAME':<30} {'ID'}")
    print("-" * 90)
    for u in sorted(data, key=lambda x: x.get("username") or ""):
        print(f"{(u.get('username') or ''):<30} {(u.get('display_name') or ''):<30} {u.get('id', '')}")


def cmd_bots(workspace_uid):
    token = get_token()
    data = api_get(f"bots?workspace_id={workspace_uid}", token)
    print(f"{len(data)} bots in workspace {workspace_uid}\n")
    print(f"{'NAME':<40} {'STOCK':<8} {'ID'}")
    print("-" * 90)
    for b in sorted(data, key=lambda x: (x.get("name") or "").lower()):
        stock = "yes" if b.get("is_stock_bot") else "no"
        print(f"{(b.get('name') or ''):<40} {stock:<8} {b.get('id', '')}")


def cmd_channels(workspace_uid):
    token = get_token()
    raw = api_get(f"workspace/{workspace_uid}/conversations", token)
    data = raw.get("conversations", raw) if isinstance(raw, dict) else raw
    print(f"{len(data)} channels in workspace {workspace_uid}\n")
    print(f"{'NAME':<35} {'PRIVATE':<10} {'ID'}")
    print("-" * 70)
    for c in sorted(data, key=lambda x: x.get("name") or ""):
        private = "yes" if c.get("private") else "no"
        print(f"{(c.get('name') or ''):<35} {private:<10} {c.get('id', '')}")


def cmd_create_channel(workspace_uid, name, invites, is_private=False):
    token = get_token()
    # Resolve invite names -> user IDs (passthrough for anything already an ID).
    if invites:
        users = load_users(workspace_uid, token)
        invites = [resolve(i, users, "user") for i in invites]
    payload = {
        "name": name,
        "topic": "",
        "purpose": "",
        "invites": invites,
        "is_private": is_private,
        "is_shared": False,
    }
    print(f"Creating channel #{name}…")
    result = api_post(f"workspace/{workspace_uid}/conversation", payload, token)
    if not result.get("ok"):
        errors = result.get("errors", result)
        sys.exit(f"Channel creation failed: {errors}")
    print(f"Created: #{name} -> {result['id']}")


def cmd_list(workspace_uid):
    token = get_token()
    data = api_get(f"demos?workspace_uid={workspace_uid}", token)
    demos = data if isinstance(data, list) else data.get("demos", [])
    if not demos:
        print("No demos found.")
        return
    print(f"{'NAME':<45} {'ID'}")
    print("-" * 90)
    for d in sorted(demos, key=lambda x: x.get("name", "").lower()):
        print(f"{d.get('name', ''):<45} {d['id']}")


def extract_demo_id(url):
    """Pull the UUID out of a demo-zone URL."""
    m = re.search(
        r"demo-builder/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        url, re.I,
    )
    if not m:
        sys.exit(f"Could not extract a demo ID from URL: {url}")
    return m.group(1)


def cmd_upload(json_path, workspace_uid=None, demo_url=None, dry_run=False, replace=False):
    path = Path(json_path)
    if not path.exists():
        sys.exit(f"File not found: {json_path}")
    try:
        demo = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON: {e}")

    # Validate the raw JSON before doing anything else.
    errors = validate_demo(demo)
    if errors:
        print(f"{len(errors)} validation error(s) — fix these before uploading:\n")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    # URL flag overrides any id in the JSON.
    if demo_url:
        demo["id"] = extract_demo_id(demo_url)
    if not demo.get("id"):
        sys.exit(
            "No demo ID found. Pass the demo-zone URL with --url, e.g.:\n"
            "  python3 demo_upload.py upload demo.json --url https://demo-zone.tinyspeck.com/demo-builder/<id>"
        )

    token = get_token()

    # workspace_uid: explicit flag > JSON > fetched from the existing demo.
    print(f"Fetching existing demo {demo['id']}…")
    existing = api_get(f"demos/{demo['id']}", token)
    workspace_uid = (workspace_uid or demo.get("workspace_uid")
                     or existing.get("workspace_uid"))
    if not workspace_uid:
        sys.exit("Could not determine workspace_uid. Pass --workspace <uid>.")
    demo["workspace_uid"] = workspace_uid

    print("Fetching workspace data…")
    users    = load_users(workspace_uid, token)
    bots     = load_bots(workspace_uid, token)
    channels = load_channels(workspace_uid, token)

    prepared = prepare_demo(demo, users, bots, channels)

    existing_actions = existing.get("conversations_actions", [])
    new_actions = prepared["conversations_actions"]
    if replace:
        prepared["conversations_actions"] = new_actions
        print(f"Replacing {len(existing_actions)} existing action(s) with {len(new_actions)} new.")
    else:
        prepared["conversations_actions"] = existing_actions + new_actions
        print(f"Appending {len(new_actions)} new action(s) to {len(existing_actions)} existing.")

    if dry_run:
        print("\n--- DRY RUN: payload that WOULD be sent (no PUT performed) ---")
        print(json.dumps(prepared, indent=2))
        print(f"\nDry run complete. {len(prepared['conversations_actions'])} total actions. Nothing uploaded.")
        return

    print(f"Uploading {path.name} ({len(prepared['conversations_actions'])} total actions)…")
    result = api_put("demos", prepared, token)
    print("Upload successful.")
    print(f"  Demo ID: {result['id']}")
    print(f"  URL:     https://demo-zone.tinyspeck.com/demo-builder/{result['id']}")


# -- CLI -----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Build and upload Slack demo scripts to demo-zone.tinyspeck.com",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="Save Bearer token to keychain")

    va = sub.add_parser("validate", help="Validate a demo JSON against the schema (no network)")
    va.add_argument("file", help="Path to demo JSON file")

    up = sub.add_parser("upload", help="Upload a demo JSON file")
    up.add_argument("file", help="Path to demo JSON file")
    up.add_argument("--url", help="demo-zone demo URL (sets the demo ID)")
    up.add_argument("--workspace", help="Workspace UID (overrides workspace_uid in JSON)")
    up.add_argument("--dry-run", action="store_true",
                    help="Resolve + validate + print the final payload; do not upload")
    up.add_argument("--replace", action="store_true",
                    help="Replace the demo's actions instead of appending to them")

    u = sub.add_parser("users", help="List users in a workspace")
    u.add_argument("--workspace", required=True, help="Workspace UID")

    b = sub.add_parser("bots", help="List bots in a workspace")
    b.add_argument("--workspace", required=True, help="Workspace UID")

    ch = sub.add_parser("channels", help="List channels in a workspace")
    ch.add_argument("--workspace", required=True, help="Workspace UID")

    cc = sub.add_parser("create-channel", help="Create a new channel in a workspace")
    cc.add_argument("name", help="Channel name (no #)")
    cc.add_argument("--workspace", required=True, help="Workspace UID")
    cc.add_argument("--invite", help="Comma-separated usernames to invite", default="")
    cc.add_argument("--private", action="store_true", help="Make the channel private")

    ls = sub.add_parser("list", help="List existing demos in a workspace")
    ls.add_argument("--workspace", required=True, help="Workspace UID")

    args = parser.parse_args()

    if args.command == "login":
        cmd_login()
    elif args.command == "validate":
        cmd_validate(args.file)
    elif args.command == "upload":
        cmd_upload(args.file, workspace_uid=args.workspace, demo_url=args.url,
                   dry_run=args.dry_run, replace=args.replace)
    elif args.command == "users":
        cmd_users(args.workspace)
    elif args.command == "bots":
        cmd_bots(args.workspace)
    elif args.command == "channels":
        cmd_channels(args.workspace)
    elif args.command == "create-channel":
        invites = [i.strip() for i in args.invite.split(",") if i.strip()]
        cmd_create_channel(args.workspace, args.name, invites, is_private=args.private)
    elif args.command == "list":
        cmd_list(args.workspace)


if __name__ == "__main__":
    main()
