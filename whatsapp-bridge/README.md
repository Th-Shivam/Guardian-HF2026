# Guardian WhatsApp bridge

A small Node.js/TypeScript transport using the open-source
[Baileys](https://github.com/WhiskeySockets/Baileys) library. It links as a WhatsApp
Web device, passes text to FastAPI, and sends FastAPI's reply to the same sender.
**No Meta Cloud API, business account, webhook subscription, or Graph API token.**

```text
WhatsApp private text
  -> Baileys -> normalized GuardianMessage
  -> POST /api/bridge/messages
  -> existing Python signals + URL analysis + SerpApi + Gemma
  -> generated explanation and recommended action
  -> Baileys -> original WhatsApp sender
```

There is no AI, URL checking, SerpApi integration, or risk scoring in this package.
The backend endpoint is only an authenticated adapter around the existing
`MessageProcessor.process_with_analysis()` pipeline.

## Setup

Use Node.js **20.19+** and the existing Python environment. Baileys is pinned to
`7.0.0-rc14` (the npm latest release at implementation time); use the lockfile
rather than an unreviewed upgrade because its APIs and WhatsApp's protocol change.

1. Copy the root `.env.example` to `.env` if you have not already done so. Do not
   replace an existing `.env`. Add these three bridge settings:

   ```dotenv
   WHATSAPP_BACKEND_URL=http://127.0.0.1:8000
   GUARDIAN_WHATSAPP_BRIDGE_TOKEN=<a-random-secret-of-at-least-32-characters>
   WHATSAPP_PAIRING_PHONE=
   ```

   Generate the shared token using `openssl rand -hex 32`. Both processes read
   the same root `.env`, regardless of the bridge's working directory. Exported
   environment variables take precedence. Use HTTPS for a remote backend; HTTP
   is permitted only on loopback. Keep the token private and never put it in a URL.

2. Enable and configure Gemma using the existing `GUARDIAN_GEMMA_*` settings.
   Set `GUARDIAN_SERPAPI_API_KEY` for live search evidence. The bridge does not
   need either provider key itself; only the Python backend calls those APIs.

3. Start FastAPI from the repository root:

   ```bash
   source .venv/bin/activate
   uvicorn app.main:app --reload --app-dir backend
   ```

4. In another terminal:

   ```bash
   cd whatsapp-bridge
   npm ci
   npm run build
   npm start
   ```

   For development, `npm run dev` runs the TypeScript entrypoint without a build.
   Run **one bridge process per WhatsApp account/auth directory**, not both commands
   simultaneously. No frontend is required.

## Log in

### QR code (default)

Leave `WHATSAPP_PAIRING_PHONE` empty. Scan the terminal QR with WhatsApp on the
account you want Guardian to use: **Settings → Linked devices → Link a device**.
Use a dedicated account and tell correspondents their forwarded messages will be
processed by Guardian and its configured inference/search providers.

### Pairing code

Set `WHATSAPP_PAIRING_PHONE` to the account's number, with country code and digits
only (no `+`, spaces, or punctuation), then start the bridge. On the phone select
**Linked devices → Link a device → Link with phone number instead**, and enter
the code printed in the terminal. Code requests wait for Baileys' QR/ready event.
This is WhatsApp Web pairing, not the WhatsApp mobile registration API.

Once linked, both modes reuse `whatsapp-bridge/.auth/`. QR/pairing codes and that
folder contain authentication secrets. The folder is gitignored, created with
owner-only permissions on POSIX, and contains Signal keys as well as credentials.
Do not commit, share, or upload it. On Windows, protect it with appropriate ACLs.

Transient disconnections reconnect with backoff; the post-pairing restart is
handled automatically. Logout, invalid sessions, forbidden connections, and a
connection replaced by another instance stop the bridge instead of reconnecting
forever. To deliberately relink, stop the bridge, review/remove its linked device
on the phone, move the old `.auth/` folder to a secure location, and start again.
The bridge never deletes credentials or logs out the account automatically.

## Message handling

- Only new `messages.upsert` notifications and direct text messages are accepted.
  Phone-number JIDs and modern `@lid` identities are supported.
- Own messages, groups, broadcasts/statuses, channels, history backfills, media,
  empty text, and text over 4,096 JavaScript string units are ignored. Ephemeral
  text wrappers are normalized by Baileys; media is not downloaded.
- The normalized payload uses `message_id`, `sender_id` (the original chat JID),
  `text`, `received_at` (UTC bridge receipt time), and `source: "whatsapp"`.
- Processing is sequential with a queue capped at 100 messages. Recent IDs are
  deduplicated in memory for up to 24 hours / 2,000 entries, including during
  reconnects. Full queues drop new messages with an operator notice.
- Replies are sent only to the original WhatsApp JID, never to a destination
  supplied by the backend or message text. Link previews are disabled.
- Backend requests time out after three minutes and are not automatically retried.
  API failures produce an explicit availability notice stating that **no risk
  assessment was generated**, not a fabricated safe/scam answer.
- A generated reply is kept if WhatsApp disconnects before sending, so reconnects
  do not rerun inference. An uncertain send failure is not blindly retried;
  recent sent messages are available to Baileys' own retry mechanism.
- Ctrl+C/SIGTERM cancels pending backend requests, closes the socket without
  revoking the linked device, and waits for queued credential saves.

This is a single-process bridge, not a durable messaging system. Queues, recent
IDs, and reply caches do not survive a process restart; exactly-once delivery is
not guaranteed. A sender should resend if no reply arrives. Baileys advises a
proper database-backed authentication store instead of `useMultiFileAuthState`
for production deployments. The file-backed store here keeps the small bridge
simple; deploy with backups, restricted access, and a dedicated session.

## Backend contract

`POST /api/bridge/messages` requires `Authorization: Bearer <shared-token>` and
the normalized JSON message described above. FastAPI validates the shape and
calls the existing Python pipeline. A successful response contains:

- `message_id`: the original message ID, checked by the bridge.
- `reply`: estimated risk, Gemma's `short_user_explanation`, and its
  `recommended_action`, formatted by Python.

The endpoint does not echo the original text or raw search evidence. Invalid
credentials return 401; an unset/short backend token or unavailable Gemma
assessment returns 503; malformed messages return 422. Keep this endpoint
private where possible; the shared secret is not a substitute for network access
controls or deployment-level rate limits. Do not expose the unencrypted local
backend directly to the internet. The old webhook adapter is not part of this
flow and requires no configuration.

## Costs and responsible use

Baileys is free/open-source and avoids Meta Cloud API transport fees. **It does
not make SerpApi, hosted Gemma, or hosting free.** Baileys is unofficial and not
affiliated with WhatsApp. Automated use may violate WhatsApp's terms and can
result in account restrictions. Use it only for consenting users; no spam, bulk
messaging, scraping, or unsolicited outreach.

References: [quickstart](https://baileys.wiki/quickstart),
[pairing codes](https://baileys.wiki/authentication/pairing-code), and
[session-management limitations](https://baileys.wiki/authentication/session-management).
