import * as vscode from 'vscode';
import { ErisChatPanel } from './chatPanel';
import { registerErisChatParticipant } from './chatParticipant';
import { captureIdeContext, resolveIdeContextRequest } from './contextBridge';
import { WorkspaceDiffProvider } from './diffProvider';
import { executeEditorCommand } from './editorBridge';
import { ConnectionState, ErisClient } from './erisClient';
import { TerminalContextObserver } from './terminalObserver';
import { ErisServiceManager } from './serviceManager';
import { runErisSelfTest } from './selfTest';


const ERIS_CONTAINER_ID = 'eris.sidebar';
const ERIS_CONTAINER_COMMAND = `workbench.view.extension.${ERIS_CONTAINER_ID}`;

/**
 * Mở Eris trong Primary Sidebar giống Cline.
 *
 * Activity Bar container là contribution native của VS Code nên icon Eris tồn
 * tại độc lập với backend. Service có chết thì UI vẫn mở và báo disconnected;
 * tuyệt đối không buộc user chạy run_eris.bat chỉ để nhìn thấy extension.
 */
async function revealErisSidebar(): Promise<void> {
  try {
    await vscode.commands.executeCommand(ERIS_CONTAINER_COMMAND);
  } catch {
    // Fallback: focus command của Webview vẫn đủ để VS Code reveal container.
  }
  await vscode.commands.executeCommand(`${ErisChatPanel.viewType}.focus`);
}

type SidebarKind = 'command' | 'group' | 'task' | 'chat' | 'skill' | 'status';
interface SidebarNode {
  kind: SidebarKind;
  label: string;
  description?: string;
  command?: string;
  args?: unknown[];
  icon?: string;
  children?: SidebarNode[];
}

/** Navigator phụ nằm dưới Chat trong Eris Primary Sidebar; mặc định collapse để không tranh diện tích. */
class ErisSidebarProvider implements vscode.TreeDataProvider<SidebarNode>, vscode.Disposable {
  private readonly changed = new vscode.EventEmitter<SidebarNode | undefined | void>();
  readonly onDidChangeTreeData = this.changed.event;
  private state: ConnectionState = 'disconnected';
  private tasks: any[] = [];
  private skills: any[] = [];

  setState(state: ConnectionState): void {
    this.state = state;
    this.changed.fire();
  }

  observeEvent(event: any): void {
    if (event?.type === 'session.ready' || event?.type === 'task.list') {
      this.tasks = Array.isArray(event.tasks) ? event.tasks : this.tasks;
      const brain = event.capabilities?.brain;
      if (Array.isArray(brain?.skills)) {
        this.skills = brain.skills;
      }
      this.changed.fire();
      return;
    }
    const taskId = String(event?.taskId ?? '');
    if (!taskId) {
      return;
    }
    let task = this.tasks.find((item) => String(item?.task_id ?? '') === taskId);
    if (!task) {
      task = {
        task_id: taskId,
        thread_id: String(event?.threadId ?? ''),
        goal: String(event?.type === 'message.user' ? (event?.payload?.content ?? 'Agent task') : (event?.payload?.label ?? 'Agent task')),
        status: 'running',
        coding_state: {},
      };
      this.tasks.unshift(task);
      this.tasks = this.tasks.slice(0, 50);
    }
    if (event.type === 'message.user' && !task.goal) {
      task.goal = String(event.payload?.content ?? 'Agent task');
    } else if (event.type === 'coding.state') {
      task.coding_state = { ...(task.coding_state ?? {}), ...(event.payload ?? {}) };
      task.status = task.coding_state?.phase === 'waiting_user' ? 'waiting_user' : (task.status || 'running');
    } else if (event.type === 'activity.end') {
      task.status = String(event.payload?.status ?? 'completed');
    } else if (event.type === 'interrupt.request') {
      task.status = event.payload?.reason === 'tool_permission' ? 'waiting_permission' : 'waiting_user';
    } else if (event.type === 'interrupt.resolved') {
      task.status = 'running';
    } else if (String(event.type).startsWith('activity.')) {
      const status = String(event.payload?.status ?? '');
      if (status) {
        task.status = status;
      }
    }
    this.changed.fire();
  }

  getTreeItem(element: SidebarNode): vscode.TreeItem {
    const collapsible = element.children
      ? vscode.TreeItemCollapsibleState.Expanded
      : vscode.TreeItemCollapsibleState.None;
    const item = new vscode.TreeItem(element.label, collapsible);
    item.description = element.description;
    if (element.icon) {
      item.iconPath = new vscode.ThemeIcon(element.icon);
    }
    if (element.command) {
      item.command = { command: element.command, title: element.label, arguments: element.args };
    }
    return item;
  }

  getChildren(element?: SidebarNode): SidebarNode[] {
    if (element?.children) {
      return element.children;
    }
    if (element) {
      return [];
    }

    const uniqueThreads = new Map<string, any>();
    for (const task of this.tasks) {
      const thread = String(task?.thread_id ?? '');
      if (thread && !uniqueThreads.has(thread)) {
        uniqueThreads.set(thread, task);
      }
    }
    const chatChildren = [...uniqueThreads.values()].slice(0, 12).map((task): SidebarNode => ({
      kind: 'chat',
      label: String(task.goal ?? task.clarified_goal ?? 'Chat').slice(0, 64),
      description: String(task.status ?? ''),
      icon: 'comment-discussion',
      command: 'eris.openTask',
      args: [String(task.task_id ?? ''), String(task.thread_id ?? '')],
    }));
    const taskChildren = this.tasks.slice(0, 16).map((task): SidebarNode => {
      const coding = task.coding_state ?? {};
      const detail = String(coding.current_action ?? task.status ?? '');
      const status = String(task.status ?? '');
      return {
        kind: 'task',
        label: String(task.goal ?? task.clarified_goal ?? 'Agent task').slice(0, 64),
        description: detail.slice(0, 42),
        icon: status === 'completed' ? 'pass' : status === 'failed' ? 'error' : status.includes('waiting') ? 'question' : 'run',
        command: 'eris.openTask',
        args: [String(task.task_id ?? ''), String(task.thread_id ?? '')],
      };
    });
    const skillChildren = this.skills.slice(0, 18).map((skill): SidebarNode => ({
      kind: 'skill',
      label: String(skill.name ?? skill.skill_name ?? 'skill'),
      description: String(skill.health ?? ''),
      icon: 'tools',
      command: 'eris.openChat',
    }));

    return [
      { kind: 'command', label: 'New Chat', icon: 'add', command: 'eris.newChat' },
      {
        kind: 'group',
        label: 'Chats',
        description: chatChildren.length ? `${chatChildren.length}` : 'empty',
        icon: 'comment-discussion',
        children: chatChildren.length ? chatChildren : [{ kind: 'status', label: 'Chưa có hội thoại', icon: 'circle-outline' }],
      },
      {
        kind: 'group',
        label: 'Plans',
        description: taskChildren.length ? `${taskChildren.length} task` : 'empty',
        icon: 'checklist',
        children: taskChildren.length ? taskChildren : [{ kind: 'status', label: 'Chưa có task', icon: 'circle-outline' }],
      },
      {
        kind: 'group',
        label: 'Skills',
        description: skillChildren.length ? `${skillChildren.length}` : 'loading',
        icon: 'tools',
        children: skillChildren.length ? skillChildren : [{ kind: 'status', label: 'Chưa nhận catalog', icon: 'circle-outline' }],
      },
      { kind: 'command', label: 'Run Self Test', icon: 'beaker', command: 'eris.selfTest' },
      {
        kind: 'status',
        label: `Service: ${this.state}`,
        icon: this.state === 'connected' ? 'vm-active' : 'debug-disconnect',
        command: 'eris.reconnect',
      },
    ];
  }

  dispose(): void {
    this.changed.dispose();
  }
}

export function activate(context: vscode.ExtensionContext): void {
  const serviceManager = new ErisServiceManager(context);
  const client = new ErisClient(context, serviceManager);
  const sidebar = new ErisSidebarProvider();
  const terminalObserver = new TerminalContextObserver();
  const diffProvider = new WorkspaceDiffProvider();
  const chatPanel = new ErisChatPanel(
    context.extensionUri, client, context, terminalObserver, diffProvider,
  );
  context.subscriptions.push(serviceManager, client, sidebar, terminalObserver, diffProvider, chatPanel);
  context.subscriptions.push(vscode.window.registerWebviewViewProvider(
    ErisChatPanel.viewType,
    chatPanel,
    { webviewOptions: { retainContextWhenHidden: true } },
  ));
  context.subscriptions.push(vscode.window.registerTreeDataProvider('eris.navigatorView', sidebar));
  registerErisChatParticipant(context, client, terminalObserver);
  context.subscriptions.push(client.onStateChanged((state) => sidebar.setState(state)));
  context.subscriptions.push(client.onEvent((event) => {
    sidebar.observeEvent(event);

    // Live IDE RPC/editor actions phải hoạt động ngay cả khi Chat Panel chưa mở.
    // Nếu gắn handler vào Webview, task background sau restart sẽ timeout rất vô duyên.
    if (event?.type === 'ide.request') {
      const payload = event.payload ?? {};
      const requestId = String(payload.requestId ?? '');
      const method = String(payload.method ?? '');
      void resolveIdeContextRequest(
        method,
        payload.params && typeof payload.params === 'object' ? payload.params : {},
        terminalObserver,
      ).then((data) => client.reportIdeResponse(
        String(event.taskId ?? ''), requestId, method, true, data, '',
      )).catch((error) => client.reportIdeResponse(
        String(event.taskId ?? ''), requestId, method, false, {}, String(error),
      ).catch(() => undefined));
      return;
    }
    if (event?.type === 'editor.command') {
      const payload = event.payload ?? {};
      const requestId = String(payload.requestId ?? '');
      const command = String(payload.command ?? '');
      void executeEditorCommand(payload, diffProvider).then((message) => client.reportEditorCommandResult(
        String(event.taskId ?? ''), requestId, command, true, message,
      )).catch((error) => client.reportEditorCommandResult(
        String(event.taskId ?? ''), requestId, command, false, String(error),
      ).catch(() => undefined));
      return;
    }
    if (event?.type === 'session.ready') {
      // Chỉ recover task VS Code của đúng session. Nếu Python process vừa restart,
      // status vẫn là running trong SQLite nhưng worker cũ đã chết. Control plane
      // phía backend phân biệt được case đó và resume checkpoint; worker còn sống
      // thì resume là no-op idempotent.
      const tasks = Array.isArray(event.tasks) ? event.tasks : [];
      const recoverable = tasks.filter((task: any) =>
        String(task?.status ?? '') === 'running'
        && String(task?.session_id ?? '') === String(event.sessionId ?? '')
        && String(task?.metadata?.source ?? '') === 'vscode',
      );
      if (recoverable.length) {
        void captureIdeContext(terminalObserver).then(async (ideContext) => {
          for (const task of recoverable) {
            await client.controlTask(String(task.task_id ?? ''), 'resume', '', '', ideContext);
          }
        }).catch(() => undefined);
      }
    }
  }));

  const openChat = async () => {
    await revealErisSidebar();
    await chatPanel.show(false);
  };
  context.subscriptions.push(vscode.commands.registerCommand('eris.openChat', openChat));
  context.subscriptions.push(vscode.commands.registerCommand('eris.newChat', async () => {
    await revealErisSidebar();
    await chatPanel.show(false);
    chatPanel.newChat();
  }));
  context.subscriptions.push(vscode.commands.registerCommand('eris.openTask', async (taskId: string, threadId: string) => {
    await chatPanel.selectTask(taskId, threadId);
  }));
  context.subscriptions.push(vscode.commands.registerCommand('eris.reconnect', async () => {
    try {
      await client.connect(true);
      await client.requestTasks();
      void vscode.window.showInformationMessage('Eris Service đã kết nối lại.');
    } catch (error) {
      void vscode.window.showErrorMessage(String(error));
    }
  }));

  context.subscriptions.push(vscode.commands.registerCommand('eris.selfTest', () => runErisSelfTest(
    client, serviceManager, terminalObserver,
  )));

  context.subscriptions.push(vscode.commands.registerCommand('eris.serviceStart', async () => {
    try {
      await serviceManager.ensureStarted();
      await client.connect(true);
      await client.requestTasks();
      void vscode.window.showInformationMessage('Eris Service đã sẵn sàng.');
    } catch (error) {
      serviceManager.showLogs();
      void vscode.window.showErrorMessage(String(error));
    }
  }));
  context.subscriptions.push(vscode.commands.registerCommand('eris.serviceRestart', async () => {
    try {
      await serviceManager.restart();
      await client.connect(true);
      await client.requestTasks();
      void vscode.window.showInformationMessage('Eris Service đã restart.');
    } catch (error) {
      serviceManager.showLogs();
      void vscode.window.showErrorMessage(String(error));
    }
  }));
  context.subscriptions.push(vscode.commands.registerCommand('eris.serviceStop', async () => {
    await serviceManager.stopOwned();
    void vscode.window.showInformationMessage('Đã dừng Eris process do VS Code launch.');
  }));
  context.subscriptions.push(vscode.commands.registerCommand('eris.serviceLogs', () => serviceManager.showLogs()));

  // UI Eris không phụ thuộc backend: icon Activity Bar + Webview được VS Code
  // đóng góp trực tiếp từ package.json. Auto-start dưới đây chỉ lo service.
  const autoStart = vscode.workspace.getConfiguration('eris.service').get<boolean>('autoStart', true);
  if (autoStart) {
    void client.connect().then(() => client.requestTasks()).catch(() => undefined);
  }
}

export function deactivate(): void {
  // Disposable được VS Code thu dọn qua ExtensionContext.
}
