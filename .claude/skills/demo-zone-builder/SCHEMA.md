# Demo Zone: `conversations_actions` Payload Reference
## Endpoint
`POST /api/v2/demos` (create) or `PUT /api/v2/demos` (update)
## Top-Level Fields
| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `name` | string | Yes | Demo name |
| `description` | string | No | |
| `shared` | boolean | No | Default: `false` |
| `workspace_uid` | string | Yes | Target workspace ID |
| `tags` | string[] | No | List of tag IDs |
| `conversations_actions` | array | No | Array of action objects (see below) |
## Each `conversations_actions[]` Element
| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `channel` | string | Yes | Slack channel ID (e.g. `C123456789`) |
| `client_uuid` | string | No | Your own UUID for cross-referencing actions |
| `delay` | int | No | 0-300 seconds between actions. Default: `0` |
| `type` | string | No | Default: `"Message"`. One of: `"Message"`, `"Thread"`, `"Bulk Reaction"`, `"File"`, `"Invite Users"`, `"Reaction"` |
| `sender` | string | No | TeamUser UID (the user sending the message) |
| `fake_bot_id` | string | No | FakeBot ID (mutually exclusive with `sender`) |
| `text` | string | No | Message content (required for Message/Thread types) |
| `referenced_client_uuid` | string | No | Points to another action's `client_uuid` (required for Thread/Reaction types) |
| `reaction_emoji` | string | No | Emoji name without colons (for Bulk Reaction type) |
| `reaction_count` | int | No | Number of reactions (for Bulk Reaction type) |
## Validation Rules
1. **Sender vs Bot**: An action needs either `sender` OR `fake_bot_id`, never both.
2. **Message/Thread**: Must have `text` + a valid sender or bot.
3. **Bulk Reaction**: Must have `reaction_emoji`, `reaction_count > 0`, and a valid `referenced_client_uuid`.
4. **Thread**: `referenced_client_uuid` must point to an existing action's `client_uuid` in the same batch.
5. **Channel**: Must exist in the workspace and not be deleted.
6. **Sender UID**: Must be a valid TeamUser in the workspace.
7. **Delay**: Must be between 0 and 300 seconds.
## Example Payload
```json
{
  "name": "Sales Demo",
  "workspace_uid": "workspace-123",
  "conversations_actions": [
    {
      "channel": "C123456789",
      "client_uuid": "msg-1",
      "type": "Message",
      "sender": "team-user-uid-001",
      "text": "Hey team, check out this new feature!",
      "delay": 0
    },
    {
      "channel": "C123456789",
      "client_uuid": "thread-1",
      "type": "Thread",
      "sender": "team-user-uid-002",
      "text": "This looks great, tell me more",
      "referenced_client_uuid": "msg-1",
      "delay": 3
    },
    {
      "channel": "C123456789",
      "client_uuid": "reaction-1",
      "type": "Bulk Reaction",
      "referenced_client_uuid": "msg-1",
      "reaction_emoji": "thumbsup",
      "reaction_count": 5,
      "delay": 2
    },
    {
      "channel": "C123456789",
      "client_uuid": "bot-msg-1",
      "type": "Message",
      "sender": null,
      "fake_bot_id": "fake-bot-id-456",
      "text": "Automated notification from integration",
      "delay": 8
    }
  ]
}
```
## Tips
- **Ordering matters**: Actions execute in array order. Make sure parent messages come before their threads/reactions.
- **`client_uuid` is the linchpin**: It's how threads and reactions reference their parent messages within the same batch. Every `referenced_client_uuid` must point to a `client_uuid` that appears earlier in the array.
- **Finding valid sender UIDs**: Use `GET /api/v2/org/{workspace_uid}/team-users` to list available TeamUser UIDs for a workspace.
- **Finding valid channels**: Use `GET /api/v2/org/{workspace_uid}/conversations` to list channels in the workspace.
- **Finding fake bots**: Use `GET /api/v2/org/{workspace_uid}/fake-bots` to list available bots.