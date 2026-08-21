/**
 * Eris → Cline Event Relay
 *
 * Translate Cline SDK event stream sang format Eris WebSocket protocol.
 * Extension TypeScript (chatPanel.ts) không cần biết Cline tồn tại;
 * nó chỉ nhìn thấy events giống như từ Python backend.
 *
 * Eris WS event format (hiện tại):
 * {
 *   type: string,         // e.g. "activity.start", "message.assistant", "coding.state"
 *   taskId: string,
 *   eventId: string,
 *   payload: object,
 *   timestamp: string,
 * }
 */

export interface ErisWsEvent {
  type: string;
  taskId: string;
  eventId: string;
  payload: Record<string, unknown>;
  timestamp: string;
  seq?: number;
}

let _seq = 0;
function nextSeq(): number {
  return ++_seq;
}

function makeEvent(
  type: string,
  taskId: string,
  payload: Record<string, unknown>,
): ErisWsEvent {
  return {
    type,
    taskId,
    eventId: `cline_${Date.now()}_${nextSeq()}`,
    payload,
    timestamp: new Date().toISOString(),
    seq: nextSeq(),
  };
}

/**
 * Cline SDK phát ra các events qua session listeners.
 * Hàm này nhận raw Cline event và trả về Eris WS event tương ứng.
 * Trả về null nếu event không cần relay (nội bộ Cline).
 */
export function translateClineEvent(
  clineEventType: string,
  data: unknown,
  taskId: string,
): ErisWsEvent | null {
  const d = (data && typeof data === 'object' ? data : {}) as Record<string, unknown>;

  switch (clineEventType) {
    // Streaming text delta từ LLM
    case 'content_delta': {
      const delta = String(d['delta'] ?? '');
      if (!delta) return null;
      return makeEvent('message.assistant.delta', taskId, { delta });
    }

    // LLM hoàn tất 1 turn text
    case 'content_end': {
      const text = String(d['text'] ?? '');
      return makeEvent('message.assistant', taskId, { content: text });
    }

    // Tool bắt đầu chạy
    case 'tool_start': {
      const toolName = String(d['name'] ?? 'tool');
      const label = humanToolLabel(toolName, d['input'] as Record<string, unknown> ?? {});
      return makeEvent('activity.start', taskId, {
        label,
        status: 'running',
        data: { tool: toolName },
      });
    }

    // Tool hoàn tất
    case 'tool_finish': {
      const toolName = String(d['name'] ?? 'tool');
      const success = d['error'] == null;
      const label = humanToolLabel(toolName, {});
      return makeEvent('activity.end', taskId, {
        label,
        status: success ? 'completed' : 'failed',
        data: { tool: toolName, error: d['error'] ?? null },
      });
    }

    // File được modified
    case 'file_write': {
      const path = String(d['path'] ?? '');
      if (!path) return null;
      return makeEvent('artifact.modified', taskId, { path, diff: d['diff'] ?? '' });
    }

    // Agent hoàn tất toàn bộ task
    case 'agent_done': {
      const success = !d['error'];
      return makeEvent(success ? 'task_completed' : 'task_failed', taskId, {
        final: String(d['result'] ?? d['error'] ?? ''),
        status: success ? 'completed' : 'failed',
      });
    }

    // Approval request (Cline hỏi trước khi write)
    case 'approval_request': {
      const question = String(d['question'] ?? 'Cline cần xác nhận');
      const options = Array.isArray(d['options']) ? d['options'] : [
        { id: 'approve', label: 'Cho phép', description: 'Tiếp tục thực thi' },
        { id: 'deny', label: 'Từ chối', description: 'Dừng lại' },
      ];
      return makeEvent('interrupt.request', taskId, {
        question,
        options,
        allowOther: false,
        source: 'cline_approval',
      });
    }

    default:
      return null;
  }
}

/**
 * Tạo human-readable label từ tên tool Cline.
 * Tương tự `human_tool_label` trong coding_state.py.
 */
function humanToolLabel(
  toolName: string,
  args: Record<string, unknown>,
): string {
  const path = String(args['path'] ?? args['file'] ?? '');
  const cmd = String(args['command'] ?? args['cmd'] ?? '');
  const query = String(args['query'] ?? args['pattern'] ?? '');

  const labels: Record<string, string> = {
    read_file: `Đọc ${path || 'file'}`,
    write_file: `Ghi ${path || 'file'}`,
    apply_patch: `Patch ${path || 'file'}`,
    execute_command: `Chạy: ${cmd.slice(0, 60) || 'terminal'}`,
    search_files: `Tìm: ${query.slice(0, 60) || 'pattern'}`,
    list_files: `Liệt kê ${path || 'thư mục'}`,
    browser_action: 'Thao tác browser',
    ask_followup_question: 'Hỏi thêm',
    submit_and_exit: 'Hoàn tất task',
  };

  return labels[toolName] ?? toolName;
}
