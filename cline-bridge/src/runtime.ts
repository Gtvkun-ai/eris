/**
 * Eris Cline Runtime
 *
 * Tạo Cline sessions qua createRuntimeHost() + startSession().
 * Provider config được inject trực tiếp vào session (không cần stored settings).
 *
 * Verified working config (2026-08-21):
 *   providerId: 'openai-compatible'
 *   baseUrl: 'http://localhost:8081/v1'  ← WebAI-to-API proxy
 *   apiKey: 'webai-proxy'               ← proxy không validate
 *   enableTools: true
 *   systemPrompt: required string
 */

import path from 'node:path';
import os from 'node:os';
import { buildSystemPromptInjection } from './context-provider.js';
import { translateClineEvent, type ErisWsEvent } from './event-relay.js';
import type { ErisRepoContext, ErisMemoryContext } from './context-provider.js';
import type { CoreSessionEvent } from '@cline/core';
import { createHookConfigFileExtension, resolveHooksConfigSearchPaths } from '@cline/core';

// ─── Public types ──────────────────────────────────────────────────────────

export interface CodingTaskInput {
  taskId: string;
  goal: string;
  workspacePath: string;
  repoContext?: ErisRepoContext | null;
  memoryContext?: ErisMemoryContext | null;
  model?: string;
  /** Pool override: WebAI endpoint URL (e.g. http://127.0.0.1:8082/v1) */
  baseUrl?: string;
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

// ─── Provider resolution ────────────────────────────────────────────────────

interface ProviderConfig {
  /** Cline CoreSessionConfig fields */
  providerId: string;
  modelId: string;
  apiKey: string;
  baseUrl?: string;
}

/**
 * Resolve provider từ env vars.
 * Default: WebAI-to-API proxy (localhost:8081) — xác thực bằng cookie Google.
 * Override: đặt ANTHROPIC_API_KEY hoặc GEMINI_API_KEY.
 */
function resolveProvider(modelOverride?: string, baseUrlOverride?: string): ProviderConfig {
  const webaiBase = (baseUrlOverride ?? process.env['ERIS_WEBAI_URL'] ?? 'http://localhost:8081')
    .replace(/\/v1\/?$/, '');
  const model = modelOverride
    ?? process.env['ERIS_CLINE_MODEL']
    ?? process.env['ERIS_GEMINI_AGENT_MODEL']
    ?? 'gemini-3-pro';

  if (process.env['ANTHROPIC_API_KEY']) {
    return {
      providerId: 'anthropic',
      modelId: process.env['ERIS_CLINE_MODEL'] ?? 'claude-sonnet-4-5',
      apiKey: process.env['ANTHROPIC_API_KEY']!,
    };
  }

  if (process.env['GEMINI_API_KEY']) {
    return { providerId: 'gemini', modelId: model, apiKey: process.env['GEMINI_API_KEY']! };
  }

  // openai-compatible provider voi baseUrl /v1 works voi WebAI proxy
  return {
    providerId: 'openai-compatible',
    modelId: model,
    apiKey: 'webai-proxy',
    baseUrl: `${webaiBase}/v1`,
  };
}

// ─── Main task runner ───────────────────────────────────────────────────────

/**
 * Chạy một CodingTask qua Cline agent loop.
 * Trả về CodingTaskResult khi agent hoàn tất, fail, hoặc stopped.
 * Events được emit realtime qua onEvent.
 */
export async function runCodingTask(
  input: CodingTaskInput,
  onEvent: EventCallback,
): Promise<CodingTaskResult> {
  const startMs = Date.now();

  // Lazy import — đảm bảo @cline/core có sẵn
  let createRuntimeHost: (typeof import('@cline/core'))['createRuntimeHost'];
  try {
    const mod = await import('@cline/core');
    createRuntimeHost = mod.createRuntimeHost;
  } catch (err) {
    throw new Error(`@cline/core unavailable. Run: npm install in cline-bridge/\n${err}`);
  }

  // Build system prompt
  const contextInjection = buildSystemPromptInjection(
    input.repoContext ?? null,
    input.memoryContext ?? null,
  );
  const systemPrompt = [
    'You are a coding specialist inside the Eris system.',
    'Do NOT roleplay as Eris. Focus on the technical task.',
    'You may use all available tools to read, modify, run commands, and verify.',
    contextInjection,
  ].filter(Boolean).join('\n\n');

  // Resolve provider — pool co the override ca model lan base URL
  const provider = resolveProvider(input.model, input.baseUrl);

  // Create RuntimeHost (local in-process)
  const host = await createRuntimeHost({
    clientName: 'eris-cline-bridge',
    backendMode: 'local',
  } as Parameters<typeof createRuntimeHost>[0]);

  // State
  const changedFiles: string[] = [];
  let finalText = '';
  let taskStatus: CodingTaskResult['status'] = 'completed';
  let resolvedSessionId = '';
  const hooksPath = path.join(input.workspacePath, '.eris', 'hooks');

  // Subscribe events TRƯỚC startSession
  const unsubscribe = host.subscribe((event: CoreSessionEvent) => {
    const sid = resolvedSessionId;

    if (event.type === 'chunk') {
      const chunk = event.payload.chunk ?? '';
      if (chunk && event.payload.stream === 'agent') {
        onEvent({
          type: 'message.assistant.delta',
          taskId: input.taskId,
          eventId: `chunk_${Date.now()}`,
          payload: { delta: chunk, sessionId: sid },
          timestamp: new Date().toISOString(),
        });
      }
    } else if (event.type === 'agent_event') {
      const agentEvent = event.payload.event as Record<string, unknown>;
      const name = String(agentEvent?.['name'] ?? '');

      if (name === 'tool_call') {
        const toolName = String(agentEvent?.['toolName'] ?? 'tool');
        const relayed = translateClineEvent('tool_start', { name: toolName }, input.taskId);
        if (relayed) onEvent(relayed);
      } else if (name === 'tool_result') {
        const toolName = String(agentEvent?.['toolName'] ?? 'tool');
        const isErr = Boolean(agentEvent?.['isError']);
        const relayed = translateClineEvent('tool_finish', { name: toolName, error: isErr ? 'tool_error' : null }, input.taskId);
        if (relayed) onEvent(relayed);
      } else if (name === 'agent_end') {
        finalText = String(agentEvent?.['result'] ?? finalText);
      }
    } else if (event.type === 'status') {
      onEvent({
        type: 'task.status',
        taskId: input.taskId,
        eventId: `status_${Date.now()}`,
        payload: { status: event.payload.status, sessionId: sid },
        timestamp: new Date().toISOString(),
      });
    } else if (event.type === 'ended') {
      const reason = String(event.payload.reason ?? '');
      taskStatus = reason === 'completed' ? 'completed' : reason === 'stopped' ? 'stopped' : 'failed';
    }
  });

  try {
    const result = await host.startSession({
      config: {
        cwd: input.workspacePath,
        // Provider — verified working with WebAI-to-API proxy
        providerId: provider.providerId,
        modelId: provider.modelId,
        apiKey: provider.apiKey,
        ...(provider.baseUrl ? { baseUrl: provider.baseUrl } : {}),
        // System prompt — required by CoreSessionConfig
        systemPrompt,
        // Runtime features
        enableTools: true,
        enableSpawnAgent: false,
        enableAgentTeams: false,
        // Disable checkpoint de tranh git dependency
        checkpoint: { enabled: false },
      },
      // Hooks: SDK tu doc .eris/hooks/*.json, tu chay shell command
      extensions: [
        createHookConfigFileExtension({
          searchPaths: resolveHooksConfigSearchPaths(hooksPath),
        }),
      ],
      prompt: input.goal,
      interactive: false,
      source: 'eris' as const,
    } as Parameters<typeof host.startSession>[0]);

    resolvedSessionId = result.sessionId;

    // Lấy kết quả cuối từ AgentResult
    if (result.result) {
      const r = result.result as Record<string, unknown>;
      finalText = String(r['text'] ?? r['result'] ?? finalText);
    }

    // Scan messages để tìm file thay đổi
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
      // non-critical
    }

    taskStatus = 'completed';
    const doneEvent = translateClineEvent('agent_done', { result: finalText }, input.taskId);
    if (doneEvent) onEvent(doneEvent);
  } catch (err) {
    taskStatus = 'failed';
    finalText = String(err);
    const failEvent = translateClineEvent('agent_done', { error: finalText }, input.taskId);
    if (failEvent) onEvent(failEvent);
  } finally {
    unsubscribe();
    try { await host.dispose(); } catch { /* ignore */ }
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
