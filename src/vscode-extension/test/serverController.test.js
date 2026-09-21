const assert = require("assert");
const fs = require("fs");
const path = require("path");

const source = fs.readFileSync(
  path.resolve(__dirname, "../src/services/server/GitPilotServerController.ts"),
  "utf8"
);

const spawnOptions = source.match(/env:\s*\{([\s\S]*?)\},\r?\n\s*\}\);/);
assert.ok(spawnOptions, "server spawn must pass an environment object");
assert.match(
  spawnOptions[1],
  /PYTHONIOENCODING:\s*["']utf-8["']/,
  "GitPilot stdout must be UTF-8 when spawned with piped output on Windows"
);
assert.match(
  spawnOptions[1],
  /PYTHONUTF8:\s*["']1["']/,
  "GitPilot must use Python UTF-8 mode when spawned by the extension"
);

console.log("PASS server controller forces UTF-8 for spawned GitPilot");
