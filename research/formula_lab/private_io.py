"""Explicitly authorized local storage. No real data on hosted CI or in Git."""
import json
import os
from pathlib import Path
import stat

MAX_BYTES=32*1024*1024


def _reparse(path):
    try: info=path.lstat()
    except FileNotFoundError:return False
    return path.is_symlink() or bool(getattr(info,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400))


def checked_path(path,authorized_root):
    if os.environ.get('GITHUB_ACTIONS','').lower()=='true':
        raise PermissionError('real input/output disabled on GitHub Actions')
    if any(os.environ.get(name) for name in ('GIT_DIR','GIT_WORK_TREE','GIT_COMMON_DIR',
           'GIT_INDEX_FILE','GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES')):
        raise PermissionError('redirected Git environment forbidden for private evidence')
    if authorized_root is None:raise PermissionError('explicit private root authorization required')
    root=Path(authorized_root).absolute();path=Path(path).absolute()
    for current in (root,path):
        for part in (current,*current.parents):
            if _reparse(part):raise PermissionError('symlink/junction/reparse path refused')
            if (part/'.git').exists() or (part/'HEAD').is_file() and (part/'objects').is_dir():
                raise PermissionError('Git directories/worktrees forbidden for private evidence')
    root=root.resolve();path=path.resolve()
    if not path.is_relative_to(root):raise PermissionError('destination outside authorized private root')
    return path


def write(path,obj,*,authorized_root):
    path=checked_path(path,authorized_root)
    raw=(json.dumps(obj,sort_keys=True,ensure_ascii=False,allow_nan=False,indent=2)+'\n').encode()
    if len(raw)>MAX_BYTES:raise ValueError('private output exceeds resource bound')
    path.parent.mkdir(parents=True,exist_ok=True)
    checked_path(path,authorized_root)
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb') as f:
        f.write(raw);f.flush();os.fsync(f.fileno())
    return path


def _pairs(pairs):
    obj={}
    for k,v in pairs:
        if k in obj:raise ValueError('duplicate JSON keys')
        obj[k]=v
    return obj


def read(path,*,authorized_root):
    path=checked_path(path,authorized_root)
    with path.open('rb') as f:raw=f.read(MAX_BYTES+1)
    if not raw or len(raw)>MAX_BYTES:raise ValueError('empty/oversize private input')
    def invalid(_):raise ValueError('nonfinite JSON')
    return json.loads(raw,object_pairs_hook=_pairs,parse_constant=invalid)
