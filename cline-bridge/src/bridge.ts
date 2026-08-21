/**
 * Eris Cline Bridge — HTTP Server
 *
 * HTTP server nhỏ lắng nghe lệnh từ Eris Python Brain.
 * Python gọi HTTP POST /task → bridge tạo Cline session, relay events về qua callback.
 *
 * Protocol:
 *   POST /task        — bắt đầu CodingTask mới (async, trả task_id ngay)
 *   GET  /task/:id    — lấy trạng thái task
 *   POST /task/:id/control { action: "stop" } — dừng task
 *   GET  /health      — health check
 *
 * Events được relay về Python qua POST đến ERIS_CALLBACK_URL (env var).
 * Nếu không có callback URL, events chỉ được log ra stdout.
 *
 * Port mặc định: 7832 (ERIS_BRIDGE_PORT env var để override)
 */

import http from 'node:http';
import { runCodingTask, type CodingTaskInput, type CodingTaskResult } from './runtime.js';
import type { ErisWsEvent } from './event-relay.js';

const PORT = parseInt(process.env['ERIS_BRIDGE_PORT'] ?? '7832', 10);
const CALLBACK_URL = process.env['ERIS_CALLBACK_URL'] ?? '';
const BRIDGE_TOKEN = process.env['ERIS_BRIDGE_TOKEN'] ?? '';

// In-memory task registry
interface TaskRecord {
  taskId: string;
  status: 'running' | 'completed' | 'failed' | 'stopped';
  startedAt: string;
  result?: CodingTaskResult;
  events: ErisWsEvent[];
}

const tasks = new Map<string, TaskRecord>();

// Relay event về Eris Python
async function relayEvent(event: ErisWsEvent): Promise<void> {
  // Luôn log ra stdout để Python có thể đọc nếu muốn
  process.stdout.write(JSON.stringify({ _bridge_event: true, ...event }) + '\n');

  if (!CALLBACK_URL) return;

  try {
    const url = new URL(CALLBACK_URL);
    const body = JSON.stringify(event);
    await fetch(url.toString(), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(BRIDGE_TOKEN ? { Authorization: `Bearer ${BRIDGE_TOKEN}` } : {}),
      },
      body,
    });
  } catch {
    // Callback fail không crash bridge; Python có thể poll /task/:id thay thế
  }
}

function parseBody(req: http.IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on('data', (chunk: Buffer) => chunks.push(chunk));
    req.on('end', () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}'));
      } catch {
        resolve({});
      }
    });
    req.on('error', reject);
  });
}

function json(res: http.ServerResponse, statusCode: number, data: unknown): void {
  const body = JSON.stringify(data);
  res.writeHead(statusCode, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

function verifyToken(req: http.IncomingMessage): boolean {
  if (!BRIDGE_TOKEN) return true;
  const auth = req.headers['authorization'] ?? '';
  return auth === `Bearer ${BRIDGE_TOKEN}`;
}

const server = http.createServer(async (req, res) => {
  if (!verifyToken(req)) {
    json(res, 401, { error: 'unauthorized' });
    return;
  }

  const url = new URL(req.url ?? '/', `http://localhost:${PORT}`);
  const path = url.pathname;
  const method = req.method ?? 'GET';

  // GET /health
  if (method === 'GET' && path === '/health') {
    json(res, 200, {
      status: 'ok',
      bridge: 'eris-cline-bridge',
      version: '0.1.0',
      activeTasks: [...tasks.values()].filter((t) => t.status === 'running').length,
    });
    return;
  }

  // POST /task — bắt đầu task mới
  if (method === 'POST' && path === '/task') {
    const body = (await parseBody(req)) as Record<string, unknown>;
    const taskId = String(body['task_id'] ?? `cline_${Date.now()}`);
    const goal = String(body['goal'] ?? '');
    const workspacePath = String(body['workspace_path'] ?? process.cwd());
    const taskMode = String(body['task_mode'] ?? 'execute') as 'execute' | 'inspect';

    if (!goal) {
      json(res, 400, { error: 'goal required' });
      return;
    }

    const input: CodingTaskInput = {
      taskId,
      goal,
      workspacePath,
      taskMode,
      repoContext: (body['repo_context'] as CodingTaskInput['repoContext']) ?? null,
      memoryContext: (body['memory_context'] as CodingTaskInput['memoryContext']) ?? null,
      model: body['model'] ? String(body['model']) : undefined,
    };

    const record: TaskRecord = {
      taskId,
      status: 'running',
      startedAt: new Date().toISOString(),
      events: [],
    };
    tasks.set(taskId, record);

    // Chạy async, trả về ngay
    json(res, 202, { task_id: taskId, status: 'running' });

    // Background execution
    runCodingTask(input, (event) => {
      record.events.push(event);
      void relayEvent(event);
    })
      .then((result) => {
        record.status = result.status;
        record.result = result;
        // Giữ tối đa 200 events per task để tránh memory leak
        if (record.events.length > 200) {
          record.events = record.events.slice(-200);
        }
      })
      .catch((err: unknown) => {
        record.status = 'failed';
        record.result = {
          taskId,
          status: 'failed',
          final: String(err),
          changedFiles: [],
          durationMs: Date.now() - Date.parse(record.startedAt),
        };
        void relayEvent({
          type: 'task_failed',
          taskId,
          eventId: `bridge_err_${Date.now()}`,
          payload: { error: String(err), status: 'failed' },
          timestamp: new Date().toISOString(),
        });
      });
    return;
  }

  // GET /task/:id
  const taskMatch = path.match(/^\/task\/([^/]+)$/);
  if (method === 'GET' && taskMatch) {
    const taskId = taskMatch[1]!;
    const record = tasks.get(taskId);
    if (!record) {
      json(res, 404, { error: 'task_not_found', task_id: taskId });
      return;
    }
    json(res, 200, {
      task_id: taskId,
      status: record.status,
      started_at: record.startedAt,
      result: record.result ?? null,
      event_count: record.events.length,
      // Trả về 50 events cuối để Python có thể poll
      recent_events: record.events.slice(-50),
    });
    return;
  }

  // POST /task/:id/control
  const controlMatch = path.match(/^\/task\/([^/]+)\/control$/);
  if (method === 'POST' && controlMatch) {
    const taskId = controlMatch[1]!;
    const record = tasks.get(taskId);
    if (!record) {
      json(res, 404, { error: 'task_not_found' });
      return;
    }
    const body = (await parseBody(req)) as Record<string, unknown>;
    const action = String(body['action'] ?? '');
    if (action === 'stop' && record.status === 'running') {
      record.status = 'stopped';
      json(res, 200, { task_id: taskId, action: 'stop', status: 'stopped' });
    } else {
      json(res, 200, { task_id: taskId, action, status: record.status });
    }
    return;
  }

  json(res, 404, { error: 'not_found' });
});

server.listen(PORT, '127.0.0.1', () => {
  // Signal Python bridge client có thể connect
  process.stdout.write(
    JSON.stringify({ _bridge_ready: true, port: PORT, pid: process.pid }) + '\n',
  );
});

server.on('error', (err) => {
  process.stderr.write(`[cline-bridge] server error: ${err}\n`);
  process.exit(1);
});

// Graceful shutdown
process.on('SIGTERM', () => server.close(() => process.exit(0)));
process.on('SIGINT', () => server.close(() => process.exit(0)));
