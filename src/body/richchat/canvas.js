'use strict';
// The browser is a presentation/client layer. All focus, grading and mastery
// decisions belong to runtime.learning_canvas in the Python backend.
(() => {
  const byId = id => document.getElementById(id);
  const state = {
    snapshot: null, selected: '', mode: 'map', pending: null, desiredNode: '',
    details: new Map(), activities: new Map(), drafts: new Map(), answers: new Map(),
    playback: null, playbackSeq: -1, playbackStream: '',
    lastVersion: -1, lastPoll: 0, lastExercisePoll: 0, lastCause: '',
    busy: false, bootstrapped: false, status: 'Đang kết nối với Eris...', offline: false,
  };
  const labels = {available: 'Có thể học', learning: 'Đang học', practicing: 'Đang luyện', mastered: 'Đã vững'};
  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function nodeById(id) {return (state.snapshot?.nodes || []).find(n => n.id === id);}
  function currentActivity() {return state.activities.get(state.selected);}
  function setStatus(value) {state.status = value; byId('status').textContent = value;}
  function errMessage(reason) {
    const known = {
      stale_canvas_revision:'Bản đồ đã được Eris cập nhật. Hãy chọn lại kiến thức.',
      canvas_focus_changed:'Eris vừa đổi trọng tâm học. Vui lòng thử lại.',
      canvas_exercise_running:'Bài Java vẫn đang chạy.',
      canvas_submission_budget_exceeded:'Bạn đã dùng hết lượt nộp bài này.'
    };
    return known[reason] || reason || 'Không thể đồng bộ. Hãy thử lại.';
  }
  function requestId() {
    const uuid = globalThis.crypto?.randomUUID?.();
    return 'web-' + (uuid || `${Date.now()}-${Math.random().toString(36).slice(2)}`);
  }
  async function send(action, fields = {}) {
    if (state.pending || (!state.snapshot && action !== 'open')) return false;
    const request_id = requestId();
    const packet = {request_id, action, ...fields};
    if (action !== 'open') packet.base_revision = state.snapshot.focus.revision;
    state.pending = {request_id, action, started: Date.now()};
    setStatus('Đang đồng bộ với Eris...');
    renderButtons();
    try {
      const response = await fetch('api/canvas/request', {method:'POST',
        headers:{'Content-Type':'application/json'}, body:JSON.stringify(packet), cache:'no-store'});
      if (!response.ok) throw new Error('Yêu cầu bị từ chối (' + response.status + ')');
      return true;
    } catch (error) {
      state.pending = null;
      setStatus('Không gửi được yêu cầu: ' + error.message);
      renderButtons();
      return false;
    }
  }
  function mergeActivity(activity) {
    if (!activity || !activity.node_id || !activity.activity_id) return;
    const prev = state.activities.get(activity.node_id);
    if (prev) {
      if ((activity.created_at || 0) < (prev.created_at || 0)) return;
      if (activity.activity_id === prev.activity_id &&
          (activity.submitted_at || 0) < (prev.submitted_at || 0)) return;
      if (activity.activity_id === prev.activity_id && activity.submission_id &&
          activity.submission_id === prev.submission_id && prev.status !== 'running' && activity.status === 'running') return;
    }
    state.activities.set(activity.node_id, activity);
    if (activity.type === 'java' && !state.drafts.has(activity.activity_id))
      state.drafts.set(activity.activity_id, activity.code || '');
  }
  function observePlayback(packet) {
    if (!packet || !Number.isSafeInteger(packet.seq)) return;
    if (packet.stream_id && state.playbackStream && packet.stream_id !== state.playbackStream) return;
    if (packet.seq <= state.playbackSeq) return;
    state.playbackSeq = packet.seq;
    state.playback = packet.final ? null : packet;
  }
  function ingest(payload) {
    if (!payload || typeof payload !== 'object') return;
    if (payload.version === state.lastVersion) return;
    state.lastVersion = payload.version;
    const snapshot = payload.learning_canvas;
    const restarted = !!(snapshot?.playback_stream_id && state.playbackStream &&
      snapshot.playback_stream_id !== state.playbackStream);
    if (snapshot?.schema === 'eris.learning.canvas.v1' && Array.isArray(snapshot.nodes) && snapshot.focus) {
      const previous = state.snapshot;
      if (restarted || !previous || snapshot.focus.revision >= previous.focus.revision) {
        if (restarted) {state.details.clear();state.activities.clear();state.lastCause = '';}
        state.snapshot = snapshot;
        if (snapshot.detail?.id) state.details.set(snapshot.detail.id, snapshot.detail);
        mergeActivity(snapshot.activity);
        if (snapshot.playback_stream_id && snapshot.playback_stream_id !== state.playbackStream) {
          state.playbackStream = snapshot.playback_stream_id;
          state.playbackSeq = -1;
          state.playback = null;
        }
        observePlayback(snapshot.playback);
        if (!state.pending || state.pending.action !== 'navigate')
          state.selected = snapshot.focus.node_id || state.selected;
        if (previous?.focus.node_id !== snapshot.focus.node_id && !state.pending)
          state.mode = 'detail';
        const cause = snapshot.focus.cause_id;
        if (cause && cause !== snapshot.focus.acknowledged_cause_id && cause !== state.lastCause && !state.pending && !state.desiredNode) {
          state.lastCause = cause;
          // This is merely an acknowledgment; never navigate on an Eris-initiated focus change.
          queueMicrotask(() => send('ack_eris_focus', {cause_id:cause}));
        }
      }
    }
    mergeActivity(payload.exercise_update);
    observePlayback(payload.playback);
    if (state.pending) {
      const ack = (payload.acks || []).find(a => a.request_id === state.pending.request_id);
      if (ack) {
        const action = state.pending.action;
        state.pending = null;
        if (ack.status === 'ok') {
          setStatus('Đã đồng bộ · Tiến độ được xác nhận từ bài làm');
        } else {
          setStatus(errMessage(ack.message || ack.status));
          if (action === 'navigate') state.selected = state.snapshot?.focus?.node_id || state.selected;
        }
      }
    }
    // A click during the initial Open ACK must not be lost when that older
    // snapshot arrives. Apply the most recent desired navigation afterward.
    if (state.desiredNode && !state.pending) {
      const desired = state.desiredNode;
      state.desiredNode = '';
      queueMicrotask(() => chooseNode(desired));
    }
    render();
  }
  async function poll() {
    if (state.busy) return;
    state.busy = true;
    try {
      const ctrl = new AbortController();
      const timeout = setTimeout(() => ctrl.abort(), 3500);
      let response;
      try {response = await fetch('api/canvas/state', {cache:'no-store', signal:ctrl.signal});}
      finally {clearTimeout(timeout);}
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json();
      state.offline = false;
      ingest(data);
      if (state.pending && Date.now() - state.pending.started > 9500) {
        state.pending = null;
        setStatus('Chưa nhận được xác nhận từ backend. Nhấn Làm mới để thử lại.');
        renderButtons();
        if (state.desiredNode) {
          const desired = state.desiredNode;
          state.desiredNode = '';
          queueMicrotask(() => chooseNode(desired));
        }
      }
      if (!state.bootstrapped && !state.pending) {state.bootstrapped = true; send('open');}
      const activity = currentActivity();
      if (!state.pending && activity?.status === 'running' && Date.now() - state.lastExercisePoll > 1600) {
        state.lastExercisePoll = Date.now();
        send('exercise_status', {activity_id:activity.activity_id, nonce:activity.nonce});
      }
    } catch (_) {
      state.offline = true;
      setStatus('Mất kết nối ERIS. Mở ứng dụng và thử lại.');
    } finally {state.busy = false;}
  }
  function renderButtons() {
    byId('refresh').disabled = !!state.pending;
    document.querySelectorAll('[data-action]').forEach(node => {node.disabled = !!state.pending || node.dataset.disabled === 'true';});
  }
  function chooseNode(id) {
    if (!nodeById(id)) return;
    state.selected = id;
    state.mode = 'detail';
    if (state.pending) {
      state.desiredNode = id;
      render();
      return;
    }
    state.desiredNode = '';
    render();
    const focus = state.snapshot?.focus?.node_id;
    if (id !== focus) send('navigate', {node_id:id});
    else if (!state.details.has(id)) send('open', {node_id:id});
  }
  function renderMap() {
    const map = byId('map');
    map.replaceChildren();
    const nodes = state.snapshot?.nodes || [];
    byId('nodeCount').textContent = nodes.length ? `${nodes.length} kiến thức` : '—';
    if (!nodes.length) {map.append(el('div','placeholder','Chưa có bản đồ. Nhấn Làm mới để tải lại.')); return;}
    const levels = [...new Set(nodes.map(n => n.level || 0))].sort((a,b) => a-b);
    for (const level of levels) {
      const group = el('section','map-layer');
      group.append(el('span','level-head',`TẦNG ${level + 1}`));
      const row = el('div','level-row');
      for (const n of nodes.filter(n => (n.level || 0) === level)) {
        const selected = n.id === state.selected;
        const btn = el('button','node' + (selected ? ' selected' : '') +
          (state.playback?.node_id === n.id ? ' speaking-node' : ''));
        btn.type = 'button';btn.dataset.node = n.id;btn.setAttribute('aria-pressed',String(selected));
        btn.append(el('span','node-top',n.title));
        const foot = el('div','node-foot');
        foot.append(el('span','node-state '+(labels[n.state] ? n.state:'available'),labels[n.state] || 'Có thể học'));
        if (n.due) foot.append(el('span','node-hint','Đến hạn ôn'));
        else if (state.snapshot.focus?.suggested_node_id === n.id) foot.append(el('span','node-hint','Eris gợi ý ↗'));
        else if (n.result_count) foot.append(el('span','node-count',`${n.result_count} kết quả`));
        btn.append(foot);btn.addEventListener('click',() => chooseNode(n.id));row.append(btn);
      }
      group.append(row);map.append(group);
    }
    requestAnimationFrame(drawConnections);
  }
  function drawConnections() {
    const svg = byId('links'), map = byId('map'), viewport = byId('mapViewport');
    svg.replaceChildren();
    if (!state.snapshot) return;
    // Overlay is positioned in the same scroll content coordinates as the rows.
    const view = viewport.getBoundingClientRect();
    const rects = new Map([...map.querySelectorAll('[data-node]')].map(button => [button.dataset.node,button.getBoundingClientRect()]));
    const width = Math.max(map.scrollWidth + 40, viewport.clientWidth);
    const height = Math.max(map.scrollHeight + 50,viewport.clientHeight);
    svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
    svg.style.width = width + 'px'; svg.style.height = height + 'px';
    const position = (rect, bottom) => ({x:rect.left - view.left + viewport.scrollLeft + rect.width/2,
      y:(bottom ? rect.bottom : rect.top) - view.top + viewport.scrollTop});
    const ns = 'http://www.w3.org/2000/svg';
    for (const n of state.snapshot.nodes) {
      const dest = rects.get(n.id);if (!dest) continue;
      for (const id of n.prerequisites || []) {
        const source = rects.get(id);if (!source) continue;
        const a = position(source,true),b = position(dest,false);
        const line = document.createElementNS(ns,'path');
        const mid = (a.y + b.y) / 2;
        line.setAttribute('d',`M ${a.x} ${a.y} C ${a.x} ${mid} ${b.x} ${mid} ${b.x} ${b.y}`);
        line.setAttribute('fill','none');line.setAttribute('stroke','#d8afca');line.setAttribute('stroke-width','1.7');
        svg.append(line);
      }
    }
  }
  function addText(parent, tag, cls, text) {const element=el(tag,cls,text);parent.append(element);return element;}
  function actionButton(parent, label, action, disabled=false, primary=false) {
    const button = el('button','button'+(primary?'':' secondary'),label);
    button.type = 'button';button.dataset.action = action;button.dataset.disabled = String(disabled);
    button.disabled = disabled || !!state.pending;
    parent.append(button);return button;
  }
  function renderActivity(container, detail) {
    addText(container,'h4','section-title','Luyện tập');
    const choices = el('div','exercise-choices');container.append(choices);
    for (const exercise of detail.exercises || []) {
      const button = actionButton(choices,exercise.type === 'java'?'⌘ Viết Java':'◉ Trắc nghiệm','exercise');
      button.addEventListener('click',()=>send('exercise',{node_id:state.selected,exercise_id:exercise.id}));
    }
    const activity = currentActivity();
    if (!activity) {addText(container,'p','summary','Chọn dạng bài để bắt đầu. Kết quả được lưu sau khi chấm.');return;}
    const card = el('section','exercise-card');container.append(card);
    if (activity.unavailable_notice) addText(card,'p','warning','Java chưa khả dụng; đã chuyển sang trắc nghiệm. '+activity.unavailable_notice);
    addText(card,'p','',activity.prompt || '');
    const running = activity.status === 'running';
    let answer = '';
    if (activity.type === 'java') {
      const editor = el('textarea','code-editor');editor.id = 'codeEditor';
      editor.setAttribute('aria-label','Soạn mã Java');editor.spellcheck = false;
      editor.value = state.drafts.get(activity.activity_id) ?? activity.code ?? '';
      editor.disabled = running || !!state.pending;
      editor.addEventListener('input',()=>state.drafts.set(activity.activity_id,editor.value));
      editor.addEventListener('keydown',event=>{
        if (event.key === 'Tab') {
          event.preventDefault();const start=editor.selectionStart,end=editor.selectionEnd;
          editor.setRangeText('    ',start,end,'end');state.drafts.set(activity.activity_id,editor.value);
        }
      });
      card.append(editor);
      const row = el('div','exercise-actions');card.append(row);
      const submit = actionButton(row,running?'Đang chạy trong Docker...':'▶ Chạy Java','submit',running,true);
      submit.addEventListener('click',()=>{
        const code = editor.value;
        if (!code.trim() || new TextEncoder().encode(code).length > 12000) {
          setStatus('Nhập code Java tối đa 12 KB.');return;
        }
        send('submit',{activity_id:activity.activity_id,nonce:activity.nonce,code});
      });
    } else {
      const list = el('div','choice-list');card.append(list);
      const selected = state.answers.get(activity.activity_id) || '';
      for (const opt of activity.options || []) {
        const button = el('button','choice'+(selected === opt.id?' selected':''),`${String(opt.id).toUpperCase()}. ${opt.text}`);
        button.type = 'button';button.setAttribute('aria-pressed',String(selected === opt.id));
        button.disabled = running || !!state.pending;
        button.addEventListener('click',()=>{state.answers.set(activity.activity_id,opt.id);renderDetail();});
        list.append(button);
      }
      const row = el('div','exercise-actions');card.append(row);
      const submit = actionButton(row,'Nộp đáp án','submit',running || !selected,true);
      submit.addEventListener('click',()=>send('submit',{activity_id:activity.activity_id,nonce:activity.nonce,answer:state.answers.get(activity.activity_id)||''}));
    }
    const actions = el('div','exercise-actions');card.append(actions);
    actionButton(actions,'Gợi ý','hint',running).addEventListener('click',()=>send('hint',{activity_id:activity.activity_id,nonce:activity.nonce}));
    actionButton(actions,'Xem lời giải','reveal',running).addEventListener('click',()=>send('reveal',{activity_id:activity.activity_id,nonce:activity.nonce}));
    addText(card,'p','summary',activity.assistance === 'hinted'?'Đã dùng gợi ý · Kết quả ghi kèm trợ giúp':
      activity.assistance === 'revealed'?'Đã xem lời giải · Kết quả ghi kèm trợ giúp':'Đang tự làm');
    if (activity.help) addText(card,'div','help',activity.help);
    if (activity.status === 'completed') {
      addText(card,'p','result '+(activity.result === 'correct'?'correct':'incorrect'),
        activity.result === 'correct'?'✓ Đúng · Đã lưu kết quả':activity.result === 'partial'?'Đúng một phần · Đã lưu kết quả':'Chưa đúng · Đã lưu kết quả');
      if (activity.tests?.length) {
        const tests=el('ul','tests');card.append(tests);
        for (const test of activity.tests) addText(tests,'li','',`${test.passed?'✓':'×'} ${test.description}`);
      }
      if (activity.diagnostic) addText(card,'p','help',activity.diagnostic);
    }
    if (activity.status === 'unavailable') addText(card,'p','warning','Không thể chạy Java. '+(activity.guidance || 'Kiểm tra Docker Desktop và môi trường JDK.'));
  }
  function renderDetail() {
    const container = byId('detail');
    // Preserve unsent Java drafts and cursor while new playback packets arrive.
    const oldEditor = byId('codeEditor');
    const focused = document.activeElement === oldEditor;
    const selection = focused ? [oldEditor.selectionStart,oldEditor.selectionEnd] : null;
    if (oldEditor && currentActivity()) state.drafts.set(currentActivity().activity_id,oldEditor.value);
    container.replaceChildren();
    const node = nodeById(state.selected);
    byId('focusState').textContent = node ? labels[node.state] || 'Có thể học' : '—';
    if (!node) {addText(container,'div','placeholder','Chọn một nút trên bản đồ để đọc nội dung và luyện tập.');return;}
    const head = el('div','detail-head');container.append(head);
    addText(head,'span','eyebrow','KIẾN THỨC / '+(node.level + 1));
    addText(head,'h3','',node.title);
    if (node.prerequisite_warnings?.length) {
      addText(head,'div','warning','Nên ôn trước: '+node.prerequisite_warnings.map(id=>nodeById(id)?.title||id).join(', ')+'. Bạn vẫn có thể học phần này.');
    }
    const detail = state.details.get(node.id);
    if (!detail) {addText(container,'div','placeholder','Đang tải nội dung từ Eris...');return;}
    addText(head,'p','summary',detail.summary || '');
    for (const block of detail.blocks || []) {
      const active = state.playback?.node_id === node.id && state.playback?.block_id === block.id &&
        state.playback.event_type === 'audio_start';
      const card = el('section','block'+(active?' active':''));
      card.dataset.block = block.id;
      addText(card,'h4','block-title',block.title);
      if (block.kind === 'java') {
        const wrapper=el('div','code-wrap'),pre=el('pre','language-java'),code=el('code','language-java',block.text);
        pre.append(code);wrapper.append(pre);card.append(wrapper);
        if (globalThis.Prism?.highlightElement) globalThis.Prism.highlightElement(code);
      } else addText(card,'p','block-text',block.text);
      container.append(card);
    }
    for (const result of state.snapshot?.late_results || []) addText(container,'p','late','Kết quả đã có · '+(result.summary || ''));
    renderActivity(container,detail);
    renderButtons();
    if (focused && byId('codeEditor')) {
      const editor = byId('codeEditor');editor.focus();editor.setSelectionRange(...selection);
    }
  }
  function renderSpeaking() {
    const playback=state.playback, node=nodeById(playback?.node_id);
    const visible = !!node && !!playback && playback.node_id !== state.selected &&
      ['queued','audio_start'].includes(playback.event_type);
    byId('speaking').hidden = !visible;
    if (visible) byId('speakingText').textContent =
      (playback.event_type==='audio_start'?'Eris đang nói về ':'Eris chuẩn bị nói về ')+node.title;
    byId('speakingJump').onclick = () => chooseNode(playback.node_id);
  }
  function render() {
    const snap=state.snapshot;
    byId('pathTitle').textContent = snap?.title || 'Dependency Injection · Java';
    byId('pin').textContent = snap?.focus?.pinned ? 'Đã ghim' : 'Theo Eris';
    byId('assessment').textContent = 'Theo dõi từ bài làm thực tế';
    const mobile=state.mode==='detail';
    byId('workspace').classList.toggle('detail-mode', mobile);
    byId('mapTab').classList.toggle('active',!mobile);
    byId('detailTab').classList.toggle('active',mobile);
    byId('mapTab').setAttribute('aria-selected',String(!mobile));
    byId('detailTab').setAttribute('aria-selected',String(mobile));
    renderMap();renderDetail();renderSpeaking();renderButtons();
  }
  byId('refresh').addEventListener('click',()=>send('open'));
  byId('mapTab').addEventListener('click',()=>{state.mode='map';render();});
  byId('detailTab').addEventListener('click',()=>{state.mode='detail';render();});
  window.addEventListener('resize',()=>requestAnimationFrame(drawConnections));
  byId('mapViewport').addEventListener('scroll',()=>requestAnimationFrame(drawConnections),{passive:true});
  render();
  poll();
  setInterval(poll,850);
})();
