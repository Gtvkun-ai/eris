import * as vscode from 'vscode';
import { ErisChatPanel } from './chatPanel';
import { ConnectionState, ErisClient } from './erisClient';

type SidebarKind = 'command' | 'group' | 'task' | 'skill' | 'status';
interface SidebarNode {
  kind: SidebarKind;
  label: string;
  description?: string;
  command?: string;
  icon?: string;
  children?: SidebarNode[];
}

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
    if (event?.type === 'session.ready') {
      this.tasks = Array.isArray(event.tasks) ? event.tasks : [];
      const brain = event.capabilities?.brain;
      this.skills = Array.isArray(brain?.skills) ? brain.skills : [];
      this.changed.fire();
      return;
    }
    const taskId = String(event?.taskId ?? '');
    if (!taskId) {
      return;
    }
    const task = this.tasks.find((item) => String(item?.task_id ?? '') === taskId);
    if (!task) {
      if (event.type === 'activity.start') {
        this.tasks.unshift({ task_id: taskId, goal: event.payload?.label ?? 'Agent task', status: 'running' });
        this.tasks = this.tasks.slice(0, 24);
        this.changed.fire();
      }
      return;
    }
    if (event.type === 'activity.end') {
      task.status = String(event.payload?.status ?? 'completed');
    } else if (event.type === 'interrupt.request') {
      task.status = event.payload?.reason === 'tool_permission' ? 'waiting_permission' : 'waiting_user';
    } else if (String(event.type).startsWith('activity.')) {
      task.status = String(event.payload?.status ?? task.status ?? 'running');
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
      item.command = { command: element.command, title: element.label };
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
    const taskChildren = this.tasks.slice(0, 12).map((task): SidebarNode => ({
      kind: 'task',
      label: String(task.goal ?? task.clarified_goal ?? 'Agent task').slice(0, 70),
      description: String(task.status ?? ''),
      icon: task.status === 'completed' ? 'pass' : task.status === 'failed' ? 'error' : 'run',
      command: 'eris.openChat',
    }));
    const skillChildren = this.skills.slice(0, 18).map((skill): SidebarNode => ({
      kind: 'skill',
      label: String(skill.name ?? skill.skill_name ?? 'skill'),
      description: String(skill.health ?? ''),
      icon: 'tools',
      command: 'eris.openChat',
    }));
    return [
      { kind: 'command', label: 'New Chat', icon: 'add', command: 'eris.newChat' },
      { kind: 'command', label: 'Current Chat', icon: 'comment-discussion', command: 'eris.openChat' },
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
  const client = new ErisClient(context);
  const sidebar = new ErisSidebarProvider();
  context.subscriptions.push(client, sidebar);
  context.subscriptions.push(vscode.window.registerTreeDataProvider('eris.sidebar', sidebar));
  context.subscriptions.push(client.onStateChanged((state) => sidebar.setState(state)));
  context.subscriptions.push(client.onEvent((event) => sidebar.observeEvent(event)));

  const openChat = () => ErisChatPanel.show(context.extensionUri, client, context);
  context.subscriptions.push(vscode.commands.registerCommand('eris.openChat', openChat));
  context.subscriptions.push(vscode.commands.registerCommand('eris.newChat', () => {
    const panel = openChat();
    panel.newChat();
  }));
  context.subscriptions.push(vscode.commands.registerCommand('eris.reconnect', async () => {
    try {
      await client.connect(true);
      void vscode.window.showInformationMessage('Eris Service đã kết nối lại.');
    } catch (error) {
      void vscode.window.showErrorMessage(String(error));
    }
  }));

  // Kết nối sớm để sidebar phản ánh trạng thái thật, nhưng extension vẫn sống nếu
  // Python service chưa chạy. Khi service xuất hiện, client sẽ reconnect tự động.
  void client.connect().catch(() => undefined);
}

export function deactivate(): void {
  // Disposable được VS Code thu dọn qua ExtensionContext.
}
