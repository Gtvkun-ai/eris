import json,sys,socket,hashlib
from pathlib import Path
sys.path.insert(0,str(Path('src').resolve()))
def no_network(*args,**kwargs): raise AssertionError('offline')
socket.socket.connect=no_network
socket.create_connection=no_network
from domain import Decision
from runtime.conversation.public_output_artifact import prepare_public_output
from runtime.conversation.contracts import NextConversationMove
from runtime.conversation.kernel import KernelTurn
from runtime.stage_contracts import StageFrameBuilder,_contains_japanese_script
from runtime.intention_authority import IntentionObserver
import runtime.runtime_settings_store as settings
settings.runtime_text=lambda *a,**k:'ja'
turn=KernelTurn(session_id='probe',generation=1,run_id='probe:control',move=NextConversationMove(intent='talk',say='probe',move_id='probe:control'),note='',delivery_id='delivery:control')
rows=[]
for name,text in [('short','Chào cậu.'),('double_space','Chào  cậu.'),('newline','Chào\ncậu.'),('len360','Chào '+ 'a'*355),('len361','Chào '+ 'a'*356)]:
 for nested in (False,True):
  payload={'text':text,'speech_text':'こんにちは。','speech_language':'ja'}
  if nested: payload['utterance']={'display':{'text':text,'language':'vi'},'speech':{'text':'こんにちは。','language':'ja'}}
  decision=Decision(text=text,speech_text='こんにちは。',animation='stand',should_speak=True)
  frame=StageFrameBuilder(language_hint='ja').build(decision,payload=dict(payload),channel='autonomous')
  observation=IntentionObserver().validate(text)
  try:
   prepare_public_output(event_id='control',turn=turn,channel='autonomous',decision=decision,payload=payload)
   result='pass'
  except Exception as e: result=str(e)
  rows.append({'case':name,'nested_utterance':nested,'chars':len(text),'observer_changes':observation.text!=text,'observer_rewritten':observation.rewritten,'direct_stage_ja':_contains_japanese_script(frame.tts_text),'prepare_result':result})
base=Path('.agents/tasks/eris-20261015-1647-audit/speech')
(base/'control-results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(rows,ensure_ascii=False,indent=2))
paths=['runtime/conversation/runtime_writer.py','runtime/conversation/public_output_artifact.py','runtime/conversation/delivery_adapter.py','runtime/stage_contracts.py','runtime/utterance_spec.py','runtime/speech_contract.py','runtime/speech_localizer.py','runtime/speech_delivery_planner.py','runtime/intention_authority.py']
hashes=[]
for p in paths:
 a=hashlib.sha256((Path('src')/p).read_bytes()).hexdigest()
 b=hashlib.sha256((Path('C:/Users/Gtvkun/Documents/eris/src')/p).read_bytes()).hexdigest()
 hashes.append({'path':'src/'+p,'dev_sha256':a,'portable_sha256':b,'match':a==b})
(base/'source-hashes.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
print('source hashes:',len(hashes),'matched:',sum(x['match'] for x in hashes))
