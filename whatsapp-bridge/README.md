# Guardian WhatsApp bridge

A small Node.js/TypeScript transport using the open-source
[Baileys](https://github.com/WhiskeySockets/Baileys) library. It links as a WhatsApp
Web device, passes text (including local image OCR) to FastAPI, and sends
FastAPI's reply to the same sender.
**No Meta Cloud API, business account, webhook subscription, or Graph API token.**

```text
WhatsApp private text or image
  -> Baileys -> local Tesseract OCR for images -> two-minute sender buffer
  -> normalized GuardianMessage
  -> POST /api/bridge/messages
  -> existing Python signals + URL analysis + SerpApi + Gemma
  -> generated explanation and recommended action
  -> Baileys -> original WhatsApp sender
```

The bridge only handles WhatsApp transport, buffering, and local image-to-text
conversion. There is no Gemma, URL checking, SerpApi integration, or risk scoring
in this package. The backend endpoint is only an authenticated adapter around
the existing `MessageProcessor.process_with_analysis()` pipeline.

## Setup

Use Node.js **20.19+** and the existing Python environment. Baileys is pinned to
`7.0.0-rc14` (the npm latest release at implementation time); use the lockfile
rather than an unreviewed upgrade because its APIs and WhatsApp's protocol change.

Image OCR also needs the open-source **Tesseract CLI and English language data**
on the machine running the bridge. On Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng
tesseract --version
tesseract --list-langs   # must include eng
```

No paid OCR service, OCR API key, new npm package, or Python OCR dependency is
needed. If Tesseract is missing, ordinary text continues working; image events
carry an explicit OCR-unavailable indication instead of being dropped.

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

- Only new `messages.upsert` notifications and direct text/image messages are
  accepted. Phone-number JIDs and modern `@lid` identities are supported.
- Own messages, groups, broadcasts/statuses, channels, history backfills, other
  media (including image files sent as documents), empty text, and normal text
  over 4,096 JavaScript string units are ignored. Baileys normalizes message
  wrappers. Only accepted image messages are downloaded for local OCR.
- The normalized payload uses `message_id`, `sender_id` (the original chat JID),
  `text`, `received_at` (UTC bridge receipt time), and `source: "whatsapp"`.
- Each sender has an independent **two-minute inactivity buffer**. Every new,
  non-duplicate text or image resets only that sender's timer. When it expires, texts are
  joined in arrival order with `\n\n` and queued as one Guardian message, keeping
  the first message's ID and receipt time. Single messages also wait two minutes.
  Images reserve their position immediately, before asynchronous OCR, so a later
  text message cannot overtake a screenshot. If a batch still has pending OCR
  after two quiet minutes, flushing waits for that OCR; completion does not
  restart the inactivity timer. The buffer then clears for the next batch.
- Waiting buffers do not block other senders. Backend processing remains
  sequential through the existing queue. Queued batches and waiting sender
  buffers share the 100-slot limit; each buffer reserves its eventual queue slot.
  Recent IDs remain deduplicated for up to 24 hours / 2,000 entries, including
  during reconnects. When full, new batches are dropped with an operator notice.
- Buffering and flush logs show only the sender JID and message count, not text.
  FastAPI's existing 4,096-character payload limit still applies to the combined
  text, including separators. Oversized batches are not split or truncated:
  backend rejection triggers the existing availability notice.
- Replies are sent only to the original WhatsApp JID, never to a destination
  supplied by the backend or message text. Link previews are disabled.
- Backend requests time out after three minutes and are not automatically retried.
  API failures produce an explicit availability notice stating that **no risk
  assessment was generated**, not a fabricated safe/scam answer.
- A generated reply is kept if WhatsApp disconnects before sending, so reconnects
  do not rerun inference. An uncertain send failure is not blindly retried;
  recent sent messages are available to Baileys' own retry mechanism.
- Ctrl+C/SIGTERM clears buffer timers and unsent batches, cancels pending backend
  requests, aborts image download/OCR, waits for temporary-image cleanup, closes
  the socket without revoking the linked device, and waits for credential saves.

This is a single-process bridge, not a durable messaging system. Buffers, queues,
recent IDs, and reply caches do not survive a process restart; exactly-once delivery is
not guaranteed. A sender should resend if no reply arrives. Baileys advises a
proper database-backed authentication store instead of `useMultiFileAuthState`
for production deployments. The file-backed store here keeps the small bridge
simple; deploy with backups, restricted access, and a dedicated session.

## Image OCR and privacy

Images are downloaded via Baileys to a unique, owner-private `guardian-ocr-*`
directory under the OS temporary directory. Local Tesseract reads the file and
returns English text through stdout. The downloaded file and directory are
removed in `finally`, on success, no text, errors, and normal signal shutdown.
No image or OCR output file is saved in the repository or auth directory. Forced
termination (SIGKILL), a system crash, or filesystem permission failures can
prevent cleanup; do not back up temporary directories containing user media.

- One image is processed at a time to limit local CPU use, without blocking text
  reception or unrelated sender timers. Each image has a 60-second overall
  work deadline, a 45-second OCR subprocess timeout, and a 10 MiB download cap.
- Recognized content is buffered as `[Image OCR text]\n<extracted text>`. A caption,
  when present, follows as `[Image caption]\n<caption>`; it is not mislabeled as OCR.
- An empty/whitespace/punctuation-only OCR result is represented as an image with
  **no useful text detected**. Download/OCR failures are separately represented
  as `[Image OCR unavailable]` with unknown contents. Both still use the normal
  pipeline; neither is evidence that the image is safe.
- OCR text is not logged. Operator logs report extraction success, no useful
  text, or failure, plus the existing sender ID/message-count batch logs.
- The image itself never goes to FastAPI, SerpApi, or Gemma. Extracted text and
  captions do go through the existing text pipeline, including the configured
  inference provider. OCR is transcription only, not visual fraud detection.
- No extra URL extraction or rewriting occurs in Node. URLs that Tesseract
  recognizes go through exactly the same Python URL/signal/SerpApi/Gemma code
  as normal text. Use clear, upright screenshots; OCR may misread or split a URL.
  The existing extractor recognizes `http://`, `https://`, and `www.` prefixes,
  not bare domains. English is the only configured OCR language for now.
- The existing 4,096-character backend limit includes OCR labels, captions, and
  all texts in a batch. Oversized OCR/batches are not silently truncated; they
  use the existing backend-error availability notice.

### Manual screenshot check

1. Confirm Tesseract and `eng` are installed. Start FastAPI with the existing
   shared token, Gemma enabled, and SerpApi configured. Rebuild/restart the bridge:

   ```bash
   cd whatsapp-bridge
   npm run build
   npm start
   ```

2. From **another WhatsApp account**, make a clear screenshot of this text in a
   notes app (use a large font and keep the entire URL on one line):

   ```text
   URGENT: Your account will be suspended.
   Pay a $50 fee and share your OTP immediately.
   Verify here: https://example.com/verify
   ```

   `example.com` is a documentation domain; this is deliberately suspicious
   example wording, not a claim that the domain is malicious. No need to visit
   the link or include any real credentials.

3. Send it to the Guardian account as a **photo/image**, not a document or
   view-once item. Optionally send `Can you check this screenshot?` within two
   minutes to confirm mixed image/text batching. Stop sending and wait **two
   minutes after the last message**, then allow time for backend reasoning.

4. In the bridge terminal, look for `Image OCR completed: text extracted.` and
   `Flushed WhatsApp batch to queue: ... messages=1` (or `messages=2` with the
   follow-up text). In FastAPI, expect a URL verification lookup, a processing
   summary with `1 URL(s)` and suspicious signals, and a successful
   `POST /api/bridge/messages`. The bridge should report a reply submitted to
   WhatsApp, and the original sending account should receive Guardian's generated
   risk explanation and recommended action. The exact risk rating is not fixed.

5. Separately, send a blank image and wait another two quiet minutes. Expect
   `Image OCR completed: no useful text detected.` followed by a normal pipeline
   request and generated reply. No image should be retained after OCR completes.

If no URL is reported, try a sharper screenshot with the scheme and URL on a
single line. If OCR is unavailable, check `tesseract --list-langs`, media access,
and the documented size/time limits. A SerpApi warning or unavailable Gemma
assessment is a backend configuration/provider issue, not an OCR success.

## Backend contract

`POST /api/bridge/messages` requires `Authorization: Bearer <shared-token>` and
the normalized JSON message described above. FastAPI validates the shape and
calls the existing Python pipeline. A successful response contains:

- `message_id`: the original message ID, checked by the bridge.
- `reply`: a consistent `HIGH RISK` / `MEDIUM RISK` / `LOW RISK` heading, Gemma's
  `short_user_explanation`, and its `recommended_action`, formatted by Python.
  Gemma chooses English, Hindi (Devanagari), or Hinglish (Roman Hindi) from the
  full buffered message/OCR content. The explanation and action label match that
  choice; Node sends the reply unchanged. URL-only or sparse input defaults to
  English unless the batch provides language context. OCR language data and
  transport-error notices are unchanged.

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
