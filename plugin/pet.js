// opencode-pet: global plugin for local activity and the pet's quick-chat relay.
const endpoint = "http://127.0.0.1:47829/event"
const registerEndpoint = "http://127.0.0.1:47829/register"

export const PetPlugin = async ({ directory, client }) => {
  // The TUI's SDK can use an in-process fetch with no listening HTTP port.
  // Expose only the four operations the pet needs through a loopback relay.
  const relay = Bun.serve({
    hostname: "127.0.0.1",
    port: 0,
    async fetch(request) {
      const url = new URL(request.url)
      if (url.searchParams.get("directory") !== directory) return new Response("Wrong project", { status: 403 })
      const segments = url.pathname.split("/").filter(Boolean)
      const sessionID = segments[1]
      if (request.method === "GET" && url.pathname === "/models") {
        try {
          const result = await client.provider.list()
          if (result.error) return new Response("OpenCode request failed", { status: result.response?.status ?? 502 })
          const connected = new Set(result.data?.connected ?? [])
          const models = (result.data?.all ?? [])
            .filter((provider) => connected.has(provider.id))
            .flatMap((provider) => Object.values(provider.models ?? {})
              .filter((model) => model.status !== "deprecated")
              .map((model) => ({ id: `${provider.id}/${model.id}`, label: `${provider.name} · ${model.name}` })))
          return Response.json(models.slice(0, 200))
        } catch {
          return new Response("OpenCode request failed", { status: 502 })
        }
      }
      if (segments[0] !== "session" || (sessionID && !/^[a-zA-Z0-9_-]+$/.test(sessionID))) {
        return new Response("Not found", { status: 404 })
      }
      try {
        let result
        if (request.method === "GET" && segments.length === 1) {
          result = await client.session.list({ query: { directory, limit: 20 } })
        } else if (request.method === "POST" && segments.length === 1) {
          result = await client.session.create({ query: { directory }, body: {} })
        } else if (request.method === "GET" && segments.length === 3 && segments[2] === "message") {
          result = await client.session.messages({ path: { id: sessionID }, query: { directory, limit: 30 } })
        } else if (request.method === "POST" && segments.length === 3 && segments[2] === "prompt_async") {
          if (Number(request.headers.get("content-length")) > 24_000) return new Response("Too large", { status: 413 })
          const body = await request.json()
          const text = body?.parts?.[0]?.text
          if (!Array.isArray(body.parts) || body.parts.length !== 1 || typeof text !== "string" ||
              !text.trim() || text.length > 20_000) return new Response("Invalid message", { status: 400 })
          const model = body.model
          if (model !== undefined && (typeof model?.providerID !== "string" ||
              typeof model?.modelID !== "string" || !model.providerID || !model.modelID)) {
            return new Response("Invalid model", { status: 400 })
          }
          result = await client.session.promptAsync({
            path: { id: sessionID }, query: { directory },
            body: { parts: [{ type: "text", text }], ...(model ? { model } : {}) },
          })
        } else {
          return new Response("Not found", { status: 404 })
        }
        if (result.error) return new Response("OpenCode request failed", { status: result.response?.status ?? 502 })
        return segments[2] === "prompt_async" ? new Response(null, { status: 204 }) : Response.json(result.data)
      } catch {
        return new Response("OpenCode request failed", { status: 502 })
      }
    },
  })
  let registered = false
  let registering = false
  const register = async () => {
    if (registering) return
    registering = true
    try {
      const response = await fetch(registerEndpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ directory, url: relay.url.href }),
        signal: AbortSignal.timeout(300),
      })
      registered = response.ok
    } catch {
      registered = false
    } finally {
      registering = false
    }
  }
  // Also register after OpenCode has been idle: the pet may start later.
  const timer = setInterval(register, 5000)
  timer.unref?.()
  void register()

  return {
    dispose: async () => {
      clearInterval(timer)
      relay.stop(true)
    },
    event: async ({ event }) => {
      if (!registered) void register()
      const properties = event.properties ?? {}
      const sessionID = properties.sessionID ?? properties.info?.sessionID ?? properties.info?.id
      let type
      switch (event.type) {
        case "session.status":
          type = properties.status?.type === "busy" ? "session.busy" :
            properties.status?.type === "idle" ? "session.idle" : undefined
          break
        case "session.idle":
        case "session.error":
        case "session.deleted":
          type = event.type
          break
        case "permission.asked":
        case "permission.updated":
        case "question.asked":
          type = "session.waiting"
          break
        case "permission.replied":
        case "question.replied":
          type = "session.busy"
          break
        case "command.executed":
          if (properties.name === "review" || properties.name === "code-review") type = "session.review"
          break
      }
      if (!type || !sessionID) return
      try {
        await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ type, sessionID, directory }),
          signal: AbortSignal.timeout(200),
        })
      } catch {
        // The desktop pet is optional; no listener must never slow down OpenCode.
      }
    },
  }
}
