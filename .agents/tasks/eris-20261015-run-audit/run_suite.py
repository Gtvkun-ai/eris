import json
import os
from pathlib import Path
import sys

sys.stdout.reconfigure(encoding='utf-8')
root = Path(__file__).parent
sys.path.insert(0, str(root / 'pytest-tools'))
import pytest

class Report:
    def __init__(self, name):
        self.stream = (root / (name + '-events.jsonl')).open('w', encoding='utf-8', buffering=1)

    def pytest_runtest_logstart(self, nodeid, location):
        self.stream.write(json.dumps({'event': 'start', 'nodeid': nodeid}) + '\n')

    def pytest_runtest_logreport(self, report):
        if report.when == 'call' or report.failed or report.skipped:
            self.stream.write(json.dumps({'event': 'report', 'nodeid': report.nodeid,
                'when': report.when, 'outcome': report.outcome,
                'duration': report.duration, 'detail': str(report.longrepr) if report.failed else ''}) + '\n')

name = sys.argv[1]
args = sys.argv[2:] or ['-q', '--timeout=25', '--tb=short']
raise SystemExit(pytest.main(args, plugins=[Report(name)]))
