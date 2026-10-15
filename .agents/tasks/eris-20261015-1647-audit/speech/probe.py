import json,sys,socket
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path('src').resolve()))
def no_network(*args, **kwargs):
    raise AssertionError('Offline probe attempted network')
socket.create_connection=no_network
socket.socket.connect=no_network
from domain import Decision
from runtime.conversation.runtime_writer import _prelocalize_v03_speech
from runtime.conversation.public_output_artifact import prepare_public_output
from runtime.conversation.contracts import NextConversationMove
from runtime.conversation.kernel import KernelTurn
from runtime.stage_contracts import StageFrameBuilder,_contains_japanese_script
from runtime.intention_authority import IntentionObserver
import runtime.runtime_settings_store as settings
settings.runtime_text=lambda *a, **k: 'ja'
class NoLocalizer:
    calls=0
    def localize(self,*args,**kwargs):
        self.calls+=1
        raise AssertionError('Already-Japanese source should skip localizer')
base=Path('.agents/tasks/eris-20261015-1647-audit/speech')
results=[]
for line in (8,20,33,39,43,47):
    response=json.loads((base/f'surface-{line}.json').read_text(encoding='utf-8'))
    payload=json.loads(response['choices'][0]['message']['content'])
    loc=NoLocalizer()
    localized=_prelocalize_v03_speech(payload,host=SimpleNamespace(character_speech_localizer=loc),language_hint='ja')
    obs=IntentionObserver().validate(localized['text'])
    decision=Decision(text=localized['text'],speech_text=localized['speech_text'],should_speak=True,animation='stand')
    turn=KernelTurn(session_id='probe',generation=1,run_id=f'probe:{line}',move=NextConversationMove(intent='talk',say='probe',move_id=f'probe:{line}'),note='',delivery_id=f'delivery:probe{line}')
    row={'raw_line':line,'display_chars':len(payload['text']),'speech_chars':len(payload['speech_text']),'localizer_calls':loc.calls,'prelocalize_contains_japanese':_contains_japanese_script(localized['speech_text']),'observer_chars':len(obs.text),'observer_changes_text':obs.text != localized['text'],'observer_rewritten':obs.rewritten,'channels':{}}
    for channel in ('chat','autonomous'):
        frame=StageFrameBuilder(language_hint='ja').build(decision,payload=dict(localized),channel=channel)
        try:
            prepared=prepare_public_output(event_id='probe',turn=turn,channel=channel,decision=decision,payload=dict(localized))
            result='pass'
        except Exception as exc:
            result=str(exc)
        row['channels'][channel]={'stage_display_chars':len(frame.display_text),'stage_speech_chars':len(frame.tts_text),'stage_speech_is_ja':_contains_japanese_script(frame.tts_text),'contract':frame.speech_contract,'prepare_result':result,'stage_speech_preview':frame.tts_text[:70]}
    results.append(row)
print(json.dumps(results,ensure_ascii=False,indent=2))
(base/'probe-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')

