import { useState, useCallback } from 'react'

/**
 * Tracks in-flight tool calls for a streaming SSE run. Each `tool_call`
 * event appends a pending entry; the next `tool_result` for that tool name
 * marks the oldest pending entry for it as done. `reset` clears everything
 * for a fresh run (e.g. re-submitting a ticker search).
 */
export function useToolCalls() {
  const [calls, setCalls] = useState([])

  const handleEvent = useCallback((eventName, data) => {
    if (eventName === 'tool_call') {
      setCalls((prev) => [...prev, { toolName: data.tool_name, args: data.args, done: false }])
    } else if (eventName === 'tool_result') {
      setCalls((prev) => {
        const index = prev.findIndex((c) => c.toolName === data.tool_name && !c.done)
        if (index === -1) return prev
        const next = [...prev]
        next[index] = { ...next[index], done: true, content: data.content }
        return next
      })
    }
  }, [])

  const reset = useCallback(() => setCalls([]), [])

  return { calls, handleEvent, reset }
}
