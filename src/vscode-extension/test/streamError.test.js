const fs = require("fs");
const path = require("path");
const assert = require("assert");

const source = fs.readFileSync(
  path.resolve(__dirname, "../src/extension.ts"),
  "utf8"
);

assert.match(
  source,
  /let streamError: string \| undefined;/,
  "SSE error events must be remembered instead of being treated as an empty stream"
);
assert.match(
  source,
  /type === "error"[\s\S]{0,500}streamError = String/,
  "the stream error event should capture the backend's message"
);
assert.match(
  source,
  /if \(streamError\) \{[\s\S]{0,180}throw new Error\(streamError\);[\s\S]{0,80}\}[\s\S]{0,260}if \(!fullText\)/,
  "a backend stream error must fail the task before the batch fallback runs"
);

console.log("PASS stream errors fail the visible task instead of falling back");
