"""At most five sequential live calls, no retries or actions executed."""
from copy import deepcopy
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
spec = importlib.util.spec_from_file_location('eq_shared', REPO / '.agents/tasks/eris-eq-verification/probe.py')
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--attempt',type=int)
    args=parser.parse_args()
    if args.attempt is not None and args.attempt<1:
        parser.error('attempt must be positive')
    run_dir=HERE if args.attempt is None else HERE / f'attempt-{args.attempt}'
    run_dir.mkdir(exist_ok=True)
    path = run_dir / 'results.jsonl'
    if path.exists():
        raise SystemExit('Run already attempted; refusing automatic repeat.')
    rows = [json.loads(l) for l in (shared.RAW / 'events_20261103T145411Z_pid5836.jsonl').read_text('utf-8').splitlines()]
    spans = json.loads((REPO / '.agents/tasks/eris-initiative-ablation/manifest.json').read_text('utf-8'))[0]['removed_spans']
    rules = [
        '- Answer-first nếu evidence đủ; nếu thiếu evidence thì chuyển sang uncertainty/probe, không claim như fact.\n',
        '- Không chuyển thiếu evidence thành suy diễn tâm lý hoặc văn mẫu fallback tĩnh.\n',
    ]
    tasks = []
    bases = {}
    for case, ident in [('vent','d88568e2807e48a1ac4f11bfdc0481ae'),('repair','93677379697e4e409966c1468de1aaa3')]:
        row=next(r for r in rows if r.get('event')=='request' and r.get('request_id')==ident)
        base=shared.restore(row['raw_request_ref'])
        system=base['messages'][0]['content']
        marker='\n\n[OUTPUT_JSON_SCHEMA_REQUIREMENT]\n'
        assert system.count(marker)==1
        suffix=system[system.index(marker):]
        for span in spans:
            assert system.count(span)==1
            system=system.replace(span,'')
        base['messages'][0]['content']=system
        bases[case]=base
        edited=deepcopy(base)
        env=json.loads(edited['messages'][-1]['content'])
        grounding=env['runtime_context']['grounding_context']
        for rule in rules:
            assert grounding.count(rule)==1
            grounding=grounding.replace(rule,'')
        env['runtime_context']['grounding_context']=grounding
        edited['messages'][-1]['content']=json.dumps(env,ensure_ascii=False)
        assert edited['messages'][:-1]==base['messages'][:-1]
        assert edited['messages'][0]['content'].endswith(suffix)
        for condition,payload in [('baseline',base),('remove_probe_rules',edited)]:
            tasks.append({'case':case,'condition':condition,'repeat':1,'payload':payload})
    control=shared.case_payload(bases['vent'],[], 'Kiro sửa code bị crash lúc đăng nhập. Giờ giúp tôi tìm lỗi nhé; cần tôi gửi thông tin gì?')
    tasks.append({'case':'debug_control','condition':'clean_explicit_help','repeat':1,'payload':control})
    random.Random(202611053).shuffle(tasks)
    plan=[{k:v for k,v in t.items() if k!='payload'} | {'request_sha256':hashlib.sha256(json.dumps(t['payload'],ensure_ascii=False,sort_keys=True).encode()).hexdigest()} for t in tasks]
    (run_dir/'plan.json').write_text(json.dumps(plan,indent=2),'utf-8')
    keys=json.loads(Path('C:/Users/Gtvkun/Documents/eris/config/secrets.json').read_text('utf-8-sig'))['api_keys']
    os.environ['ERIS_EQ_PROBE_API_KEY']=keys.get('ERIS_DS_EXECUTIVE_API_KEY') or keys['ERIS_DS2API_API_KEY']
    with path.open('x',encoding='utf-8') as out:
        for i,t in enumerate(tasks,1):
            r=shared.request(t,'http://127.0.0.1:5103/v1/chat/completions')
            out.write(json.dumps(r,ensure_ascii=False)+'\n');out.flush()
            print(i,r.get('http_status',r.get('error_type')),r['elapsed_seconds'],flush=True)
            if r.get('http_status')!=200:
                print('Service failure; stopping without retry.',flush=True)
                break


if __name__=='__main__':
    main()
