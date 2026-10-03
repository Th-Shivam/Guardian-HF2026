import { isBoom } from '@hapi/boom'
import makeWASocket, {
  Browsers,
  DisconnectReason,
  makeCacheableSignalKeyStore,
  normalizeMessageContent,
  useMultiFileAuthState,
  type WAMessage,
  type WAMessageContent,
  type WASocket,
} from '@whiskeysockets/baileys'
import { chmod, mkdir } from 'node:fs/promises'
import { pino } from 'pino'
import qrcode from 'qrcode-terminal'

import { requestReply, type GuardianMessage } from './backend.js'
import { loadConfig } from './config.js'
import { extractImageText } from './ocr.js'
import { transcribeVoice, VoiceTranscriptionError, VOICE_UNAVAILABLE } from './voice.js'

const BUFFER_INACTIVITY_MS = 60 * 1000
const MAX_QUEUE = 100
const MAX_CACHE = 2000
const SEEN_TTL_MS = 24 * 60 * 60 * 1000
const UNAVAILABLE = 'Guardian could not complete this check. No risk assessment was generated. Please try again later.'

interface Job {
  message: GuardianMessage
  reply?: string
  voiceNotice?: string
}

interface SenderBuffer {
  messages: [GuardianMessage, ...GuardianMessage[]]
  timer: NodeJS.Timeout
  pendingImages: number
  pendingVoices: number
  voiceNotices: Set<string>
  expired: boolean
}

interface IncomingMessage {
  message: GuardianMessage
  isImage: boolean
  isAudio: boolean
  caption: string
}

function normalize(message: WAMessage): IncomingMessage | undefined {
  const { id, remoteJid, fromMe } = message.key
  // Only private chats: no self replies, groups, newsletters, or broadcasts.
  // Modern WhatsApp may identify a sender with a LID instead of a phone JID.
  if (fromMe || !id || !remoteJid || !/^\d+(?::\d+)?@(s\.whatsapp\.net|lid)$/.test(remoteJid)) return
  const content = normalizeMessageContent(message.message)
  const isImage = Boolean(content?.imageMessage)
  const isAudio = !isImage && Boolean(content?.audioMessage) // PTT notes and audio attachments
  const text = (content?.conversation ?? content?.extendedTextMessage?.text)?.trim() ?? ''
  if (!isImage && !isAudio && (!text || text.length > 4096)) return
  return {
    message: {
      message_id: id,
      sender_id: remoteJid,
      text, // media is filled by OCR/STT before its batch can flush
      received_at: new Date().toISOString(), // bridge receipt time, not an inferred timezone
      source: 'whatsapp',
    },
    isImage,
    isAudio,
    caption: content?.imageMessage?.caption?.trim() ?? '',
  }
}

function remember<T>(cache: Map<string, T>, key: string, value: T): void {
  cache.set(key, value)
  if (cache.size > MAX_CACHE) {
    const oldest = cache.keys().next().value
    if (oldest !== undefined) cache.delete(oldest)
  }
}

async function main(): Promise<void> {
  const config = loadConfig()
  process.umask(0o077)
  await mkdir(config.authDirectory, { recursive: true, mode: 0o700 })
  await chmod(config.authDirectory, 0o700)
  const { state, saveCreds } = await useMultiFileAuthState(config.authDirectory)
  // Baileys can log decrypted content, identifiers, or session details. Only
  // our lifecycle/batch metadata (and explicit login codes) are shown.
  const logger = pino({ level: 'silent' })
  const keys = makeCacheableSignalKeyStore(state.keys, logger)
  const shutdown = new AbortController()
  const queue: Job[] = []
  const buffers = new Map<string, SenderBuffer>()
  const seen = new Map<string, number>()
  const sent = new Map<string, WAMessageContent>()
  let socket: WASocket | undefined
  let connected = false
  let processing = false
  let stopping = false
  let reconnectAttempt = 0
  let reconnectTimer: NodeJS.Timeout | undefined
  let credentialWrites = Promise.resolve()
  // One local OCR process at a time; text reception and sender timers keep
  // running. Each image reserves its position in its buffer before this work.
  let imageWork = Promise.resolve()
  let voiceWork = Promise.resolve() // STT stays separate from the existing OCR work

  async function stop(exitCode: number): Promise<void> {
    if (stopping) return
    stopping = true
    connected = false
    if (reconnectTimer) clearTimeout(reconnectTimer)
    for (const buffer of buffers.values()) clearTimeout(buffer.timer)
    buffers.clear()
    shutdown.abort()
    queue.length = 0
    socket?.end(undefined) // disconnect, do not revoke the saved linked device
    await Promise.all([imageWork, voiceWork]) // wait for temporary image/audio cleanup
    await credentialWrites
    process.exitCode = exitCode
  }

  function scheduleReconnect(restartRequired = false): void {
    if (stopping || reconnectTimer) return
    const delay = restartRequired ? 250 : Math.min(1000 * 2 ** reconnectAttempt++, 30_000)
    console.info(`WhatsApp disconnected; reconnecting in ${delay} ms.`)
    reconnectTimer = setTimeout(() => {
      reconnectTimer = undefined
      connect()
    }, delay)
  }

  function flushSender(senderId: string): void {
    const buffer = buffers.get(senderId)
    if (!buffer || stopping) return
    if (buffer.pendingImages > 0 || buffer.pendingVoices > 0) {
      buffer.expired = true
      return
    }
    buffers.delete(senderId)
    // Failed voice slots stay empty, not fabricated evidence. Other messages
    // keep their original order and still receive the normal risk assessment.
    const readable = buffer.messages.filter(message => message.text.trim())
    const voiceNotice = [...buffer.voiceNotices].join('\n')
    // Transfer the reserved buffer slot to the existing queue. Removing the
    // buffer first lets the sender start a fresh batch while this one runs.
    queue.push({
      message: {
        ...buffer.messages[0],
        text: readable.map(message => message.text).join('\n\n'),
      },
      reply: readable.length ? undefined : voiceNotice,
      voiceNotice: readable.length ? voiceNotice : undefined,
    })
    console.info(`Flushed WhatsApp batch to queue: sender=${senderId} messages=${buffer.messages.length}`)
    void drain()
  }

  async function drain(): Promise<void> {
    if (processing || stopping) return
    processing = true
    try {
      while (connected && socket && !stopping && queue.length) {
        const job = queue[0]!
        if (job.reply === undefined) {
          try {
            job.reply = await requestReply(config, job.message, shutdown.signal)
          } catch {
            if (stopping) return
            console.error('Guardian request failed; sending an availability notice, not a risk assessment.')
            job.reply = UNAVAILABLE
          }
          if (job.voiceNotice) job.reply += `\n\n${job.voiceNotice}`
        }
        // Retain a completed reply across a reconnect without calling AI again.
        if (!connected || !socket || stopping) return
        queue.shift()
        try {
          const outgoing = await socket.sendMessage(job.message.sender_id, {
            text: job.reply,
            linkPreview: null, // never fetch URLs that might appear in a model reply
          })
          if (!outgoing?.key.id) throw new Error('WhatsApp returned no outgoing message ID.')
          if (outgoing.message) {
            remember(sent, `${job.message.sender_id}:${outgoing.key.id}`, outgoing.message)
          }
          console.info('Guardian reply submitted to WhatsApp.')
        } catch {
          // Delivery may already have succeeded. Do not blindly retry and
          // create duplicate replies; Baileys may request a cached resend.
          console.error('WhatsApp reply could not be confirmed; not retrying automatically.')
        }
      }
    } finally {
      processing = false
    }
  }

  function connect(): void {
    if (stopping) return
    try {
      const sock = makeWASocket({
        auth: { creds: state.creds, keys },
        logger,
        browser: Browsers.ubuntu('Chrome'),
        markOnlineOnConnect: false,
        syncFullHistory: false,
        shouldSyncHistoryMessage: () => false,
        getMessage: async key => sent.get(`${key.remoteJid}:${key.id}`),
      })
      socket = sock
      let pairingRequested = false

      sock.ev.on('creds.update', () => {
        credentialWrites = credentialWrites.then(() => saveCreds()).catch(() => {
          console.error('Could not save WhatsApp credentials; stopping the bridge.')
          void stop(1)
        })
      })

      sock.ev.on('connection.update', update => {
        if (stopping || socket !== sock) return
        if (update.qr && !state.creds.registered) {
          if (config.pairingPhone) {
            if (!pairingRequested) {
              pairingRequested = true
              void sock.requestPairingCode(config.pairingPhone).then(code => {
                if (!stopping && socket === sock) console.info(`WhatsApp pairing code: ${code}`)
              }).catch(() => {
                if (stopping || socket !== sock) return
                console.error('Could not request a pairing code. Restart to try again, or use QR login.')
                void stop(1)
              })
            }
          } else {
            console.info('Scan with WhatsApp → Linked devices → Link a device. Keep this QR private.')
            qrcode.generate(update.qr, { small: true })
          }
        }
        if (update.connection === 'open') {
          connected = true
          reconnectAttempt = 0
          console.info('WhatsApp connected. Waiting for private text, image, and voice messages.')
          void drain()
        } else if (update.connection === 'close') {
          connected = false
          const error = update.lastDisconnect?.error
          const code = isBoom(error) ? error.output.statusCode : undefined
          const terminal = [
            DisconnectReason.loggedOut,
            DisconnectReason.badSession,
            DisconnectReason.connectionReplaced,
            DisconnectReason.forbidden,
            DisconnectReason.multideviceMismatch,
          ]
          if (code !== undefined && terminal.includes(code)) {
            console.error(`WhatsApp session stopped (${code}). Check Linked devices and the bridge README before restarting.`)
            void stop(1)
          } else {
            scheduleReconnect(code === DisconnectReason.restartRequired)
          }
        }
      })

      sock.ev.on('messages.upsert', event => {
        if (stopping || socket !== sock || event.type !== 'notify') return
        const now = Date.now()
        for (const [id, time] of seen) {
          if (now - time < SEEN_TTL_MS) break
          seen.delete(id)
        }
        for (const incoming of event.messages) {
          const normalized = normalize(incoming)
          if (!normalized) continue
          const { message, isImage, isAudio, caption } = normalized
          const id = `${message.sender_id}:${message.message_id}`
          if (seen.has(id)) continue
          let buffer = buffers.get(message.sender_id)
          // Reserve a queue slot per waiting sender so an accepted batch is
          // not dropped when its inactivity timer expires.
          if (!buffer && queue.length + buffers.size >= MAX_QUEUE) {
            console.error('Bridge queue is full; ignoring a new message. Sender must retry later.')
            continue
          }
          remember(seen, id, now)
          if (buffer) {
            clearTimeout(buffer.timer)
            buffer.messages.push(message)
            buffer.expired = false
            buffer.timer = setTimeout(() => flushSender(message.sender_id), BUFFER_INACTIVITY_MS)
          } else {
            buffer = {
              messages: [message],
              timer: setTimeout(() => flushSender(message.sender_id), BUFFER_INACTIVITY_MS),
              pendingImages: 0,
              pendingVoices: 0,
              voiceNotices: new Set(),
              expired: false,
            }
            buffers.set(message.sender_id, buffer)
          }
          console.info(`Buffering WhatsApp messages: sender=${message.sender_id} messages=${buffer.messages.length}`)
          if (isImage) {
            const imageBuffer = buffer
            imageBuffer.pendingImages += 1
            // Duplicate protection and slot reservation happen before any
            // asynchronous download, keeping image/text arrival order intact.
            imageWork = imageWork.then(async () => {
              if (stopping) return
              try {
                message.text = await extractImageText(incoming, shutdown.signal)
              } catch {
                // Never log SDK errors, OCR output, media URLs, or file paths.
                console.error('Image OCR unavailable: check Tesseract/eng installation, media access, size, and time limits.')
                message.text = '[Image OCR unavailable]\nThe image could not be read. Its contents are unknown; this is not evidence that it is safe.'
              } finally {
                if (caption) message.text += `\n\n[Image caption]\n${caption}`
                imageBuffer.pendingImages -= 1
                if (!stopping && imageBuffer.expired && buffers.get(message.sender_id) === imageBuffer) {
                  flushSender(message.sender_id)
                }
              }
            })
          }
          if (isAudio) {
            const voiceBuffer = buffer
            voiceBuffer.pendingVoices += 1
            // Reserve the original slot before STT, just as for images. Neither
            // completion order nor later text can reorder the buffered content.
            voiceWork = voiceWork.then(async () => {
              if (stopping) return
              try {
                message.text = await transcribeVoice(incoming, config, shutdown.signal)
              } catch (error) {
                message.text = ''
                if (!stopping) {
                  console.error(error instanceof VoiceTranscriptionError
                    ? error.message
                    : 'Voice transcription failed; check ElevenLabs configuration, connectivity, and limits.')
                  voiceBuffer.voiceNotices.add(error instanceof VoiceTranscriptionError
                    ? error.userReply
                    : VOICE_UNAVAILABLE)
                }
              } finally {
                voiceBuffer.pendingVoices -= 1
                if (!stopping && voiceBuffer.expired && buffers.get(message.sender_id) === voiceBuffer) {
                  flushSender(message.sender_id)
                }
              }
            })
          }
        }
      })
    } catch {
      console.error('Could not create the WhatsApp connection.')
      scheduleReconnect()
    }
  }

  process.once('SIGINT', () => { void stop(0) })
  process.once('SIGTERM', () => { void stop(0) })
  connect()
}

main().catch(() => {
  // Do not print exception objects: SDK/network errors may carry credentials.
  console.error('Bridge startup failed. Check Node version, .env configuration, and .auth directory permissions.')
  process.exitCode = 1
})
