import { downloadMediaMessage, normalizeMessageContent, type WAMessage } from '@whiskeysockets/baileys'
import { createWriteStream } from 'node:fs'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Transform } from 'node:stream'
import { pipeline } from 'node:stream/promises'

import type { BridgeConfig } from './config.js'

const STT_ENDPOINT = 'https://api.elevenlabs.io/v1/speech-to-text'
const MAX_AUDIO_BYTES = 10 * 1024 * 1024
const VOICE_TIMEOUT_MS = 120_000
export const VOICE_UNAVAILABLE = 'Guardian could not transcribe one or more voice messages right now. Please send the text or try again later.'
const VOICE_UNCLEAR = 'Guardian could not understand one or more voice messages. Please record them again clearly or send the text.'
const AUDIO_EXTENSIONS: Record<string, string> = {
  'audio/ogg': 'ogg',
  'audio/opus': 'opus',
  'audio/mpeg': 'mp3',
  'audio/mp3': 'mp3',
  'audio/mp4': 'm4a',
  'audio/x-m4a': 'm4a',
  'audio/aac': 'aac',
  'audio/amr': 'amr',
  'audio/wav': 'wav',
  'audio/x-wav': 'wav',
  'audio/webm': 'webm',
  'audio/flac': 'flac',
}

/** Safe diagnostics only: no upstream response bodies, keys, media URLs, or text. */
export class VoiceTranscriptionError extends Error {
  constructor(message: string, readonly userReply: string = VOICE_UNAVAILABLE) {
    super(message)
  }
}

async function audioStream(message: WAMessage, signal: AbortSignal): Promise<Transform> {
  signal.throwIfAborted()
  // This Baileys version does not propagate fetch signals. Stop waiting when
  // cancelled, and discard a late stream without writing a temporary file.
  return new Promise((resolve, reject) => {
    const onAbort = () => reject(new VoiceTranscriptionError('Audio download timed out or was cancelled.'))
    signal.addEventListener('abort', onAbort, { once: true })
    void downloadMediaMessage(message, 'stream', {}).then(stream => {
      signal.removeEventListener('abort', onAbort)
      stream.on('error', () => {}) // pipeline observes errors after temp-file setup
      if (signal.aborted) stream.destroy()
      else resolve(stream)
    }, () => {
      signal.removeEventListener('abort', onAbort)
      reject(new VoiceTranscriptionError('Could not download the WhatsApp audio.'))
    })
  })
}

/** Send the original audio to ElevenLabs only, returning its unmodified transcript. */
export async function transcribeVoice(
  message: WAMessage,
  config: BridgeConfig,
  shutdown: AbortSignal,
): Promise<string> {
  if (!config.elevenLabsApiKey) {
    throw new VoiceTranscriptionError('Set ELEVENLABS_API_KEY to enable voice transcription.')
  }
  const audio = normalizeMessageContent(message.message)?.audioMessage
  if (!audio) throw new VoiceTranscriptionError('No audio was present in the WhatsApp message.')
  const mime = audio.mimetype?.split(';')[0]?.trim().toLowerCase() || 'audio/ogg'
  const extension = AUDIO_EXTENSIONS[mime] ?? 'bin'
  const signal = AbortSignal.any([shutdown, AbortSignal.timeout(VOICE_TIMEOUT_MS)])
  const stream = await audioStream(message, signal)
  let directory: string | undefined
  try {
    signal.throwIfAborted()
    directory = await mkdtemp(join(tmpdir(), 'guardian-voice-'))
    const audioPath = join(directory, `audio.${extension}`)
    let bytes = 0
    const limit = new Transform({
      transform(chunk: Buffer, _encoding, callback) {
        bytes += chunk.length
        if (bytes > MAX_AUDIO_BYTES) {
          callback(new VoiceTranscriptionError(
            'Voice recording exceeded the 10 MiB limit.',
            'Guardian could not process that large recording. Please send a shorter voice note or type the message.',
          ))
        } else callback(null, chunk)
      },
    })
    await pipeline(stream, limit, createWriteStream(audioPath, { mode: 0o600, flags: 'wx' }), { signal })
    if (bytes === 0) throw new VoiceTranscriptionError('Audio was empty.', VOICE_UNCLEAR)

    const body = new FormData()
    body.set('file', new Blob([new Uint8Array(await readFile(audioPath, { signal }))], {
      type: extension === 'bin' ? 'application/octet-stream' : mime,
    }), `audio.${extension}`)
    body.set('model_id', config.elevenLabsSttModel)
    body.set('tag_audio_events', 'false')
    body.set('diarize', 'false')
    body.set('timestamps_granularity', 'none')
    // Do not set language_code or transcript_edit: auto-detect the spoken
    // languages, retain code-switching, and do not translate/transliterate.
    const response = await fetch(STT_ENDPOINT, {
      method: 'POST',
      headers: { 'xi-api-key': config.elevenLabsApiKey },
      body,
      signal,
      redirect: 'error',
    })
    if (!response.ok) {
      await response.body?.cancel()
      throw new VoiceTranscriptionError(`ElevenLabs STT returned HTTP ${response.status}.`)
    }
    const data: unknown = await response.json()
    if (typeof data !== 'object' || data === null || !('text' in data) || typeof data.text !== 'string') {
      throw new VoiceTranscriptionError('ElevenLabs STT returned an invalid transcript response.')
    }
    const text = data.text.trim()
    if (!/[\p{L}\p{N}]/u.test(text)) {
      throw new VoiceTranscriptionError('ElevenLabs STT returned no usable speech.', VOICE_UNCLEAR)
    }
    console.info('Voice transcription completed.')
    return `[Voice transcription]\n${text}`
  } finally {
    stream.destroy()
    if (directory) await rm(directory, { recursive: true, force: true })
  }
}
