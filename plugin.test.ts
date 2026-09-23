import { afterEach, expect, test } from "bun:test"
import { PetPlugin } from "./plugin/pet.js"

const originalFetch = globalThis.fetch
afterEach(() => { globalThis.fetch = originalFetch })

test("forwards session activity and permission states, but no conversation content", async () => {
  const sent: unknown[] = []
  let relayUrl = ""
  globalThis.fetch = (async (url, options) => {
    if (String(url).endsWith("/register")) {
      const registration = JSON.parse(options.body as string)
      relayUrl = registration.url
      sent.push({ directory: registration.directory, url: "local-relay" })
    } else {
      sent.push(JSON.parse(options.body as string))
    }
    return new Response(null, { status: 204 })
  }) as typeof fetch

  const calls: unknown[] = []
  const client = { session: {
    list: async () => ({ data: [{ id: "s-1", title: "Test" }] }),
    create: async () => ({ data: { id: "s-2" } }),
    messages: async () => ({ data: [{ info: { role: "assistant" }, parts: [{ type: "text", text: "hola" }] }] }),
    promptAsync: async (request: unknown) => { calls.push(request); return { data: undefined } },
  }, provider: {
    list: async () => ({ data: { connected: ["own"], all: [
      { id: "own", name: "My provider", models: { custom: { id: "custom", name: "My model", status: "active" } } },
      { id: "other", name: "Other", models: { hidden: { id: "hidden", name: "Hidden" } } },
    ] } }),
  } }
  const plugin = await PetPlugin({ directory: "/work", serverUrl: new URL("http://localhost:4096"), client } as never)
  await Bun.sleep(1)
  expect(relayUrl).toStartWith("http://127.0.0.1:")
  expect((await (await originalFetch(`${relayUrl}/session?directory=%2Fwork`)).json())[0].title).toBe("Test")
  expect(await (await originalFetch(`${relayUrl}/models?directory=%2Fwork`)).json()).toEqual([
    { id: "own/custom", label: "My provider · My model" },
  ])
  expect((await (await originalFetch(`${relayUrl}/session?directory=%2Fwork`, { method: "POST", body: "{}" })).json()).id).toBe("s-2")
  expect((await (await originalFetch(`${relayUrl}/session/s-1/message?directory=%2Fwork`)).json())[0].parts[0].text).toBe("hola")
  const prompt = await originalFetch(`${relayUrl}/session/s-1/prompt_async?directory=%2Fwork`, {
    method: "POST", body: JSON.stringify({ parts: [{ type: "text", text: "hola" }], model: { providerID: "own", modelID: "custom" } }),
  })
  expect(prompt.status).toBe(204)
  expect(calls).toEqual([{ path: { id: "s-1" }, query: { directory: "/work" }, body: { parts: [{ type: "text", text: "hola" }], model: { providerID: "own", modelID: "custom" } } }])
  expect((await originalFetch(`${relayUrl}/session?directory=%2Fother`)).status).toBe(403)
  const event = plugin.event!
  await event({ event: { type: "session.status", properties: {
    sessionID: "session-1", status: { type: "busy" }, prompt: "private"
  } } } as never)
  await event({ event: { type: "permission.asked", properties: { sessionID: "session-1" } } } as never)
  await event({ event: { type: "permission.replied", properties: { sessionID: "session-1" } } } as never)
  await event({ event: { type: "message.updated", properties: { sessionID: "session-1", text: "private" } } } as never)
  await event({ event: { type: "session.idle", properties: { sessionID: "session-1" } } } as never)
  await event({ event: { type: "command.executed", properties: { sessionID: "session-1", name: "review" } } } as never)
  expect(sent).toEqual([
    { directory: "/work", url: "local-relay" },
    { type: "session.busy", sessionID: "session-1", directory: "/work" },
    { type: "session.waiting", sessionID: "session-1", directory: "/work" },
    { type: "session.busy", sessionID: "session-1", directory: "/work" },
    { type: "session.idle", sessionID: "session-1", directory: "/work" },
    { type: "session.review", sessionID: "session-1", directory: "/work" },
  ])
  await plugin.dispose?.()
})
