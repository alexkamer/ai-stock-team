const BASE_URL = '/api'

export async function getJSON(path) {
  const response = await fetch(`${BASE_URL}${path}`)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed: ${response.status}`)
  }
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
