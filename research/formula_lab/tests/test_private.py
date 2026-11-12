import json
from pathlib import Path
import subprocess
import sys

import pytest

from research.formula_lab import private_io as io
from research.formula_lab import prospective


def test_explicit_external_root_and_create_only(tmp_path,monkeypatch):
    monkeypatch.delenv('GITHUB_ACTIONS',raising=False)
    with pytest.raises(PermissionError): io.write(tmp_path/'a.json',{},authorized_root=None)
    io.write(tmp_path/'a.json',{'data':'synthetic'},authorized_root=tmp_path)
    with pytest.raises(FileExistsError): io.write(tmp_path/'a.json',{},authorized_root=tmp_path)
    with pytest.raises(PermissionError): io.write(tmp_path.parent/'escape.json',{},authorized_root=tmp_path)


def test_all_git_worktrees_and_nested_git_directories_forbidden(tmp_path,monkeypatch):
    monkeypatch.delenv('GITHUB_ACTIONS',raising=False)
    for kind in ('directory','file'):
        root=tmp_path/kind; root.mkdir()
        marker=root/'.git'
        marker.mkdir() if kind=='directory' else marker.write_text('gitdir: elsewhere')
        with pytest.raises(PermissionError): io.write(root/'evidence'/'a.json',{},authorized_root=root/'evidence')


def test_hosted_real_data_reads_and_writes_refused(tmp_path,monkeypatch):
    monkeypatch.setenv('GITHUB_ACTIONS','true')
    with pytest.raises(PermissionError): io.write(tmp_path/'x.json',{},authorized_root=tmp_path)
    with pytest.raises(PermissionError): io.read(tmp_path/'x.json',authorized_root=tmp_path)


@pytest.mark.parametrize('name',['GIT_DIR','GIT_WORK_TREE','GIT_COMMON_DIR','GIT_INDEX_FILE','GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES'])
def test_redirected_git_environment_cannot_hide_worktree(tmp_path,monkeypatch,name):
    monkeypatch.delenv('GITHUB_ACTIONS',raising=False)
    monkeypatch.setenv(name,str(tmp_path/'synthetic_git_metadata'))
    with pytest.raises(PermissionError):io.write(tmp_path/'private.json',{},authorized_root=tmp_path)


def test_symlink_escape_refused(tmp_path,monkeypatch):
    monkeypatch.delenv('GITHUB_ACTIONS',raising=False)
    private=tmp_path/'private';private.mkdir()
    other=tmp_path/'other';other.mkdir()
    link=private/'link'
    try: link.symlink_to(other,target_is_directory=True)
    except OSError:
        if sys.platform!='win32': raise
        # Directory junction creation does not require Windows developer mode.
        completed=subprocess.run(['powershell','-NoProfile','-Command',
            "New-Item -ItemType Junction -Path '"+str(link)+"' -Target '"+str(other)+"' | Out-Null"],capture_output=True)
        assert completed.returncode==0
    with pytest.raises(PermissionError): io.write(link/'x.json',{},authorized_root=private)


def test_duplicate_json_keys_and_large_inputs_fail_closed(tmp_path,monkeypatch):
    monkeypatch.delenv('GITHUB_ACTIONS',raising=False)
    path=tmp_path/'x.json';path.write_text('{"a":1,"a":2}')
    with pytest.raises(ValueError):io.read(path,authorized_root=tmp_path)
    path.write_text('{"a":NaN}')
    with pytest.raises(ValueError):io.read(path,authorized_root=tmp_path)


def test_caller_assertions_and_local_hash_are_never_trusted_predraw_proof():
    result=prospective.admission({'official_verified':True,'cutoff_verified':True,
        'tsa_verified':True,'sha256':'a'*64})
    assert result['formal_A']==0 and result['edge']=='NO_EDGE'
    assert result['eligible_predictions']==0 and result['status']=='BLOCKED'
    assert result['missing_verifiers']
