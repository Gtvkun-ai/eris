/**
 * Eris Cline Runtime
 *
 * Tạo và quản lý Cline LocalRuntimeHost sessions.
 * Mỗi CodingTask từ Eris Brain → một Cline session.
 * Events được relay về qua callback để bridge.ts forward sang Python.
 *
 * Phase A: LocalRuntimeHost (in-process, đơn giản)
 * Phase C+: HubRuntimeHost (daemon, session survive restart)
 */

import { buildSystemPromptInjection } from './context-provider.js';
import { translateClineEvent, type ErisWsEvent } from './event-relay.js';
import type { ErisRepoContext, ErisMemoryContext } from './context-provider.js';

export interface CodingTaskInput {
  taskId: string;
  goal: string;
  workspacePath: string;
  taskMode: 'execute' | 'inspect';
  repoContext?: ErisRepoContext | null;
  memoryContext?: ErisMemoryContext | null;
  model?: string;
}

export interface CodingTaskResult {
  taskId: string;
  status: 'completed' | 'failed' | 'stopped';
  final: string;
  changedFiles: string[];
  durationMs: number;
}

export type EventCallback = (event: ErisWsEvent) => void;

/**
 * Chạy một Cline session cho CodingTask.
 * Trả về Promise<CodingTaskResult> khi agent hoàn tất (hoặc fail).
 * Events được emit realtime qua onEvent callback.
 */
export async function runCodingTask(
  input: CodingTaskInput,
  onEvent: EventCallback,
): Promise<CodingTaskResult> {
  const startMs = Date.now();

  // Lazy import để tránh top-level crash nếu @cline/core chưa install
  let clineCore: typeof import('@cline/core');
  try {
    clineCore = await import('@cline/core');
  } catch (err) {
    throw new Error(
      `@cline/core not available. Run: npm install inside cline-bridge/\nOriginal: ${err}`,
    );
  }

  const { createLocalRuntimeHost } = clineCore;

  // Build system prompt từ Eris context
  const contextInjection = buildSystemPromptInjection(
    input.repoContext ?? null,
    input.memoryContext ?? null,
  );

  const modeInstruction =
    input.taskMode === 'inspect'
      ? 'INSPECT-ONLY MODE: read, analyze, and explain. Do NOT modify any files.'
      : 'EXECUTION MODE: you may read, modify, run commands, and verify.';

  const systemPrompt = [
    'You are a coding specialist working inside the Eris system.',
    'Do NOT roleplay Eris\'s personality. Focus on the task.',
    modeInstruction,
    '',
    contextInjection,
  ]
    .filter(Boolean)
    .join('\n');

  // Tạo LocalRuntimeHost
  const host = await createLocalRuntimeHost({
    cwd: input.workspacePath,
    systemPrompt,
    model: input.model ?? 'claude-sonnet-4-5',
  });

  const changedFiles: string[] = [];
  let finalText = '';
  let taskStatus: 'completed' | 'failed' | 'stopped' = 'completed';

  // Bắt đầu session
  const session = await host.start({
    userMessage: input.goal,
    mode: input.taskMode === 'inspect' ? 'read-only' : undefined,
  });

  // Relay events về Python
  function emit(clineType: string, data: unknown): void {
    const event = translateClineEvent(clineType, data, input.taskId);
    if (event) {
      onEvent(event);
    }
  }

  // Subscribe events
  session.on('content_delta', (data: unknown) => emit('content_delta', data));
  session.on('content_end', (data: unknown) => {
    const d = (data && typeof data === 'object' ? data : {}) as Record<string, unknown>;
    finalText = String(d['text'] ?? finalText);
    emit('content_end', data);
  });
  session.on('tool_start', (data: unknown) => emit('tool_start', data));
  session.on('tool_finish', (data: unknown) => {
    const d = (data && typeof data === 'object' ? data : {}) as Record<string, unknown>;
    const path = String(d['path'] ?? '');
    if (path && String(d['name'] ?? '').includes('write')) {
      changedFiles.push(path);
      emit('file_write', { path, diff: d['diff'] ?? '' });
    }
    emit('tool_finish', data);
  });

  // Chờ agent hoàn tất
  try {
    const result = await session.waitForCompletion();
    const r = (result && typeof result === 'object' ? result : {}) as Record<string, unknown>;
    finalText = String(r['text'] ?? finalText);
    taskStatus = 'completed';
    emit('agent_done', { result: finalText });
  } catch (err) {
    taskStatus = 'failed';
    finalText = String(err);
    emit('agent_done', { error: finalText });
  }

  return {
    taskId: input.taskId,
    status: taskStatus,
    final: finalText,
    changedFiles,
    durationMs: Date.now() - startMs,
  };
}
