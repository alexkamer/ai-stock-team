const BASE_URL = '/api'

async function throwForStatus(response) {
  const body = await response.json().catch(() => ({}))
  const error = new Error(body.detail || `Request failed: ${response.status}`)
  error.status = response.status
  throw error
}

export async function getJSON(path) {
  const response = await fetch(`${BASE_URL}${path}`)
  if (!response.ok) await throwForStatus(response)
  return response.json()
}

/**
 * POST a JSON body and parse a JSON response - used by the auth endpoints
 * (login/signup/logout), which aren't SSE streams and don't fit streamSSE.
 * The session cookie is sent/received automatically since these are
 * same-origin requests (via Vite's /api proxy in dev).
 */
export async function postJSON(path, body) {
  const response = await fetch(`${BASE_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
  if (!response.ok) await throwForStatus(response)
  return response.json()
}

export async function deleteJSON(path) {
  const response = await fetch(`${BASE_URL}${path}`, { method: 'DELETE' })
  if (!response.ok) await throwForStatus(response)
  return response.json()
}

/**
 * Stream Server-Sent Events from a GET or POST endpoint, invoking `onEvent`
 * for each `(eventName, data)` pair as it arrives. `data` is JSON-parsed.
 *
 * SSE's built-in `EventSource` only supports GET with no request body, and
 * `/chat` is POST - so this parses the `text/event-stream` body by hand from
 * a plain `fetch` response instead, which works for every route.
 */
export async function streamSSE(path, { method = 'GET', body, signal, onEvent }) {
  const response = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal,
  })
  if (!response.ok || !response.body) {
    throw new Error(`Request failed: ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''

    for (const chunk of events) {
      let eventName = 'message'
      let data = null
      for (const line of chunk.split('\n')) {
        if (line.startsWith('event: ')) eventName = line.slice('event: '.length)
        else if (line.startsWith('data: ')) data = line.slice('data: '.length)
      }
      if (data !== null) onEvent(eventName, JSON.parse(data))
    }
  }
}
