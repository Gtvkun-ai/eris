const fs = require("fs");
const path = require("path");
const assert = require("assert");

const source = fs.readFileSync(
  path.resolve(__dirname, "../src/extension.ts"),
  "utf8"
);

const sendStart = source.indexOf("const sendChatToBackend = async");
assert.notStrictEqual(sendStart, -1, "sendChatToBackend should exist");

const sendEnd = source.indexOf("const buildQuickActionPrompt", sendStart);
assert.notStrictEqual(sendEnd, -1, "sendChatToBackend should end before quick actions");

const sendBody = source.slice(sendStart, sendEnd);

const readinessIndex = sendBody.indexOf("const readinessBlock = await resolveChatReadinessBlocker();");
const appendIndex = sendBody.indexOf("appendChatMessageToState(userMessage);");

assert.ok(
  readinessIndex !== -1,
  "chat should preflight readiness before starting a visible task"
);
assert.ok(
  appendIndex !== -1 && readinessIndex < appendIndex,
  "a provider/server blocker should be reported before the task enters the transcript pipeline"
);

assert.match(
  source,
  /const shouldUseStreamingForIntent = \(intent: string\): boolean =>[\s\S]{0,120}intent !== "general"/,
  "plain conversational messages should skip the coding-agent stream"
);

const streamGuardIndex = sendBody.indexOf("if (shouldUseStreamingForIntent(intent))");
const streamCallIndex = sendBody.indexOf("sendChatStreaming(");
const batchIndex = sendBody.indexOf("const batchStartedAt = Date.now();");

assert.ok(
  streamGuardIndex !== -1 && streamGuardIndex < streamCallIndex,
  "the SSE call should be guarded by intent"
);
assert.ok(
  streamCallIndex !== -1 && streamCallIndex < batchIndex,
  "batch remains the fallback/lightweight route after the stream decision"
);

console.log("PASS chat readiness and general-message routing are guarded");
