"""Isolated current-policy check; does not import or run Eris runtime."""
import ast
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
import os
from pathlib import Path
import random
import sys
import urllib.request

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / '.agents/tasks/eris-eq-verification'))
from probe import RAW, restore, case_payload, request


def main():
    with urllib.request.urlopen('http://127.0.0.1:5103/healthz', timeout=5) as health:
        assert health.status == 200
    original = json.loads((HERE / 'baseline_core.json').read_text('utf-8'))
    module = ast.parse((REPO / 'src/runtime/conversation/root_prompt_contract.py').read_text('utf-8-sig'))
    lean = next(ast.literal_eval(n.value) for n in module.body if isinstance(n, ast.Assign))
    manifest = json.loads((REPO / '.agents/tasks/eris-initiative-ablation/manifest.json').read_text('utf-8'))
    expected = original
    for span in manifest[0]['removed_spans']:
        assert expected.count(span) == 1
        expected = expected.replace(span, '')
    assert lean == expected, 'Production change must be exactly the tested deletions'
    examples = (HERE / 'examples.txt').read_text('utf-8')
    rows = [json.loads(l) for l in (RAW / 'events_20261103T145411Z_pid5836.jsonl').read_text('utf-8').splitlines()]
    historical = []
    for name, ident in [('vent_runtime', 'd88568e2807e48a1ac4f11bfdc0481ae'),
                        ('repair_runtime', '93677379697e4e409966c1468de1aaa3')]:
        row = next(r for r in rows if r.get('event') == 'request' and r.get('request_id') == ident)
        historical.append((name, restore(row['raw_request_ref'])))
    template = historical[-1][1]
    controls = [
        ('discouraged', [], 'Tối nào cũng tập đàn mà nghe vẫn dở. Hôm nay hết muốn đụng vào nó luôn.'),
        ('angry_help', [], 'Bực thật, cửa hàng giao nhầm hàng rồi bắt tôi chờ. Soạn giúp tôi tin nhắn yêu cầu đổi, cần biết gì cứ hỏi.'),
        ('switch_to_help', [('user', 'Cứ bị từ chối hồ sơ, mệt quá.'), ('assistant', 'Cứ hy vọng rồi lại hụt, mệt thật.')],
         'Ừ. Giờ giúp tôi sửa CV nhé. Tôi nên gửi bản CV hay tin tuyển dụng trước?'),
        ('banter', [('assistant', 'Tôi đang trông nhà cho đống tab của anh đây.')], 'Nhớ tưới nước cho chúng, tab nào héo thì đem phơi nắng :))'),
        ('disagreement', [], 'Bạn bè tử tế thì phải bênh tôi kể cả khi tôi sai chứ. Bạn đồng ý không?'),
        ('initiative', [], 'Chọn một chuyện bạn thấy thú vị rồi kể luôn đi, tôi muốn nghe.'),
    ]
    cases = historical + [(name, case_payload(template, history, text)) for name, history, text in controls]
    tasks = []
    for name, payload in cases:
        for condition, core in [('original', original), ('lean', lean), ('lean_examples', lean + examples)]:
            modified = deepcopy(payload)
            modified['messages'][0]['content'] = core
            assert modified['messages'][1:] == payload['messages'][1:]
            for repeat in (1, 2):
                tasks.append({'case': name, 'condition': condition, 'repeat': repeat, 'payload': modified})
    random.Random(202611051).shuffle(tasks)
    (HERE / 'plan.json').write_text(json.dumps([{k: v for k, v in t.items() if k != 'payload'} for t in tasks], indent=2), 'utf-8')
    credentials = json.loads(Path('C:/Users/Gtvkun/Documents/eris/config/secrets.json').read_text('utf-8-sig'))['api_keys']
    os.environ['ERIS_EQ_PROBE_API_KEY'] = credentials.get('ERIS_DS_EXECUTIVE_API_KEY') or credentials['ERIS_DS2API_API_KEY']
    path = HERE / 'results.jsonl'
    existing = [json.loads(l) for l in path.read_text('utf-8').splitlines()] if path.exists() else []
    completed = {(r['case'], r['condition'], r['repeat']) for r in existing}
    tasks = [t for t in tasks if (t['case'], t['condition'], t['repeat']) not in completed]
    with ThreadPoolExecutor(max_workers=2) as executor, path.open('a', encoding='utf-8') as out:
        futures = [executor.submit(request, t, 'http://127.0.0.1:5103/v1/chat/completions') for t in tasks]
        for future in as_completed(futures):
            result = future.result()
            out.write(json.dumps(result, ensure_ascii=False) + '\n')
            out.flush()
            print(result['case'], result['condition'], result['repeat'], result.get('http_status', result.get('error_type')), flush=True)


if __name__ == '__main__':
    main()
