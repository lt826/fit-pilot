// 与后端通信的唯一出口：SSE 流式对话 + 画像读写
//
// 为什么不用 EventSource：它只支持 GET，无法携带 JSON 请求体，
// 所以用 fetch + ReadableStream 手动解析 SSE 文本协议

export async function streamChat(message, sessionId, handlers) {
  const resp = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
  })
  if (!resp.ok || !resp.body) throw new Error(`连接失败: HTTP ${resp.status}`)

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })

    // SSE 以空行分隔事件块：event: xxx\ndata: {...}\n\n
    let idx
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      let event = 'message'
      let data = ''
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (!data) continue
      try {
        handlers[event]?.(JSON.parse(data))
      } catch {
        // 非 JSON 数据忽略，不让单条坏事件中断整轮
      }
    }
  }
}

export const getProfile = () =>
  fetch('/api/profile').then((r) => r.json())

export const saveProfile = (p) =>
  fetch('/api/profile', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(p),
  }).then((r) => r.json())

// ---- 会话历史 ----

export const createSession = () =>
  fetch('/api/sessions', { method: 'POST' }).then((r) => r.json())

export const listSessions = () =>
  fetch('/api/sessions').then((r) => r.json())

export const getSessionMessages = (sid) =>
  fetch(`/api/sessions/${sid}/messages`).then((r) => r.json())

export const deleteSession = (sid) =>
  fetch(`/api/sessions/${sid}`, { method: 'DELETE' }).then((r) => r.json())

// ---- 数据管理（不可逆，仅 UI 触发，不暴露给 Agent） ----

export const listTrainingLogs = () =>
  fetch('/api/training-logs').then((r) => r.json())

export const deleteTrainingLog = (id) =>
  fetch(`/api/training-logs/${id}`, { method: 'DELETE' }).then((r) => r.json())

export const listBodyMetrics = () =>
  fetch('/api/body-metrics').then((r) => r.json())

export const deleteBodyMetric = (id) =>
  fetch(`/api/body-metrics/${id}`, { method: 'DELETE' }).then((r) => r.json())
