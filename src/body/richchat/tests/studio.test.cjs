'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const base=path.resolve(__dirname,'..');
const U=require('../studio.js');
const html=fs.readFileSync(path.join(base,'index.html'),'utf8');
const portal=fs.readFileSync(path.join(base,'..','UdpListener.RichChatPortal.cs'),'utf8');
const script=fs.readFileSync(path.join(base,'chat.js'),'utf8');

test('fingerprint ổn định và không lưu toàn bộ nội dung làm key',()=>{
  const message={role:'user',date:'2026-11-06',time:'21:00',text:'Riêng tư'};
  const a=U.fingerprint(message);
  assert.equal(a,U.fingerprint({...message}));
  assert.notEqual(a,U.fingerprint({...message,text:'Thay đổi'}));
  assert.ok(!a.includes('Riêng tư'));
});
test('đính kèm text không làm vỡ fence Markdown',()=>{
  const block=U.fileBlock('readme.md','hello\n~~~~\nworld');
  assert.match(block,/~~~~~text\nhello\n~~~~\nworld\n~~~~~/);
  assert.ok(!block.includes('```html'));
});
test('giới hạn payload tính theo UTF-8 JSON, không phải số ký tự đơn thuần',()=>{
  assert.equal(U.sizeOkay('a'),true);
  assert.equal(U.sizeOkay(''),false);
  assert.equal(U.sizeOkay('a'.repeat(6001)),false);
  assert.equal(U.sizeOkay('\\'.repeat(6000)),false);
  assert.equal(U.sizeOkay('ừ'.repeat(2000)),true);
});
test('Studio assets và các điểm móc giao diện được đóng gói cùng Godot',()=>{
  for(const f of ['studio.css','studio.js']){
    assert.match(html,new RegExp(f.replace('.','\\.')));
    assert.ok(portal.includes('"'+f+'"'));
  }
  for(const id of ['messages','input','sendForm','search','dates','inspector','avatarRoom','notifyFinished','attachmentTray','fileInput','micBtn','topicList']){
    assert.match(html,new RegExp('id="'+id+'"'));
  }
});
test('SSE sử dụng cùng snapshot có nguồn gốc runtime; polling fallback vẫn tồn tại',()=>{
  assert.match(portal,/relative == "api\/events"/);
  assert.match(portal,/StreamRichChatEvents\(net\)/);
  assert.match(portal,/Volatile\.Read\(ref _richChatSnapshot\)/);
  assert.match(portal,/presence = new/);
  assert.match(script,/eris:stream-state/);
  assert.match(script,/if\(!document\.hidden&&!window\.ErisStudio\?\.isStreaming/);
});
test('keyed rendering tránh replaceChildren toàn bộ transcript khi polling',()=>{
  assert.match(script,/dataset\.renderKey/);
  assert.match(script,/root\.insertBefore\(node/);
  assert.doesNotMatch(script,/root\.replaceChildren\(frag\)/);
});
