const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const base=path.resolve(__dirname,'..');
const source=p=>fs.readFileSync(path.join(base,p),'utf8');
const cs=fs.readFileSync(path.resolve(base,'..','UdpListener.RichChatPortal.cs'),'utf8');
const csLive=fs.readFileSync(path.resolve(base,'..','UdpListener.LiveStudioPortal.cs'),'utf8');

test('Live Studio is accessible from existing Eris chat and ships as embedded resource',()=>{
 assert.match(source('index.html'),/href="live\.html"/);
 for (const f of ['live.html','live.css','live.js','live-overlay.html','live-overlay.css','live-overlay.js']) {
   assert.ok(fs.existsSync(path.join(base,f)));
   assert.ok(cs.includes('"'+f+'"'),f+' missing resource');
 }
});
test('portal protects control endpoint with token and same-origin and keeps send on main thread',()=>{
 assert.match(cs,/relative == "api\/live\/control"/);
 assert.match(cs,/expectedOrigin = "Origin: http:\/\/" \+ expectedHost/);
 assert.match(cs,/TryQueueLiveStudioCommand\(control.RootElement\)/);
 assert.match(cs,/TickLiveStudioPortal\(\)/);
 assert.match(csLive,/ConcurrentQueue<string>/);
 assert.match(csLive,/_chatSend\.PutPacket/);
});
test('frontend waits for Cortex ACK and never injects viewer text through innerHTML',()=>{
 const script=source('live.js');
 assert.match(script,/pendingId/);
 assert.match(script,/last_action/);
 assert.match(script,/res\.ok/);
 assert.match(script,/textContent/);
 assert.doesNotMatch(script,/\.innerHTML\s*=/);
 assert.match(script,/status_version/);
 assert.match(source('live.html'),/Prompt injection/i);
});
test('OBS subtitle overlay displays only audio_speaking text after receipt',()=>{
 const script=source('live-overlay.js');
 assert.match(script,/state\.audio_speaking/);
 assert.match(script,/state\.caption/);
 assert.match(script,/textContent/);
 assert.doesNotMatch(script,/\.innerHTML\s*=/);
 assert.match(source('live-overlay.css'),/background:transparent/);
});
