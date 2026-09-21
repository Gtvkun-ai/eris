"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.actorFromStatus = actorFromStatus;
exports.createCodingObservation = createCodingObservation;
exports.userIntentObservation = userIntentObservation;
exports.fromGitPilotEvent = fromGitPilotEvent;
exports.taskLifecycleObservation = taskLifecycleObservation;
const ROLE_MAP = {
    explorer: 'explorer',
    planner: 'planner',
    developer: 'coder',
    coder: 'coder',
    reviewer: 'reviewer',
    verify: 'validation',
    validation: 'validation',
    done: 'gitpilot',
};
function actorFromStatus(status, fallback) {
    const key = String(status ?? '').trim().toLowerCase();
    return ROLE_MAP[key] ?? fallback;
}
function text(value, limit = 900) {
    let output = String(value ?? '').replace(/\u0000/g, '').replace(/\r/g, '').trim();
    // Không đẩy token/key tình cờ xuất hiện trong command, prompt hoặc lỗi vào Desktop journal.
    output = output
        .replace(/(api[_-]?key|token|authorization|password|secret)\s*[:=]\s*[^\s,;]+/gi, '$1=<redacted>')
        .replace(/Bearer\s+[A-Za-z0-9._~+\/-]+/gi, 'Bearer <redacted>');
    return output.slice(0, limit);
}
function cleanPath(value) {
    return text(value, 520).replace(/\\/g, '/');
}
function pathsFrom(event) {
    const found = [];
    const add = (value) => {
        const path = cleanPath(value);
        if (path && !found.includes(path))
            found.push(path);
    };
    add(event.path);
    const args = event.arguments && typeof event.arguments === 'object' ? event.arguments : {};
    for (const key of ['file_path', 'path', 'filename', 'target'])
        add(args[key]);
    return found.slice(0, 8);
}
function commandFrom(event) {
    const args = event.arguments && typeof event.arguments === 'object' ? event.arguments : {};
    const raw = args.command ?? args.cmd ?? args.script;
    const clean = text(raw, 320);
    return clean || undefined;
}
function base(ctx, eventType, actor = ctx.actor, source = 'eris-code/gitpilot') {
    return {
        schema: 'eris.coding.observation.v1',
        source,
        task_id: ctx.taskId,
        session_id: ctx.sessionId,
        thread_id: ctx.threadId,
        workspace: ctx.workspace,
        actor,
        event_type: eventType,
        at: Date.now() / 1000,
    };
}
function createCodingObservation(args) {
    const observation = base({
        taskId: text(args.taskId, 160),
        sessionId: text(args.sessionId, 160),
        threadId: text(args.threadId ?? '', 160),
        workspace: cleanPath(args.workspace),
        actor: args.actor,
    }, args.eventType, args.actor, args.source);
    if (args.files?.length) {
        observation.files = [...new Set(args.files.map(cleanPath).filter(Boolean))].slice(0, 12);
    }
    const command = text(args.command, 320);
    if (command)
        observation.command = command;
    const status = text(args.status, 80);
    if (status)
        observation.status = status;
    const evidence = text(args.evidence, args.eventType === 'phase_summary' ? 2600 : 800);
    if (evidence)
        observation.evidence = evidence;
    if (args.metrics)
        observation.metrics = { ...args.metrics };
    return observation;
}
function userIntentObservation(content, ctx) {
    return createCodingObservation({
        eventType: 'user_intent',
        source: 'eris-code/user',
        taskId: ctx.taskId,
        sessionId: ctx.sessionId,
        threadId: ctx.threadId,
        workspace: ctx.workspace,
        actor: 'user',
        // Đây là prompt công khai user vừa gửi coding agent, không phải hidden CoT.
        evidence: text(content, 800),
    });
}
/** Chuyển raw GitPilot SSE thành telemetry nhỏ, không chép raw file content. */
function fromGitPilotEvent(event, ctx) {
    const type = String(event.type ?? '');
    let actor = ctx.actor;
    if (type === 'status_change') {
        if (String(event.status ?? '') === 'keepalive')
            return { actor };
        actor = actorFromStatus(event.status, actor);
        const observation = base({ ...ctx, actor }, 'phase_changed', actor);
        observation.status = text(event.status, 80);
        observation.evidence = text(event.message, 320);
        return { observation, actor };
    }
    if (type === 'plan_step') {
        const action = String(event.action ?? '');
        const stepActor = actorFromStatus(action, actor);
        const observation = base(ctx, 'plan_step', stepActor);
        observation.status = text(event.status, 80);
        observation.evidence = text(event.title, 320);
        observation.metrics = { step_index: Number(event.step_index ?? 0) };
        return { observation, actor: stepActor };
    }
    if (type === 'phase_summary') {
        const summaryActor = actorFromStatus(event.actor, actor);
        const observation = base(ctx, 'phase_summary', summaryActor);
        // Đây là output công khai của specialist, không phải hidden chain-of-thought.
        observation.evidence = text(event.summary, 2600);
        return { observation, actor: summaryActor };
    }
    if (type === 'tool_start') {
        const observation = base(ctx, 'tool_started', actor);
        observation.tool = text(event.name, 120);
        observation.files = pathsFrom(event);
        observation.command = commandFrom(event);
        return { observation, actor };
    }
    if (type === 'tool_result') {
        const observation = base(ctx, 'tool_finished', actor);
        observation.tool = text(event.name, 120);
        observation.status = event.is_error ? 'error' : 'ok';
        // Chỉ giữ một excerpt lỗi/summary. Không log raw read_file result vì đó là source code.
        if (event.is_error)
            observation.evidence = text(event.result, 700);
        observation.metrics = { is_error: Boolean(event.is_error) };
        return { observation, actor };
    }
    if (type === 'file_write') {
        const observation = base(ctx, 'file_changed', actor);
        observation.files = pathsFrom(event);
        observation.status = text(event.action ?? 'modify', 80);
        return { observation, actor };
    }
    if (type === 'approval_needed') {
        const observation = base(ctx, 'approval_requested', actor);
        observation.tool = text(event.tool, 120);
        observation.files = pathsFrom(event);
        observation.status = text(event.risk_level ?? 'medium', 40);
        observation.evidence = text(event.summary, 480);
        return { observation, actor };
    }
    if (type === 'approval_resolved') {
        const observation = base(ctx, 'approval_resolved', actor);
        observation.status = event.approved ? 'approved' : 'denied';
        return { observation, actor };
    }
    if (type === 'test_result') {
        const observation = base(ctx, 'test_result', 'validation');
        observation.status = Number(event.failed ?? 0) > 0 ? 'failed' : 'passed';
        observation.evidence = text(event.framework, 120);
        observation.metrics = {
            passed: Number(event.passed ?? 0),
            failed: Number(event.failed ?? 0),
            skipped: Number(event.skipped ?? 0),
            exit_code: Number(event.exit_code ?? 0),
        };
        return { observation, actor: 'validation' };
    }
    if (type === 'diagnostics') {
        const observation = base(ctx, 'diagnostics', 'validation');
        observation.status = Number(event.errors ?? 0) > 0 ? 'failed' : 'passed';
        observation.metrics = { errors: Number(event.errors ?? 0), warnings: Number(event.warnings ?? 0) };
        return { observation, actor: 'validation' };
    }
    if (type === 'done') {
        const observation = base(ctx, 'task_completed', 'gitpilot');
        // Summary đầy đủ có thể chứa code; chỉ ghi dấu hoàn tất, journal tự tổng hợp từ evidence trước đó.
        observation.status = 'completed';
        return { observation, actor: 'gitpilot' };
    }
    if (type === 'error') {
        const observation = base(ctx, 'task_failed', actor);
        observation.status = 'failed';
        observation.evidence = text(event.error, 700);
        return { observation, actor };
    }
    return { actor };
}
function taskLifecycleObservation(eventType, ctx, evidence = '') {
    const observation = base(ctx, eventType, eventType === 'task_started' ? 'gitpilot' : ctx.actor);
    observation.status = eventType === 'task_started' ? 'running' : eventType === 'task_cancelled' ? 'cancelled' : 'failed';
    if (evidence)
        observation.evidence = text(evidence, 700);
    return observation;
}
//# sourceMappingURL=codingObservation.js.map