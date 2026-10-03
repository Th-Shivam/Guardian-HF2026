import type { BridgeConfig } from './config.js'
import { traceHeaders } from './observability.js'

/** Matches the existing Python GuardianMessage contract; no analysis in Node. */
export interface GuardianMessage {
  message_id: string
  sender_id: string
  text: string
  received_at: string
  source: 'whatsapp'
}

export async function requestReply(
  config: BridgeConfig,
  message: GuardianMessage,
  shutdown: AbortSignal,
): Promise<string> {
  // Allow the existing synchronous SerpApi + Gemma pipeline time to finish.
  // No automatic HTTP retries: a lost response may already have incurred work.
  const response = await fetch(config.backendEndpoint, {
    method: 'POST',
    redirect: 'error',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${config.token}`,
      ...traceHeaders(),
    },
    body: JSON.stringify(message),
    signal: AbortSignal.any([shutdown, AbortSignal.timeout(180_000)]),
  })
  if (!response.ok) {
    await response.body?.cancel()
    throw new Error(`Guardian backend returned HTTP ${response.status}.`)
  }
  const data: unknown = await response.json()
  if (
    typeof data !== 'object' || data === null ||
    !('message_id' in data) || data.message_id !== message.message_id ||
    !('reply' in data) || typeof data.reply !== 'string' ||
    !data.reply.trim() || Array.from(data.reply).length > 2000
  ) {
    throw new Error('Guardian backend returned an invalid reply.')
  }
  // The recipient always comes from WhatsApp, never from the HTTP response.
  return data.reply
}
