"""Twelve-call mechanism probe; preserve historical wire schema exactly."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import random
import sys
import urllib.request

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / '.agents/tasks/eris-eq-verification'))
# This script is named probe.py too, so load the shared helper under another name.
import importlib.util
spec = importlib.util.spec_from_file_location('eq_shared', REPO / '.agents/tasks/eris-eq-verification/probe.py')
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)


def main():
    rows = [json.loads(l) for l in (shared.RAW / 'events_20261103T145411Z_pid5836.jsonl').read_text('utf-8').splitlines()]
    spans = json.loads((REPO / '.agents/tasks/eris-initiative-ablation/manifest.json').read_text('utf-8'))[0]['removed_spans']
    rules = [
        '- Answer-first nếu evidence đủ; nếu thiếu evidence thì chuyển sang uncertainty/probe, không claim như fact.\n',
        '- Không chuyển thiếu evidence thành suy diễn tâm lý hoặc văn mẫu fallback tĩnh.\n',
    ]
    tasks = []
    manifest = []
    for case, ident, oracle in [
        ('vent', 'd88568e2807e48a1ac4f11bfdc0481ae', 'Người dùng đang tâm sự về sự bực bội khi làm việc với Kiro, chưa yêu cầu Eris chẩn đoán hay sửa code. Chi tiết lỗi code chưa rõ; nhu cầu hiện tại là được chia sẻ trải nghiệm khó chịu, không phải hoàn tất một yêu cầu hỗ trợ kỹ thuật.'),
        ('repair', '93677379697e4e409966c1468de1aaa3', 'Người dùng đang phản đối chính cách Eris tương tác: họ muốn tâm sự nhưng Eris tiếp tục hỏi kỹ thuật. Đây là lời sửa cách hiểu của Eris, không chỉ là thêm thông tin về Kiro. Các nhận định cũ rằng đây không phải lời sửa Eris không còn phù hợp.'),
    ]:
        row = next(r for r in rows if r.get('event') == 'request' and r.get('request_id') == ident)
        base = shared.restore(row['raw_request_ref'])
        system = base['messages'][0]['content']
        marker = '\n\n[OUTPUT_JSON_SCHEMA_REQUIREMENT]\n'
        assert system.count(marker) == 1
        suffix = system[system.index(marker):]
        for span in spans:
            assert system.count(span) == 1
            system = system.replace(span, '')
        base['messages'][0]['content'] = system
        assert system.endswith(suffix)
        ablated = deepcopy(base)
        env = json.loads(ablated['messages'][-1]['content'])
        grounding = env['runtime_context']['grounding_context']
        for rule in rules:
            assert grounding.count(rule) == 1
            grounding = grounding.replace(rule, '')
        env['runtime_context']['grounding_context'] = grounding
        ablated['messages'][-1]['content'] = json.dumps(env, ensure_ascii=False)
        guided = deepcopy(base)
        env = json.loads(guided['messages'][-1]['content'])
        env['research_oracle_situation'] = oracle
        guided['messages'][-1]['content'] = json.dumps(env, ensure_ascii=False)
        for condition, payload in [('baseline', base), ('remove_probe_rules', ablated), ('oracle_situation', guided)]:
            assert payload['messages'][0]['content'].endswith(suffix)
            assert payload['messages'][:-1] == base['messages'][:-1]
            assert {k:v for k,v in payload.items() if k!='messages'} == {k:v for k,v in base.items() if k!='messages'}
            manifest.append({'case':case,'condition':condition,'schema_suffix_sha256':hashlib.sha256(suffix.encode()).hexdigest(), 'system_sha256':hashlib.sha256(system.encode()).hexdigest()})
            for repeat in (1,2):
                tasks.append({'case':case,'condition':condition,'repeat':repeat,'payload':payload})
    random.Random(202611052).shuffle(tasks)
    (HERE/'manifest.json').write_text(json.dumps(manifest,indent=2),'utf-8')
    (HERE/'plan.json').write_text(json.dumps([{k:v for k,v in t.items() if k!='payload'} for t in tasks],indent=2),'utf-8')
    if '--run' not in sys.argv:
        print('Prepared 12 calls; wire/schema invariants passed. No calls made.')
        return
    with urllib.request.urlopen('http://127.0.0.1:5103/healthz', timeout=5) as health:
        assert health.status == 200
    credentials = json.loads(Path('C:/Users/Gtvkun/Documents/eris/config/secrets.json').read_text('utf-8-sig'))['api_keys']
    os.environ['ERIS_EQ_PROBE_API_KEY'] = credentials.get('ERIS_DS_EXECUTIVE_API_KEY') or credentials['ERIS_DS2API_API_KEY']
    path = HERE/'results.jsonl'
    existing = [json.loads(l) for l in path.read_text('utf-8').splitlines()] if path.exists() else []
    completed={(r['case'],r['condition'],r['repeat']) for r in existing if r.get('http_status')==200}
    tasks=[t for t in tasks if (t['case'],t['condition'],t['repeat']) not in completed]
    with ThreadPoolExecutor(max_workers=2) as ex, path.open('a',encoding='utf-8') as out:
        remaining=iter(tasks)
        pending=set()
        halted=False
        for task in list(tasks[:2]):
            next(remaining)
            pending.add(ex.submit(shared.request,task,'http://127.0.0.1:5103/v1/chat/completions'))
        while pending:
            finished,pending=wait(pending,return_when=FIRST_COMPLETED)
            for f in finished:
                r=f.result(); out.write(json.dumps(r,ensure_ascii=False)+'\n'); out.flush()
                print(r['case'],r['condition'],r['repeat'],r.get('http_status',r.get('error_type')),flush=True)
                if r.get('http_status')!=200:
                    halted=True
            if not halted:
                for _ in finished:
                    task=next(remaining,None)
                    if task is not None:
                        pending.add(ex.submit(shared.request,task,'http://127.0.0.1:5103/v1/chat/completions'))
        if halted:
            print('Stopped scheduling after service failure; failed tasks are not marked completed.',flush=True)


if __name__=='__main__':
    main()
