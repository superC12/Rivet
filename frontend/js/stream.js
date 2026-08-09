export async function consumeEventStream(response, handlers, signal) {
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try { message = (await response.json()).detail || message; } catch { /* keep safe message */ }
    throw new Error(message);
  }
  if (!response.body) throw new Error("Streaming is not supported by this browser.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    if (signal?.aborted) { await reader.cancel(); break; }
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() || "";
    for (const block of blocks) {
      let name = "message";
      const data = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) name = line.slice(6).trim();
        if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      }
      const raw = data.join("\n");
      let payload = raw;
      try { payload = JSON.parse(raw); } catch { /* token text is valid */ }
      handlers[name]?.(payload);
    }
  }
}
