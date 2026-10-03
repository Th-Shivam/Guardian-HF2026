# Guardian WhatsApp bridge

A small Node.js/TypeScript transport using the open-source
[Baileys](https://github.com/WhiskeySockets/Baileys) library. It links as a WhatsApp
Web device, passes text (including local image OCR and ElevenLabs voice
transcriptions) to FastAPI, and sends FastAPI's reply to the same sender.
**No Meta Cloud API, business account, webhook subscription, or Graph API token.**

```text
WhatsApp private text, image, or voice/audio
  -> Baileys -> local Tesseract OCR / ElevenLabs STT -> two-minute sender buffer
  -> normalized GuardianMessage
  -> POST /api/bridge/messages
  -> existing Python signals + URL analysis + SerpApi + Gemma
  -> generated explanation and recommended action
  -> Baileys -> original WhatsApp sender
```

The bridge only handles WhatsApp transport, buffering, local image-to-text
conversion, and ElevenLabs speech-to-text. There is no Gemma, URL checking, SerpApi integration, or risk scoring
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
   For voice notes/audio attachments, also add these to the **root** `.env`:

   ```dotenv
   ELEVENLABS_API_KEY=<your-real-elevenlabs-key-with-speech-to-text-access>
   ELEVENLABS_STT_MODEL=scribe_v2
   ```

   `scribe_v2` is ElevenLabs' current recommended uploaded-recording model, not
   the realtime WebSocket model. Restart the bridge after changing these values.
   An empty key leaves text/images working; voice messages receive an availability
   notice. The key is used only by Node and must never be placed in a `VITE_`
   variable. No ElevenLabs SDK, extra npm dependency, or other STT provider is used.

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
processed by Guardian and its configured inference/search providers, and that
voice recordings are uploaded to ElevenLabs for transcription.

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

- Only new `messages.upsert` notifications and direct text/image/voice/audio messages
  are accepted. Phone-number JIDs and modern `@lid` identities are supported.
- Own messages, groups, broadcasts/statuses, channels, history backfills, other
  media (including images/audio sent as documents), empty text, and normal text
  over 4,096 JavaScript string units are ignored. Baileys normalizes message
  wrappers. Only accepted images/audio are downloaded for OCR/STT.
- The normalized payload uses `message_id`, `sender_id` (the original chat JID),
  `text`, `received_at` (UTC bridge receipt time), and `source: "whatsapp"`.
- Each sender has an independent **two-minute inactivity buffer**. Every new,
  non-duplicate text, image, or voice/audio resets only that sender's timer. When
  it expires, texts are joined in arrival order with `\n\n` and queued as one
  Guardian message, keeping the first message's ID and receipt time. Single
  messages also wait two minutes. Images and audio reserve their positions
  immediately, before asynchronous OCR/STT, so later text cannot overtake them.
  If a batch still has pending OCR/STT after two quiet minutes, flushing waits
  for it; completion does not restart the inactivity timer. The buffer then
  clears for the next batch.
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
  requests, aborts media download/OCR/STT, waits for temporary-image/audio cleanup,
  closes the socket without revoking the linked device, and waits for credential saves.

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

## Voice transcription and privacy

Voice notes (PTT) and ordinary WhatsApp audio attachments use **only ElevenLabs**:
`POST https://api.elevenlabs.io/v1/speech-to-text`, authenticated with the
`xi-api-key` header. The original audio is uploaded as multipart data using the
configured model. Language is automatically detected; the bridge does not force
English, translate, transliterate, or rewrite spoken URLs. Hindi/English/code-
switching are retained as recognized by Scribe. Hinglish spelling/script and
code-switching accuracy depend on STT; the existing Gemma prompt chooses the
reply language from the resulting batch, not the audio itself.

- Successful content is buffered as `[Voice transcription]\n<transcript>` and
  follows exactly the existing signals, URL extraction, SerpApi, and Gemma path.
  No new classifier, risk decision, or model call is added to that path.
- Audio is downloaded to an owner-private `guardian-voice-*` OS temporary
  directory, not the repository, auth directory, or a permanent recording store.
  The file/directory are removed in `finally` after success, empty results, API
  errors, and normal signal shutdown. SIGKILL, system crashes, or filesystem
  failures can prevent cleanup; do not back up these temporary directories.
- Only the transcription goes to FastAPI/Gemma, not the recording. **Audio does
  leave the machine for ElevenLabs.** Local deletion does not guarantee deletion
  at ElevenLabs: its provider/account retention policies apply. The API's zero-
  retention option is enterprise-only and is not enabled by this integration.
- Each recording has a **10 MiB download cap** and a **120-second overall work
  deadline** once its turn starts. STT runs one recording at a time, separately
  from OCR, without blocking incoming text or other sender timers. A busy STT
  queue can extend a voice batch beyond its two-minute inactivity period.
- Empty, whitespace/punctuation-only, invalid, or failed transcripts never become
  fabricated evidence. The batch gets a friendly English transport notice asking
  for clearer audio/text or a later retry. If nothing readable remains, no backend
  risk assessment is requested. In mixed batches, other content is assessed
  normally and a voice-failure notice is appended; the backend's formatted reply
  itself is unchanged. Text and image handling continue after STT failures.
- Keys, audio, transcripts, and provider error bodies are not logged. Diagnostics
  show success or a sanitized error (for example HTTP status). Transcripts and
  their labels count toward the existing 4,096-character combined backend limit.

### Manual voice checks

These are manual steps, not an automated test suite. Use synthetic content only;
no real OTPs, passwords, payment requests, or suspicious live links are needed.

1. Set `ELEVENLABS_API_KEY` and `ELEVENLABS_STT_MODEL=scribe_v2` in the root `.env`.
   Keep the existing shared bridge token, real SerpApi key, and enabled/configured
   Gemma settings. Start FastAPI from the repository root:

   ```bash
   source .venv/bin/activate
   python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
   ```

2. In another terminal, rebuild/start the bridge and pair it if necessary:

   ```bash
   cd whatsapp-bridge
   npm run build
   npm start
   ```

   Wait for `WhatsApp connected. Waiting for private text, image, and voice messages.`
   Use **another WhatsApp account** to send to Guardian's account; own messages
   are ignored. Use the WhatsApp microphone for each recording below. Send each
   language example as a **separate batch**: after each note, stop sending for
   two minutes, allow additional STT/backend time, and wait for the reply before
   starting the next example.

3. **English:** record: “Someone says my bank account will be blocked today unless
   I send them my one-time password. Should I share it?” Expect an English
   risk explanation and safe action, not an instruction to share a code.

4. **Hindi:** record: “मुझे फोन आया कि मेरा बैंक खाता आज बंद हो जाएगा। उसे बचाने
   के लिए वे मेरा गुप्त कोड माँग रहे हैं। क्या मुझे उन्हें यह कोड देना चाहिए?”
   Expect Hindi advice and the `क्यों` / `क्या करें` headings when the transcript
   is recognized as Hindi. No English language override is sent to ElevenLabs.

5. **Hinglish:** record: “Mujhe ek message mila hai. They say my bank account will
   be blocked today. OTP share karne ko bol rahe hain. Should I trust this message?”
   Expect Hinglish advice (`Kyun` / `Kya karein`) when STT retains the meaningful
   English/Hindi mix. A wholly Hindi-rendered transcript can lead to a Hindi reply;
   the bridge deliberately does not force Romanization or translation.

6. **Scam wording with a spoken URL:** record: “Urgent! Your account will close
   today. Open H T T P S colon slash slash example dot com slash verify, pay fifty
   dollars, and send your OTP now.” `example.com` is a documentation domain, not
   a claim of maliciousness. Expect an assessment of the pressure/payment/OTP
   wording, with no predetermined risk rating. If STT produces the literal
   `https://example.com/verify`, FastAPI should report `1 URL(s)` and a SerpApi
   lookup. Speech may instead produce words such as “example dot com”; those are
   **not rewritten into URLs**. To check the URL path reliably, repeat the note
   in a fresh batch and send `https://example.com/verify` as text within two
   minutes. Stop sending; expect one batch with `messages=2` and a URL lookup.

7. **Mixed ordering:** in a fresh batch send, in this order, a voice note saying
   “First, someone requested a payment,” the text `Second, please check this`,
   a clear screenshot saying `Third: never share an OTP`, and another voice note
   saying “Fourth, should I verify through the official bank app?” Keep gaps
   below two minutes, then wait two quiet minutes. Expect a single `messages=4`
   flush after all OCR/STT completes and one normal Guardian assessment. For an
   exact payload-order check, inspect `job.message.text` at `requestReply` in a
   local debugger: voice → text → image OCR → voice, with the documented labels.
   Do not add permanent transcript/payload logging.

8. **Unclear audio and API failure:** separately send a few seconds of silence.
   If STT returns no usable speech, expect a friendly request for clearer audio
   or text, not a LOW-risk verdict. Then stop **only the bridge** and restart it
   with a deliberately invalid key for that process:

   ```bash
   ELEVENLABS_API_KEY=invalid-for-manual-check npm start
   ```

   Send a voice note, wait two quiet minutes, and expect a friendly unavailable
   notice plus a sanitized diagnostic, not a crash. Send normal text in a new
   batch and verify it still works. Stop this process and run `npm start` normally
   to restore the real `.env` key. This does not modify `.env`.

For successful notes, logs should show `Voice transcription completed.`, a batch
flush, a successful backend request, and `Guardian reply submitted to WhatsApp.`
After each completed/failed note, check the OS temp directory for this run's
`guardian-voice-*` folder: it should be gone. On Linux/macOS, with no recording
currently being processed:

```bash
find "${TMPDIR:-/tmp}" -maxdepth 1 -type d -name 'guardian-voice-*' -print
```

No audio or transcript should appear in the repository or `.auth/`. A nonempty
but incorrectly recognized transcript is still an STT limitation, not proof of
safe content. Do not expect transcripts or raw provider replies in logs.

References: [ElevenLabs STT API](https://elevenlabs.io/docs/api-reference/speech-to-text/convert),
[Scribe models](https://elevenlabs.io/docs/overview/models), and
[languages/formats](https://elevenlabs.io/docs/overview/capabilities/speech-to-text).

## Backend contract

`POST /api/bridge/messages` requires `Authorization: Bearer <shared-token>` and
the normalized JSON message described above. FastAPI validates the shape and
calls the existing Python pipeline. A successful response contains:

- `message_id`: the original message ID, checked by the bridge.
- `reply`: a consistent `HIGH RISK` / `MEDIUM RISK` / `LOW RISK` heading, a short
  **Why** section using Gemma's explanation, and **What to do** with a practical
  action and official-channel verification reminder for sensitive requests.
  Python bounds the generated prose at sentence boundaries and omits confidence
  percentages and raw evidence. Gemma chooses English, Hindi (Devanagari), or
  Hinglish (Roman Hindi) from the full buffered text/OCR/voice content. Both section
  labels and advice match that choice; Node sends the reply unchanged apart from
  appending a transport notice when a mixed batch has failed voice transcription. URL-only
  or sparse input defaults to English unless the batch provides language context.
  OCR language data and transport-error notices are unchanged.

The endpoint does not echo the original text or raw search evidence. Invalid
credentials return 401; an unset/short backend token or unavailable Gemma
assessment returns 503; malformed messages return 422. Keep this endpoint
private where possible; the shared secret is not a substitute for network access
controls or deployment-level rate limits. Do not expose the unencrypted local
backend directly to the internet. The old webhook adapter is not part of this
flow and requires no configuration.

## Costs and responsible use

Baileys is free/open-source and avoids Meta Cloud API transport fees. **It does
not make ElevenLabs STT, SerpApi, hosted Gemma, or hosting free.** Baileys is unofficial and not
affiliated with WhatsApp. Automated use may violate WhatsApp's terms and can
result in account restrictions. Use it only for consenting users; no spam, bulk
messaging, scraping, or unsolicited outreach.

References: [quickstart](https://baileys.wiki/quickstart),
[pairing codes](https://baileys.wiki/authentication/pairing-code), and
[session-management limitations](https://baileys.wiki/authentication/session-management).
