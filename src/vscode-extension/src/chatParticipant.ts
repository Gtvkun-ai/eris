import * as crypto from 'node:crypto';
import * as path from 'node:path';
import * as vscode from 'vscode';
import { captureIdeContext, currentWorkspaceRef } from './contextBridge';
import { ErisClient } from './erisClient';
import { TerminalContextObserver } from './terminalObserver';

const PARTICIPANT_ID = 'gtvk.eris';
const INACTIVITY_TIMEOUT_MS = 40 * 60_000;

interface ErisChatResult extends vscode.ChatResult {
  metadata: {
    threadId: string;
    taskId: string;
    status: string;
  };
}

/**
 * Đăng ký @eris trong Chat native của VS Code.
 *
 * Surface này KHÔNG gọi model Copilot. Nó chỉ mượn UI Chat của VS Code rồi gửi
 * request vào đúng Eris Service/LangGraph đang phục vụ Eris Panel. Vì vậy Eris
 * vẫn giữ brain, memory, supervisor, permission policy và checkpoint của mình.
 */
export function registerErisChatParticipant(
  context: vscode.ExtensionContext,
  client: ErisClient,
  terminalObserver: TerminalContextObserver,
): vscode.ChatParticipant {
  const handler: vscode.ChatRequestHandler = async (
    request,
    chatContext,
    stream,
    token,
  ): Promise<ErisChatResult> => {
    const prompt = request.prompt.trim();
    const threadId = previousThreadId(chatContext) || `vscode_chat_${crypto.randomUUID()}`;
    if (!prompt) {
      return {
        metadata: { threadId, taskId: '', status: 'empty' },
        errorDetails: { message: 'Nhập nội dung sau @eris.' },
      };
    }
    if (!vscode.workspace.isTrusted) {
      return {
        metadata: { threadId, taskId: '', status: 'workspace_untrusted' },
        errorDetails: { message: 'Workspace chưa được Trust. Eris không đọc hoặc sửa code ở workspace này.' },
      };
    }

    const taskMode: 'execute' | 'inspect' = request.command === 'inspect' || request.command === 'plan'
      ? 'inspect'
      : 'execute';
    const content = participantPrompt(request.command, prompt);
    stream.progress('Eris đang nối vào agent…');

    try {
      await client.createThread(threadId);
      const ideContext = await captureIdeContext(terminalObserver);
      ideContext.chat = {
        surface: 'vscode-native-chat',
        command: request.command ?? '',
        references: request.references.map(serializeReference),
      };

      const result = await runBackendTurn(
        client,
        threadId,
        content,
        taskMode,
        ideContext,
        stream,
        token,
      );
      // Full Eris Panel vẫn là nơi xem Choice Card/ChangeSet/timeline dài hơi.
      // Native Chat giữ vai trò cửa vào nhanh thay vì cố clone toàn bộ UI lần hai.
      stream.button({ command: 'eris.openChat', title: 'Open Eris' });
      return { metadata: { threadId, taskId: result.taskId, status: result.status } };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return {
        metadata: { threadId, taskId: '', status: 'failed' },
        errorDetails: { message },
      };
    }
  };

  const participant = vscode.chat.createChatParticipant(PARTICIPANT_ID, handler);
  participant.iconPath = vscode.Uri.joinPath(context.extensionUri, 'media', 'eris.svg');
  participant.followupProvider = {
    provideFollowups(result) {
      const metadata = result.metadata as ErisChatResult['metadata'] | undefined;
      if (metadata?.status === 'waiting_user' || metadata?.status === 'waiting_permission') {
        return [{
          prompt: 'Tiếp tục theo lựa chọn tôi vừa nêu.',
          label: 'Tiếp tục task',
        }];
      }
      return [
        { prompt: 'Kiểm tra lại thay đổi vừa làm và chạy test phù hợp.', label: 'Kiểm tra thay đổi' },
        { prompt: 'Giải thích ngắn gọn vì sao chọn hướng sửa này.', label: 'Giải thích hướng sửa' },
      ];
    },
  };
  context.subscriptions.push(participant);
  return participant;
}

function previousThreadId(chatContext: vscode.ChatContext): string {
  for (let index = chatContext.history.length - 1; index >= 0; index -= 1) {
    const turn = chatContext.history[index];
    if (turn instanceof vscode.ChatResponseTurn && turn.participant === PARTICIPANT_ID) {
      const threadId = String(turn.result.metadata?.threadId ?? '').trim();
      if (threadId) {
        return threadId;
      }
    }
  }
  return '';
}

function participantPrompt(command: string | undefined, prompt: string): string {
  switch (command) {
    case 'plan':
      return `[VS Code /plan] Chỉ điều tra và lập kế hoạch. Không sửa file hoặc chạy lệnh có side effect.\n\n${prompt}`;
    case 'inspect':
      return `[VS Code /inspect] Điều tra vấn đề và báo kết luận. Không sửa file trừ khi user yêu cầu ở lượt sau.\n\n${prompt}`;
    case 'fix':
      return `[VS Code /fix] Ưu tiên tìm root cause, sửa gọn và kiểm chứng bằng test phù hợp.\n\n${prompt}`;
    default:
      return prompt;
  }
}

function serializeReference(reference: vscode.ChatPromptReference): Record<string, unknown> {
  const value = reference.value;
  let rendered: unknown = value;
  if (value instanceof vscode.Uri) {
    rendered = { kind: 'uri', value: value.toString(), fsPath: value.scheme === 'file' ? value.fsPath : '' };
  } else if (value instanceof vscode.Location) {
    rendered = {
      kind: 'location',
      uri: value.uri.toString(),
      fsPath: value.uri.scheme === 'file' ? value.uri.fsPath : '',
      range: {
        start: { line: value.range.start.line + 1, column: value.range.start.character + 1 },
        end: { line: value.range.end.line + 1, column: value.range.end.character + 1 },
      },
    };
  } else if (typeof value !== 'string') {
    // Unknown reference types không được ném object extension-host tùy ý qua WS.
    // modelDescription vẫn cho Eris biết ý nghĩa mà không phụ thuộc implementation.
    rendered = String(reference.modelDescription ?? reference.id ?? 'reference');
  }
  return {
    id: reference.id,
    modelDescription: reference.modelDescription ?? '',
    range: reference.range ? [...reference.range] : undefined,
    value: rendered,
  };
}

async function runBackendTurn(
  client: ErisClient,
  threadId: string,
  content: string,
  taskMode: 'execute' | 'inspect',
  ideContext: Record<string, unknown>,
  stream: vscode.ChatResponseStream,
  token: vscode.CancellationToken,
): Promise<{ taskId: string; status: string }> {
  return new Promise((resolve, reject) => {
    let taskId = '';
    let finished = false;
    let streamedText = '';
    let completionTimer: ReturnType<typeof setTimeout> | undefined;
    let inactivityTimer: ReturnType<typeof setTimeout> | undefined;
    const progressSeen = new Set<string>();

    const finish = (status: string) => {
      if (finished) {
        return;
      }
      finished = true;
      cleanup();
      resolve({ taskId, status });
    };
    const fail = (error: unknown) => {
      if (finished) {
        return;
      }
      finished = true;
      cleanup();
      reject(error instanceof Error ? error : new Error(String(error)));
    };
    const cleanup = () => {
      listener.dispose();
      cancelListener.dispose();
      if (inactivityTimer) {
        clearTimeout(inactivityTimer);
      }
      if (completionTimer) {
        clearTimeout(completionTimer);
      }
    };
    const progress = (label: string) => {
      const clean = label.trim();
      if (!clean || progressSeen.has(clean)) {
        return;
      }
      progressSeen.add(clean);
      stream.progress(clean);
    };
    const armInactivityWatchdog = () => {
      if (inactivityTimer) {
        clearTimeout(inactivityTimer);
      }
      inactivityTimer = setTimeout(() => {
        fail(new Error(
          'Eris không phát tiến độ trong 40 phút. Native Chat đã ngừng chờ; task backend có thể vẫn còn và có thể xem trong Eris Panel.',
        ));
      }, INACTIVITY_TIMEOUT_MS);
    };

    const listener = client.onEvent((event: any) => {
      const eventThread = String(event?.threadId ?? '');
      const eventTask = String(event?.taskId ?? '');
      if (event?.type === 'message.accepted' && eventThread === threadId) {
        taskId = eventTask || taskId;
        return;
      }
      if (eventThread !== threadId && (!taskId || eventTask !== taskId)) {
        return;
      }
      if (taskId && eventTask && eventTask !== taskId) {
        return;
      }
      if (!taskId && eventTask) {
        taskId = eventTask;
      }
      // Đây là inactivity watchdog, không còn là deadline cứng cho cả turn.
      // Task code 10-30 phút vẫn sống miễn backend còn phát event tiến độ.
      armInactivityWatchdog();

      const type = String(event?.type ?? '');
      const payload = event?.payload ?? {};
      if (type === 'message.assistant.delta') {
        const delta = String(payload.delta ?? '');
        if (delta) {
          streamedText += delta;
          stream.markdown(delta);
        }
        return;
      }
      if (type === 'message.assistant') {
        const finalText = String(payload.content ?? '');
        if (finalText) {
          if (!streamedText) {
            stream.markdown(finalText);
          } else if (finalText.startsWith(streamedText)) {
            stream.markdown(finalText.slice(streamedText.length));
          } else if (finalText !== streamedText) {
            stream.markdown(`\n\n${finalText}`);
          }
        }
        finish('completed');
        return;
      }
      if (type === 'interrupt.request') {
        renderInterrupt(stream, payload);
        finish(String(payload.reason ?? '') === 'tool_permission' ? 'waiting_permission' : 'waiting_user');
        return;
      }
      if (type === 'artifact.modified' || type === 'artifact.created') {
        const file = String(payload.path ?? '');
        if (file) {
          progress(`Đã sửa ${file}`);
          const uri = workspaceFileUri(file);
          if (uri) {
            stream.reference(uri);
          }
        }
        return;
      }
      if (type === 'changeset.created') {
        progress(`ChangeSet ${String(payload.changeSetId ?? '') || 'đã tạo'}`);
        return;
      }
      if (type === 'coding.state') {
        progress(String(payload.current_action ?? payload.phase ?? ''));
        return;
      }
      if (type.startsWith('activity.')) {
        progress(String(payload.label ?? payload.detail ?? ''));
        if (type === 'activity.end') {
          const status = String(payload.status ?? 'completed');
          if (status === 'failed' || status === 'stopped') {
            const detail = String(payload.detail ?? payload.label ?? status);
            stream.markdown(`\n\n**${status === 'failed' ? 'Task lỗi' : 'Task đã dừng'}:** ${escapeMarkdown(detail)}`);
            finish(status);
          } else if (status === 'completed') {
            // Protocol thường phát activity.end rồi mới message.assistant cho cùng
            // internal event. Chờ một nhịp ngắn để không nuốt mất final answer.
            completionTimer = setTimeout(() => finish('completed'), 700);
          }
        }
      }
    });

    const cancelListener = token.onCancellationRequested(() => {
      if (taskId) {
        void client.controlTask(taskId, 'pause', 'VS Code native chat cancelled', '', ideContext).catch(() => undefined);
      }
      finish('cancelled');
    });
    armInactivityWatchdog();

    void client.sendUserMessage(content, {
      threadId,
      taskMode,
      workspaceRef: currentWorkspaceRef(),
      context: ideContext,
    }).catch(fail);
  });
}

function renderInterrupt(stream: vscode.ChatResponseStream, payload: Record<string, any>): void {
  const question = String(payload.question ?? 'Eris cần thêm quyết định từ user.');
  const options = Array.isArray(payload.options) ? payload.options : [];
  let markdown = `\n\n**${escapeMarkdown(question)}**\n\n`;
  for (const option of options) {
    const label = String(option?.label ?? option?.id ?? 'Option');
    const description = String(option?.description ?? option?.desc ?? '');
    markdown += `- **${escapeMarkdown(label)}**${description ? `: ${escapeMarkdown(description)}` : ''}\n`;
  }
  markdown += '\nTrả lời trực tiếp trong `@eris` để LangGraph resume cùng thread.';
  stream.markdown(markdown);
}

function workspaceFileUri(file: string): vscode.Uri | undefined {
  const root = currentWorkspaceRef();
  if (!root) {
    return undefined;
  }
  const absolute = path.isAbsolute(file) ? file : path.join(root, file);
  return vscode.Uri.file(absolute);
}

function escapeMarkdown(value: string): string {
  return value.replace(/[\\`*_{}\[\]()#+.!|>-]/g, '\\$&');
}
