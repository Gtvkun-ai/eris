/**
 * Eris Cline Runtime
 *
 * Tạo và quản lý Cline sessions qua createRuntimeHost() + startSession().
 * Mỗi CodingTask từ Eris Brain → một Cline session.
 * Events được relay về qua callback để bridge.ts forward sang Python.
 *
 * API thực tế từ @cline/core 0.0.77:
 *   createRuntimeHost(ClineCoreOptions) → RuntimeHost
 *   host.startSession(StartSessionInput) → StartSessionResult (bao gồm result nếu non-interactive)
 *   host.subscribe(listener) → nhận CoreSessionEvent (chunk | agent_event | session_snapshot | ended | status)
 *   host.runTurn(SendSessionInput) → dùng cho interactive session
 *
 * Phase A: backendMode="local" (in-process, không cần hub daemon)
 * Phase C+: backendMode="hub" (session survive restart)
 */

import path from 'node:path';
import os from 'node:os';
import { buildSystemPromptInjection } from './context-provider.js';
import { translateClineEvent, type ErisWsEvent } from './event-relay.js';
import type { ErisRepoContext, ErisMemoryContext } from './context-provider.js';
import type { CoreSessionEvent } from '@cline/core';

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
  sessionId?: string;
}

export type EventCallback = (event: ErisWsEvent) => void;

/**
 * Resolve data directory cho Cline session storage.
 * Đặt trong ~/.eris/cline-sessions để tách khỏi workspace user.
 */
function resolveDataDir(): string {
  return path.join(os.homedir(), '.eris', 'cline-sessions');
}

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

  // Lazy import
  let createRuntimeHost: (typeof import('@cline/core'))['createRuntimeHost'];
  try {
    const mod = await import('@cline/core');
    createRuntimeHost = mod.createRuntimeHost;
  } catch (err) {
    throw new Error(
      `@cline/core not available. Run: npm install inside cline-bridge/\nOriginal: ${err}`,
    );
  }

  // Build system prompt từ Eris context
  const contextInjection = buildSystemPromptInjection(
    input.repoContext ?? null,
    input.memoryContext ?? null,
  );

  const modeInstruction =
    input.taskMode === 'inspect'
      ? 'INSPECT-ONLY MODE: read, analyze, and explain. Do NOT modify any files.'
      : 'EXECUTION MODE: you may read, modify, run commands, and verify.';

  const customInstructions = [
    'You are a coding specialist working inside the Eris system.',
    'Do NOT roleplay Eris\'s personality. Focus on the task.',
    modeInstruction,
    '',
    contextInjection,
  ]
    .filter(Boolean)
    .join('\n');

  // Tạo RuntimeHost với local in-process backend
  const host = await createRuntimeHost({
    clientName: 'eris-cline-bridge',
    backendMode: 'local',
    dataDir: resolveDataDir(),
  } as Parameters<typeof createRuntimeHost>[0]);

  const changedFiles: string[] = [];
  let finalText = '';
  let taskStatus: 'completed' | 'failed' | 'stopped' = 'completed';
  let resolvedSessionId = '';

  // Subscribe events TRƯỚC khi startSession
  const unsubscribe = host.subscribe((event: CoreSessionEvent) => {
    const sessionId = resolvedSessionId;

    if (event.type === 'chunk') {
      const chunk = event.payload.chunk ?? '';
      if (chunk && event.payload.stream === 'agent') {
        onEvent({
          type: 'message.assistant.delta',
          taskId: input.taskId,
          eventId: `chunk_${Date.now()}`,
          payload: { delta: chunk, sessionId },
          timestamp: new Date().toISOString(),
        });
      }
    } else if (event.type === 'agent_event') {
      const agentEvent = event.payload.event as Record<string, unknown>;
      const agentEventName = String(agentEvent?.['name'] ?? '');

      if (agentEventName === 'tool_call') {
        const toolName = String(agentEvent?.['toolName'] ?? 'tool');
        const relayed = translateClineEvent('tool_start', { name: toolName }, input.taskId);
        if (relayed) onEvent(relayed);
      } else if (agentEventName === 'tool_result') {
        const toolName = String(agentEvent?.['toolName'] ?? 'tool');
        const isError = Boolean(agentEvent?.['isError']);
        const relayed = translateClineEvent(
          'tool_finish',
          { name: toolName, error: isError ? 'tool_error' : null },
          input.taskId,
        );
        if (relayed) onEvent(relayed);
      } else if (agentEventName === 'agent_end') {
        finalText = String(agentEvent?.['result'] ?? finalText);
      }
    } else if (event.type === 'status') {
      const status = String(event.payload.status ?? '');
      onEvent({
        type: 'task.status',
        taskId: input.taskId,
        eventId: `status_${Date.now()}`,
        payload: { status, sessionId },
        timestamp: new Date().toISOString(),
      });
    } else if (event.type === 'ended') {
      const reason = String(event.payload.reason ?? '');
      taskStatus = reason === 'completed' ? 'completed' : reason === 'stopped' ? 'stopped' : 'failed';
    }
  });

  try {
    // Cấu hình session
    const startInput = {
      config: {
        cwd: input.workspacePath,
        customInstructions,
        // Dùng model từ stored provider settings nếu không chỉ định
        ...(input.model ? { model: input.model } : {}),
      },
      prompt: input.goal,
      interactive: false, // non-interactive: chạy đến khi xong tự động
      source: 'eris' as const,
    };

    const result = await host.startSession(startInput as Parameters<typeof host.startSession>[0]);
    resolvedSessionId = result.sessionId;

    // Đọc session kết quả cuối cùng nếu có
    if (result.result) {
      const agentResult = result.result as Record<string, unknown>;
      finalText = String(agentResult['text'] ?? agentResult['result'] ?? finalText);
    }

    // Đọc messages để tìm changed files
    try {
      const messages = await host.readSessionMessages(result.sessionId);
      for (const msg of messages) {
        const m = msg as Record<string, unknown>;
        const content = m['content'];
        if (typeof content === 'string' && content.includes('write_to_file')) {
          const match = content.match(/"path"\s*:\s*"([^"]+)"/);
          if (match?.[1]) changedFiles.push(match[1]);
        }
      }
    } catch {
      // Non-critical
    }

    taskStatus = 'completed';
    translateClineEvent('agent_done', { result: finalText }, input.taskId);
    onEvent(translateClineEvent('agent_done', { result: finalText }, input.taskId)!);
  } catch (err) {
    taskStatus = 'failed';
    finalText = String(err);
    const failEvent = translateClineEvent('agent_done', { error: finalText }, input.taskId);
    if (failEvent) onEvent(failEvent);
  } finally {
    unsubscribe();
    try {
      await host.dispose();
    } catch {
      // ignore dispose errors
    }
  }

  return {
    taskId: input.taskId,
    status: taskStatus,
    final: finalText,
    changedFiles,
    durationMs: Date.now() - startMs,
    sessionId: resolvedSessionId,
  };
}
