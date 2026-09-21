/**
 * Sessions Tree View Provider
 *
 * Displays active/paused/completed sessions in the sidebar.
 * Allows creating, resuming, and deleting sessions.
 */
import * as vscode from 'vscode';
import { GitPilotApiClient, SessionInfo } from '../api/client';

export class SessionsTreeProvider implements vscode.TreeDataProvider<SessionTreeItem> {
    private _onDidChangeTreeData = new vscode.EventEmitter<SessionTreeItem | undefined>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

    constructor(private readonly _client: GitPilotApiClient) {}

    refresh(): void {
        this._onDidChangeTreeData.fire(undefined);
    }

    getTreeItem(element: SessionTreeItem): vscode.TreeItem {
        return element;
    }

    async getChildren(element?: SessionTreeItem): Promise<SessionTreeItem[]> {
        if (element) { return []; }
        if (!this._client.isConnected) {
            return [new SessionTreeItem('Not connected', '', 'disconnected', 'info')];
        }

        try {
            const sessions = await this._client.listSessions();
            if (sessions.length === 0) {
                return [new SessionTreeItem('No sessions yet', '', 'empty', 'info')];
            }
            return sessions.map(s => new SessionTreeItem(
                sessionLabel(s),
                s.id,
                s.status || 'active',
                'session',
                s,
            ));
        } catch {
            return [new SessionTreeItem('Failed to load sessions', '', 'error', 'info')];
        }
    }
}

export class SessionTreeItem extends vscode.TreeItem {
    constructor(
        label: string,
        public readonly sessionId: string,
        public readonly status: string,
        public readonly itemType: 'session' | 'info',
        public readonly session?: SessionInfo,
    ) {
        super(label, vscode.TreeItemCollapsibleState.None);

        if (itemType === 'info') {
            this.iconPath = new vscode.ThemeIcon('info');
            return;
        }

        const icons: Record<string, string> = {
            active: 'play-circle',
            paused: 'debug-pause',
            completed: 'check',
        };
        this.iconPath = new vscode.ThemeIcon(icons[status] || 'circle-outline');
        this.description = `${session?.message_count || 0} msgs · ${status}`;
        this.tooltip = `Session: ${sessionId}\nRepo: ${sessionRepo(session)}\nStatus: ${status}\nMessages: ${session?.message_count || 0}`;
        this.contextValue = 'session';

        this.command = {
            command: 'gitpilot.loadSession',
            title: 'Load Session',
            arguments: [sessionId],
        };
    }
}

function sessionLabel(session: SessionInfo): string {
    return (
        session.title ||
        session.name ||
        session.repo ||
        joinedRepo(session) ||
        (session.branch ? `Local Git (${session.branch})` : 'Untitled session')
    );
}

function sessionRepo(session?: SessionInfo): string {
    if (!session) { return 'Unknown'; }
    return session.repo || joinedRepo(session) || (session.branch ? `Local branch: ${session.branch}` : 'Local workspace');
}

function joinedRepo(session: SessionInfo): string {
    return session.repo_owner && session.repo_name ? `${session.repo_owner}/${session.repo_name}` : '';
}
