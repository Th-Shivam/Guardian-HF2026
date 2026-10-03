import { loadEnvFile } from 'node:process'
import { fileURLToPath } from 'node:url'

export interface BridgeConfig {
  backendEndpoint: URL
  token: string
  pairingPhone: string
  authDirectory: string
}

export function loadConfig(): BridgeConfig {
  // Both src/ and dist/ resolve to the same repository-root .env. Existing
  // process environment variables take precedence over that file.
  try {
    loadEnvFile(fileURLToPath(new URL('../../.env', import.meta.url)))
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
      throw new Error('Could not read the repository-root .env file.')
    }
  }

  const token = process.env.GUARDIAN_WHATSAPP_BRIDGE_TOKEN?.trim() ?? ''
  if (token.length < 32 || /\s/.test(token)) {
    throw new Error('Set GUARDIAN_WHATSAPP_BRIDGE_TOKEN to a random secret of at least 32 characters.')
  }
  let backend: URL
  try {
    backend = new URL(process.env.WHATSAPP_BACKEND_URL || 'http://127.0.0.1:8000')
  } catch {
    throw new Error('WHATSAPP_BACKEND_URL must be a valid backend URL.')
  }
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(backend.hostname)
  if (
    (backend.protocol !== 'https:' && !(backend.protocol === 'http:' && loopback)) ||
    backend.username || backend.password || backend.search || backend.hash
  ) {
    throw new Error('Use HTTPS for the backend, or HTTP on loopback, without URL credentials or query strings.')
  }
  backend.pathname = backend.pathname.replace(/\/$/, '') + '/api/bridge/messages'

  const pairingPhone = process.env.WHATSAPP_PAIRING_PHONE?.trim() ?? ''
  if (pairingPhone && !/^[1-9]\d{6,14}$/.test(pairingPhone)) {
    throw new Error('WHATSAPP_PAIRING_PHONE must contain country code and digits only, without + or spaces.')
  }
  return {
    backendEndpoint: backend,
    token,
    pairingPhone,
    authDirectory: fileURLToPath(new URL('../.auth/', import.meta.url)),
  }
}
