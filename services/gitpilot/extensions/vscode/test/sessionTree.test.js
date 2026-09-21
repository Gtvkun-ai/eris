const Module = require("module");
const assert = require("assert");
const path = require("path");

const OUT = path.resolve(__dirname, "../out");

const vscodeStub = {
  TreeItemCollapsibleState: { None: 0 },
  ThemeIcon: class {
    constructor(id) {
      this.id = id;
    }
  },
  TreeItem: class {
    constructor(label, collapsibleState) {
      this.label = label;
      this.collapsibleState = collapsibleState;
    }
  },
  EventEmitter: class {
    constructor() {
      this.event = () => ({ dispose() {} });
    }
    fire() {}
    dispose() {}
  },
};

const origResolve = Module._resolveFilename;
Module._resolveFilename = function (request, ...args) {
  if (request === "vscode") return "vscode";
  return origResolve.call(this, request, ...args);
};
require.cache.vscode = {
  id: "vscode",
  filename: "vscode",
  loaded: true,
  exports: vscodeStub,
};

const { SessionsTreeProvider } = require(path.join(
  OUT,
  "tree/sessionsTreeProvider.js"
));

(async () => {
  const provider = new SessionsTreeProvider({
    isConnected: true,
    listSessions: async () => [
      {
        id: "s1",
        name: "Local Git: eris (main)",
        repo: null,
        branch: "main",
        message_count: 0,
        status: "active",
      },
    ],
  });

  const [item] = await provider.getChildren();

  assert.strictEqual(item.label, "Local Git: eris (main)");
  assert.ok(!String(item.tooltip).includes("undefined"));
  assert.ok(!String(item.label).includes("undefined"));

  console.log("PASS sessions tree renders backend session names");
})();
