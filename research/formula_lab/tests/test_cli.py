import json
import os
import subprocess
import sys

from research.formula_lab import benchmark


def run(*args,env=None):
    return subprocess.run([sys.executable,'-m','research.formula_lab.cli',*args],capture_output=True,text=True,env=env)


def test_synthetic_compute_reports_no_ticket_or_period_values():
    p=run('synthetic','--train','40','--validation','10','--holdout','3')
    assert p.returncode==0,p.stderr
    data=json.loads(p.stdout)
    assert data['games']==['ssq','dlt'] and data['evaluated_per_mode']==3
    assert data['formal_A']==0 and data['edge']=='NO_EDGE'
    for private_key in ('predictions','front','back','issue','model_sha256'):
        assert private_key not in data


def test_private_cli_rejects_hosted_execution_without_echoing_inputs(tmp_path):
    private=tmp_path/'private';private.mkdir()
    secret=private/'SENSITIVE_FILENAME.json'
    secret.write_text('not even valid JSON')
    p=run('private','--authorized-root',str(private),'--input',str(secret),'--output',str(private/'out.json'),
          env=dict(os.environ,GITHUB_ACTIONS='true'))
    assert p.returncode==2
    assert 'SENSITIVE_FILENAME' not in p.stdout+p.stderr
    assert not (private/'out.json').exists()


def test_benchmark_measures_equivalent_work_and_limits():
    result=benchmark.measure(repeats=3,rows=60)
    assert result['parity_verified'] is True
    assert result['reference_seconds']>0 and result['numpy_seconds']>0
    assert result['speedup']==result['reference_seconds']/result['numpy_seconds']
    assert result['preferred_backend'] in ('numpy','reference')
    assert result['profile_top']


def test_malformed_arguments_do_not_echo_private_tokens():
    for args in [('private','--holdout','SENSITIVE_BAD_VALUE'),
                 ('private','SENSITIVE_FILENAME')]:
        p=run(*args,env=dict(os.environ,GITHUB_ACTIONS='true'))
        assert p.returncode==2
        assert 'SENSITIVE' not in p.stdout+p.stderr
        assert json.loads(p.stdout)['status']=='BLOCKED'
