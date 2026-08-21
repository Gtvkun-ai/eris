/**
 * Eris Context Provider
 *
 * Nhận RepoContext từ Eris Python Brain và inject vào system prompt
 * của Cline session. Đây là cầu nối giữa Eris's semantic workspace
 * knowledge và Cline's agent loop.
 *
 * Pattern học từ Continue context providers nhưng không phụ thuộc runtime Continue.
 */

export interface ErisRepoContext {
  /** Cây file structure, dependencies, main entry points */
  context_pack: string;
  /** Resolved paths từ fuzzy path resolution */
  resolved_targets?: string[];
  /** Confidence score của context (0.0–1.0) */
  confidence?: number;
  /** Workspace root path */
  workspace_path?: string;
  /** Timestamp context được tạo */
  generated_at?: string;
}

export interface ErisMemoryContext {
  /** Recent relevant memories */
  snippets?: string[];
  /** User preferences / project conventions */
  preferences?: Record<string, string>;
}

/**
 * Tạo system prompt injection từ Eris context.
 * Cline sẽ nhận đây làm phần đầu system prompt trước khi agent loop bắt đầu.
 */
export function buildSystemPromptInjection(
  repoCtx: ErisRepoContext | null,
  memoryCtx: ErisMemoryContext | null,
): string {
  const parts: string[] = [];

  if (repoCtx?.context_pack) {
    parts.push(
      '--- ERIS REPOSITORY CONTEXT ---',
      `Workspace: ${repoCtx.workspace_path ?? '(unknown)'}`,
      `Context confidence: ${((repoCtx.confidence ?? 0) * 100).toFixed(0)}%`,
      '',
      repoCtx.context_pack.trim(),
      '',
      'Repository rule: consult this map first before deep-reading files.',
      '--- END REPOSITORY CONTEXT ---',
    );
  }

  if (repoCtx?.resolved_targets && repoCtx.resolved_targets.length > 0) {
    parts.push(
      '',
      '--- RESOLVED TARGETS ---',
      repoCtx.resolved_targets.slice(0, 20).join('\n'),
      '--- END RESOLVED TARGETS ---',
    );
  }

  if (memoryCtx?.preferences && Object.keys(memoryCtx.preferences).length > 0) {
    const prefLines = Object.entries(memoryCtx.preferences)
      .slice(0, 10)
      .map(([k, v]) => `- ${k}: ${v}`)
      .join('\n');
    parts.push('', '--- USER PREFERENCES (from Eris memory) ---', prefLines, '--- END PREFERENCES ---');
  }

  if (memoryCtx?.snippets && memoryCtx.snippets.length > 0) {
    parts.push(
      '',
      '--- RELEVANT ERIS MEMORY ---',
      memoryCtx.snippets.slice(0, 5).join('\n\n'),
      '--- END ERIS MEMORY ---',
    );
  }

  return parts.join('\n');
}
