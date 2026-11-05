"""Five live calls through current Root; sandbox state, no delivery or real memory."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
sys.path.insert(0,str(REPO/'src'))
os.environ['ERIS_ROOT_SESSION_BOOTSTRAP']='0'
os.environ['ERIS_ROOT_INTERACTION_CHOICES']='0'
from runtime.ai_orchestrated.contracts import RuntimeMindState
from runtime.conversation.agent import RuntimeModelRootAgent
from runtime.conversation.context_assembler import ConversationContextAssembler
from runtime.conversation.contracts import ConversationEvent
from runtime.conversation_handoff import ConversationHandoffRuntime
from runtime.source_grounding import SourceGroundingEngine
from llm.client import _attach_deepseek_json_schema

spec=importlib.util.spec_from_file_location('eq_shared',REPO/'.agents/tasks/eris-eq-verification/probe.py')
shared=importlib.util.module_from_spec(spec);spec.loader.exec_module(shared)


class Router:
    executive_client=SimpleNamespace(model_name='deepseek-flash',base_url='http://127.0.0.1:5103/v1')
    def __init__(self,case):self.case=case;self.result=None;self.calls=0
    def invoke_structured_worker(self,_client,**kw):
        self.calls+=1
        if self.calls>1:raise RuntimeError('Single-call smoke budget; no follow-up inference')
        assert 'PHÁN ĐOÁN XÃ HỘI CỦA ERIS' in kw['system']
        assert 'social_situation_evidence' in kw['payload']['runtime_context']
        requested={'type':'json_schema','json_schema':{'name':kw['name'],'schema':kw['schema'],'strict':True}}
        messages=_attach_deepseek_json_schema([
            {'role':'system','content':kw['system']},
            {'role':'user','content':json.dumps(kw['payload'],ensure_ascii=False,default=str)},
        ],requested)
        assert messages[0]['content'].count('[OUTPUT_JSON_SCHEMA_REQUIREMENT]')==1
        wire={'model':'deepseek-flash','messages':messages,'max_tokens':max(2048,kw.get('max_tokens',1200)),
              'reasoning_effort':kw.get('reasoning_effort','medium'),'thinking':{'type':'enabled'},
              'temperature':kw.get('temperature',.3),'response_format':{'type':'json_object'}}
        self.result=shared.request({'case':self.case,'condition':'current_source','repeat':1,'payload':wire},
                                   'http://127.0.0.1:5103/v1/chat/completions')
        self.result['social_evidence']=deepcopy(kw['payload']['runtime_context']['social_situation_evidence'])
        self.result['schema_suffix_present']=True
        if self.result.get('http_status')!=200:raise RuntimeError('Service failure')
        parsed=self.result.get('parsed')
        if not isinstance(parsed,dict):
            try:parsed=json.loads(self.result.get('content','').strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip())
            except ValueError:parsed=None
        return parsed


def main():
    path=HERE/'results.jsonl'
    if path.exists():raise SystemExit('Already attempted; no automatic repeat')
    keys=json.loads(Path('C:/Users/Gtvkun/Documents/eris/config/secrets.json').read_text('utf-8-sig'))['api_keys']
    os.environ['ERIS_EQ_PROBE_API_KEY']=keys.get('ERIS_DS_EXECUTIVE_API_KEY') or keys['ERIS_DS2API_API_KEY']
    cases=[
        ('vent',[], 'tức điên luôn. nãy giao cho kiro làm code, mà nó làm loay hoay si đa, bực bội vl'),
        ('repair',[{'role':'user','content':'Kiro làm tôi bực quá.'},{'role':'assistant','content':'Nó sai ở module nào? Anh gửi brief và log để tôi xem nhé.','delivery_status':'delivered'}],
         'Tôi chỉ đang tâm sự mà, sao bạn cứ hỏi kỹ thuật vậy?'),
        ('debug',[], 'Kiro sửa code bị crash lúc đăng nhập. Giờ giúp tôi tìm lỗi nhé; cần tôi gửi thông tin gì?'),
        ('discouraged',[], 'Tối nào cũng tập đàn mà nghe vẫn dở. Hôm nay hết muốn đụng vào nó luôn.'),
        ('banter',[{'role':'assistant','content':'Tôi đang trông nhà cho đống tab của anh đây.','delivery_status':'delivered'}],
         'Nhớ tưới nước cho chúng, tab nào héo thì đem phơi nắng :))'),
    ]
    (HERE/'plan.json').write_text(json.dumps([{'case':c,'history':h,'user_text':t} for c,h,t in cases],ensure_ascii=False,indent=2),'utf-8')
    metadata={'source_commit':'745c1c7b','portable_synced':False,'state':'fresh sandbox; no seeded learned episodes',
              'pipeline':'current assembler/handoff/grounding/RootAgent; isolated live HTTP adapter',
              'source_hashes':{str(f):hashlib.sha256((REPO/f).read_bytes()).hexdigest() for f in [
                Path('src/runtime/conversation/agent.py'),Path('src/runtime/conversation/root_prompt_contract.py'),
                Path('src/runtime/conversation/social_situation.py'),Path('src/runtime/source_grounding.py')]}}
    (HERE/'environment.json').write_text(json.dumps(metadata,indent=2),'utf-8')
    with path.open('x',encoding='utf-8') as out:
        for index,(case,history,text) in enumerate(cases,1):
            handoff=ConversationHandoffRuntime()
            previous=next((h['content'] for h in reversed(history) if h['role']=='assistant'),'')
            handoff.observe_user_turn(text,turn_ref=f'user:{index}',turn_index=index*2,
                                      previous_assistant_text=previous,previous_assistant_turn_ref='assistant:previous' if previous else '')
            state=RuntimeMindState()
            host=SimpleNamespace(ai_state_reducer=SimpleNamespace(snapshot=lambda:state),
                                 conversation_handoff_runtime=handoff,conversation_id='sandbox',memory_kernel=None,logger=None)
            event=ConversationEvent.user_turn(session_id='sandbox',text=text)
            engine=SourceGroundingEngine();report=engine.analyze(text)
            context=ConversationContextAssembler(host).assemble(event=event,user_text=text,recent_history=history,source_report=report)
            context['grounding_context']=engine.render_prompt_context(report)
            context['user_addressing_context']='User is male; address as anh and refer to self as tôi.'
            router=Router(case)
            decision=RuntimeModelRootAgent(router).decide(event=event,recent_history=history,note='',runtime_context=context)
            result=router.result or {'case':case,'error_type':'NoInference'}
            result['root_decision']=decision.to_dict() if callable(getattr(decision,'to_dict',None)) else {'type':type(decision).__name__}
            result['root_worker_calls']=router.calls
            out.write(json.dumps(result,ensure_ascii=False,default=str)+'\n');out.flush()
            print(case,result.get('http_status',result.get('error_type')),result.get('elapsed_seconds'),flush=True)
            if result.get('http_status')!=200:break


if __name__=='__main__':main()
