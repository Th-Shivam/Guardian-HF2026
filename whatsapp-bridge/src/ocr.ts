import { downloadMediaMessage, type WAMessage } from '@whiskeysockets/baileys'
import { execFile } from 'node:child_process'
import { createWriteStream } from 'node:fs'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { Transform } from 'node:stream'
import { pipeline } from 'node:stream/promises'
import { promisify } from 'node:util'

const runFile = promisify(execFile)
const MAX_IMAGE_BYTES = 10 * 1024 * 1024
const IMAGE_TIMEOUT_MS = 60_000

/** Stop waiting on a media request even if Baileys ignores the fetch signal. */
async function imageStream(message: WAMessage, signal: AbortSignal): Promise<Transform> {
  signal.throwIfAborted()
  return new Promise((resolve, reject) => {
    const onAbort = () => reject(new Error('Image download cancelled.'))
    signal.addEventListener('abort', onAbort, { once: true })
    void downloadMediaMessage(message, 'stream', {}).then(stream => {
      signal.removeEventListener('abort', onAbort)
      // A timed-out request may finish later. Never write its image to disk.
      if (signal.aborted) stream.destroy()
      else {
        // Cover the brief gap while creating the temp directory; pipeline
        // subsequently observes any recorded stream failure itself.
        stream.on('error', () => {})
        resolve(stream)
      }
    }, () => {
      signal.removeEventListener('abort', onAbort)
      reject(new Error('Image download failed.'))
    })
  })
}

/** Convert one WhatsApp image to text locally. Never retain images or OCR files. */
export async function extractImageText(message: WAMessage, shutdown: AbortSignal): Promise<string> {
  const signal = AbortSignal.any([shutdown, AbortSignal.timeout(IMAGE_TIMEOUT_MS)])
  const stream = await imageStream(message, signal)
  let directory: string | undefined
  try {
    signal.throwIfAborted()
    directory = await mkdtemp(join(tmpdir(), 'guardian-ocr-'))
    const imagePath = join(directory, 'image')
    let bytes = 0
    const limit = new Transform({
      transform(chunk: Buffer, _encoding, callback) {
        bytes += chunk.length
        if (bytes > MAX_IMAGE_BYTES) callback(new Error('Image exceeds the OCR size limit.'))
        else callback(null, chunk)
      },
    })
    await pipeline(stream, limit, createWriteStream(imagePath, { mode: 0o600, flags: 'wx' }), { signal })
    // Arguments are passed directly, not through a shell. Output stays in
    // memory; Tesseract recognizes the image format without a filename suffix.
    const { stdout } = await runFile('tesseract', [imagePath, 'stdout', '-l', 'eng', '--psm', '6'], {
      signal,
      timeout: 45_000,
      killSignal: 'SIGKILL',
      maxBuffer: 64 * 1024,
      encoding: 'utf8',
      env: { ...process.env, OMP_THREAD_LIMIT: '1' },
    })
    const text = stdout.replace(/\r\n?/g, '\n').replace(/\f/g, '').trim()
    // Whitespace/punctuation alone is not useful recognized text. Do not
    // invent or repair URLs: extracted text uses the backend's normal rules.
    if (!/[\p{L}\p{N}]/u.test(text)) {
      console.info('Image OCR completed: no useful text detected.')
      return '[Image OCR text]\nNo useful text was detected in this image. The image contents could not be assessed; missing text is not evidence of safety.'
    }
    console.info('Image OCR completed: text extracted.')
    return `[Image OCR text]\n${text}`
  } finally {
    stream.destroy()
    if (directory) await rm(directory, { recursive: true, force: true })
  }
}
