import * as Sentry from '@sentry/node'
import { basename } from 'node:path'

export type GuardianInputType = 'text' | 'url' | 'image' | 'voice'
export type GuardianTrace = ReturnType<typeof Sentry.startInactiveSpan>
type SpanOptions = Parameters<typeof Sentry.startSpan>[0]

const SAFE_DATA = new Set([
  'input_type', 'provider', 'model', 'success',
  'gen_ai.operation.name', 'gen_ai.agent.name', 'gen_ai.tool.name',
])
const SAFE_NAMES = new Set([
  'guardian.request', 'execute_tool ocr', 'execute_tool stt', 'guardian.backend_request',
])
let enabled = false

type SpanData = NonNullable<Sentry.Event['spans']>[number]
type TraceData = NonNullable<NonNullable<Sentry.Event['contexts']>['trace']>

function safeSpan<T extends SpanData | TraceData>(span: T): T {
  return {
    trace_id: span.trace_id,
    span_id: span.span_id,
    parent_span_id: span.parent_span_id,
    start_timestamp: span.start_timestamp,
    timestamp: span.timestamp,
    op: span.op,
    status: span.status,
    description: typeof span.description === 'string' && SAFE_NAMES.has(span.description)
      ? span.description : 'guardian.operation',
    data: Object.fromEntries(Object.entries(span.data ?? {}).filter(([key]) => SAFE_DATA.has(key))),
  } as T
}

function scrubEvent<T extends Sentry.Event>(event: T): T {
  // Rebuild an allowlisted payload; never send request data, IDs, breadcrumbs,
  // arbitrary context, exception text, locals, source snippets or private paths.
  const safe = {
    event_id: event.event_id,
    timestamp: event.timestamp,
    start_timestamp: event.start_timestamp,
    type: event.type,
    platform: event.platform,
    level: event.level,
    sdk: event.sdk,
    contexts: event.contexts?.trace ? { trace: safeSpan(event.contexts.trace) } : {},
    ...(event.type === 'transaction' ? {
      transaction: SAFE_NAMES.has(event.transaction ?? '') ? event.transaction : 'guardian.request',
      spans: event.spans?.map(safeSpan),
    } : {}),
    ...(event.exception ? { exception: { values: event.exception.values?.map(value => ({
      type: value.type,
      value: 'Guardian operation failed (details omitted)',
      stacktrace: { frames: value.stacktrace?.frames?.map(frame => ({
        filename: basename(frame.filename?.split(/[?#]/)[0] ?? 'unknown'),
        function: frame.function,
        lineno: frame.lineno,
        in_app: frame.in_app,
      })) },
    })) } } : {}),
  }
  return safe as T
}

export function initSentry(): void {
  const dsn = process.env.SENTRY_DSN?.trim()
  if (!dsn) return
  try {
    Sentry.init({
      dsn,
      tracesSampleRate: 1.0,
      traceLifecycle: 'static',
      tracePropagationTargets: [], // Only the explicit backend header below.
      defaultIntegrations: false, // No HTTP, console, media or AI auto-capture.
      enableRuntimeChannelInjection: false,
      enhanceFetchErrorMessages: false,
      debug: false,
      maxBreadcrumbs: 0,
      dataCollection: {
        userInfo: false,
        cookies: false,
        httpHeaders: false,
        httpBodies: [],
        urlQueryParams: false,
        genAI: { inputs: false, outputs: false },
        stackFrameVariables: false,
        frameContextLines: 0,
      },
      beforeSend: scrubEvent,
      beforeSendTransaction: scrubEvent,
    })
    enabled = true
  } catch {
    console.error('Sentry initialization failed; continuing without tracing.')
  }
}

export function inputType(text: string, media?: 'image' | 'voice'): GuardianInputType {
  if (media) return media
  if (text.includes('[Image OCR')) return 'image'
  if (text.includes('[Voice transcription]')) return 'voice'
  return /https?:\/\//i.test(text) ? 'url' : 'text'
}

export function startGuardianTrace(input_type: GuardianInputType): GuardianTrace | undefined {
  if (!enabled) return undefined
  // Each independent sender batch needs a fresh trace, not the process's scope ID.
  return Sentry.startNewTrace(() => Sentry.startInactiveSpan({
    name: 'guardian.request',
    op: 'guardian.request',
    forceTransaction: true,
    attributes: { input_type },
  }))
}

export async function withGuardianSpan<T>(
  parent: GuardianTrace | undefined,
  options: SpanOptions,
  work: () => Promise<T>,
): Promise<T> {
  if (!parent || !enabled) return work()
  return Sentry.withActiveSpan(parent, () => Sentry.startSpan(options, async span => {
    try {
      const result = await work()
      span.setAttribute('success', true)
      span.setStatus({ code: 1 })
      return result
    } catch (error) {
      span.setAttribute('success', false)
      span.setStatus({ code: 2 })
      captureException(error)
      throw error
    }
  }))
}

export function traceHeaders(): Record<string, string> {
  const span = enabled ? Sentry.getActiveSpan() : undefined
  // Contains only randomly generated trace/span IDs and the sampling bit.
  return span ? { 'sentry-trace': Sentry.spanToTraceHeader(span) } : {}
}

export function finishGuardianTrace(trace: GuardianTrace | undefined, success: boolean): void {
  if (!trace) return
  trace.setAttribute('success', success)
  trace.setStatus({ code: success ? 1 : 2 })
  trace.end()
}

export function captureException(error: unknown): void {
  if (enabled) Sentry.captureException(error)
}
