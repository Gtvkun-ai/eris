'use strict';
// First-party same-origin Eris portal. No external CDN, no client-side fake success.
(() => {
  const el = id => document.getElementById(id);
  const set = (id, value) => { const node = el(id); if (node) node.textContent = String(value); };
  const ACTIONS = ['startLive','startSimulator','stopLive','emergencyStop'];
  let lastRevision = 0, pendingId = '', previousAction = '', started = false;
  let mostRecent = null;
  const number = n => Number.isFinite(Number(n)) ? Number(n).toLocaleString('vi-VN') : '0';
  const stamp = x => Number.isFinite(Number(x)) ? new Date(Number(x) * 1000).toLocaleTimeString('vi-VN', {hour:'2-digit', minute:'2-digit', second:'2-digit'}) : '';
  const duration = seconds => { const x = Math.max(0,Math.round(Number(seconds)||0)); return `${String(Math.floor(x/3600)).padStart(2,'0')}:${String(Math.floor(x%3600/60)).padStart(2,'0')}:${String(x%60).padStart(2,'0')}`; };
  const notice = (message, type='') => { set('controlMessage', message); el('controlMessage').className = 'notice' + (type ? ' ' + type : ''); };
  function toggleButtons(state) {
    const enabled = state?.enabled === true, active = state?.active === true;
    const ready = enabled && state?.tts_ready === true && state?.root_available === true;
    el('startLive').disabled = !ready || active || !state.tiktok_sdk_installed || !!pendingId;
    el('startSimulator').disabled = !ready || active || !!pendingId;
    el('stopLive').disabled = !active || !!pendingId;
    el('emergencyStop').disabled = !active;
    document.querySelectorAll('.scenario').forEach(x => { x.disabled = !active || state.mode !== 'simulator' || !!pendingId; });
    el('customComment').disabled = !active || state.mode !== 'simulator';
    el('customForm').querySelector('button').disabled = !active || state.mode !== 'simulator' || !!pendingId;
  }
  async function send(action, payload = {}) {
    if (pendingId && action !== 'emergency_stop') return;
    const requestId = `${Date.now()}-${Math.floor(Math.random()*1e9)}`;
    pendingId = requestId;
    toggleButtons(mostRecent || {});
    notice('Đã gửi lệnh, đang chờ Cortex xác nhận…');
    try {
      const res = await fetch('api/live/control', { method:'POST', cache:'no-store', credentials:'same-origin',
        headers:{'Content-Type':'application/json'}, body:JSON.stringify({action, request_id:requestId,...payload}) });
      if (!res.ok) throw Error('Portal không nhận lệnh (' + res.status + ')');
      // 202 is queue acknowledgment, NOT proof of start/stop.
      setTimeout(() => { if(pendingId === requestId) {pendingId = ''; notice('Chưa nhận ACK từ Cortex. Kiểm tra app Eris có đang chạy.', 'error'); toggleButtons(mostRecent || {});}}, 8000);
    } catch(err) { pendingId = ''; notice(String(err?.message || err), 'error'); toggleButtons(mostRecent || {}); }
  }
  el('validateLive').addEventListener('click', () => send('validate'));
  el('copyOverlayUrl').addEventListener('click', async () => {
    const url=new URL('live-overlay.html', location.href).href;
    try {await navigator.clipboard.writeText(url);notice('Đã sao chép URL phụ đề. Dán vào OBS Browser Source (máy này), không chia sẻ URL có token.','success');}
    catch (_) {notice('Clipboard bị chặn. Mở trang phụ đề và sao chép URL trên thanh địa chỉ.','error');}
  });
  el('startLive').addEventListener('click', () => send('start_live',{room:el('tiktokRoom').value.trim()}));
  el('startSimulator').addEventListener('click', () => send('start_simulator'));
  el('stopLive').addEventListener('click', () => send('stop'));
  el('emergencyStop').addEventListener('click', () => {
    if (!window.confirm('Dừng phiên live của Eris ngay? Phòng TikTok ngoài ứng dụng có thể vẫn phát qua OBS.')) return;
    send('emergency_stop');
  });
  document.querySelectorAll('.scenario').forEach(btn => btn.addEventListener('click', () => send('simulate',{scenario:btn.dataset.scenario})));
  el('customForm').addEventListener('submit', e => {e.preventDefault(); const comment=el('customComment').value.trim();if(comment)send('simulate',{scenario:'custom', comment});});
  function renderEvents(events) {
    const container=el('eventFeed'); container.replaceChildren();
    set('eventCount', `${events.length} sự kiện gần nhất`);
    if (!events.length) {const p=document.createElement('p');p.className='empty';p.textContent='Chưa có sự kiện từ phòng live.';container.append(p);return;}
    const icons={comment:'◌', gift:'✧',like:'♡', follow:'+',room_end:'■'};
    for (const e of [...events].reverse()) {
      const row=document.createElement('div'); row.className='event';
      const ico=document.createElement('span');ico.className='symbol';ico.textContent=icons[e.kind] || '•';
      const content=document.createElement('div');
      const who=document.createElement('div');who.className='who';who.textContent=String(e.viewer||'Khán giả').slice(0,50);
      const time=document.createElement('span');time.className='time';time.textContent=stamp(e.time);who.append(time);
      const body=document.createElement('div');body.className='body';
      body.textContent=e.kind==='comment' ? String(e.text||'').slice(0,160)
        : e.kind==='gift' ? `Gift: ${String(e.gift||'').slice(0,60)} × ${number(e.count)}` : e.kind==='like' ? `Like × ${number(e.count)}` : 'Follow';
      content.append(who,body);row.append(ico,content);container.append(row);
    }
  }
  function renderLearning(state){
    set('learningStatus',state.learning_enabled?'Opt-in · On':'Off');
    const list=el('learningSessions');list.replaceChildren();
    const sessions=Array.isArray(state.learning_summary)?state.learning_summary:[];
    set('learningDescription',state.learning_enabled
      ? 'Chỉ lưu thống kê tổng hợp sau buổi live. Không lưu nội dung comment, tên người xem, ký ức cá nhân hoặc tỷ lệ quà để quyết định persona.'
      : 'Chưa lưu bền vững. Nếu muốn giữ kinh nghiệm ở mức thống kê, bật ERIS_LIVE_LEARNING_ENABLED=1 và khởi động lại Eris.');
    if(!sessions.length) {const p=document.createElement('p');p.className='empty';p.textContent='Chưa có buổi live đã chốt hoặc chưa bật lưu.';list.append(p);return;}
    for (const s of [...sessions].reverse()){
      const row=document.createElement('div');
      row.textContent=`${s.date || 'N/A'} · ${duration(s.duration_s)} · ${number(s.batches)} batch · ${number(s.root_attempts)} lượt Root · ${number(s.no_reply)} lần im lặng`;
      list.append(row);
    }
  }
  const check=(id,yes) => { const target=el(id);target.className='check '+(yes?'ok':'fail');target.textContent=yes?'✓':'○'; };
  function render(state){
    mostRecent=state;
    set('hostConnection','Cortex đang phản hồi');el('hostDot').classList.add('connected');
    const mode=state.active ? (state.mode==='simulator'?'Simulator':state.mode==='tiktok'?'TikTok Listener':'Đang khởi động') : 'Offline';
    set('modeChip',mode);
    set('connectionChip',state.connection || 'disconnected');
    set('stageUptime',duration(state.uptime_s));
    set('stageLabel',state.active ? (state.mode==='tiktok' ? (state.connection==='connected'?'Đã nối phòng TikTok':'Đang thử kết nối TikTok') : 'Eris đang ở chế độ Simulator') : 'Chưa bắt đầu phiên live');
    const error=state.blocked_reason || (state.enabled===false?'ERIS_LIVE_ENABLED=1 chưa bật':'');
    set('stageDescription',error || (state.active?'Root quyết định phản hồi hoặc im lặng; không có showmanship state machine.':'Bật Simulator để thử đường sự kiện mà không cần TikTok.'));
    set('rootBadge',state.root_available?'Root · Ready':'Root · Unavailable');
    set('voiceBadge',state.tts_ready?'Voice · Vietnamese':'Voice · Setup required');
    set('privacyBadge',state.privacy==='public_live_isolated'?'Private Memory · Isolated':'Privacy · Unknown');
    set('metricAccepted',number(state.accepted));set('metricBatches',number(state.batches));set('metricRoot',number(state.root_attempts));
    set('metricDelivery',number(state.audio_delivered));set('metricSilence',number(state.no_reply));
    set('metricDropped',number((state.expired||0)+(state.overflow||0)+(state.duplicate||0)+(state.stale||0)));
    set('queueStatus',number(state.queue_depth));set('providerStatus',state.connection || 'disconnected');
    set('ttsStatus',(state.tts_language || 'unknown')+(state.tts_ready?' · OK':' · Blocked'));
    set('privacyStatus',state.privacy || 'unknown');
    check('checkKernel',state.root_available);check('checkLanguage',state.tts_ready);check('checkSDK',state.tiktok_sdk_installed);check('checkSession',state.active);
    renderEvents(Array.isArray(state.events)?state.events:[]);renderLearning(state);
    if(state.validation) set('validationResult', `Offline: ${state.validation.passed}/${state.validation.total} checks · ${state.validation.scope}`);
    const ack=state.last_action;
    if (ack && ack.request_id && ack.request_id!==previousAction && ack.action!=='status') {
      previousAction=ack.request_id;
      if(ack.request_id===pendingId) pendingId='';
      notice(ack.ok ? `Cortex xác nhận: ${ack.status || ack.action}${ack.accepted_events!==undefined ? ' · '+ack.accepted_events+' events':''}`
                    : `Lệnh thất bại: ${ack.reason || 'unknown'}`,ack.ok?'success':'error');
    }
    toggleButtons(state);
  }
  async function poll(){
    try{
      const res=await fetch('api/live/state',{cache:'no-store',credentials:'same-origin'});
      if(!res.ok)throw Error(`HTTP ${res.status}`);
      const state=await res.json();
      if(!state || typeof state!=='object')throw Error('invalid state');
      if(state.status_version!==1)throw Error('waiting for Cortex');
      if(Number(state.server_time || 0)<lastRevision) return;
      lastRevision=Number(state.server_time || 0);
      if(Date.now()/1000-lastRevision>8)throw Error('Cortex status is stale');
      render(state);
    }catch(err){
      el('hostDot').classList.remove('connected');set('hostConnection','Chưa nhận Cortex');
      set('connectionChip','Mất kết nối');
      if(!started){notice('Mở Eris Cortex và bật ERIS_LIVE_ENABLED=1 để sử dụng panel.','error');}
    }
    started=true;
  }
  poll();window.setInterval(poll,1100);
})();
