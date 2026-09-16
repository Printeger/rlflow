import hashlib
import os
from pathlib import Path
import tracemalloc
import pytest
from rlflow.files import stream_digest, SourceIndex, validate_inputs
from rlflow.store import Conflict


def test_stream_hash_2gib_output_is_never_read(tmp_path,monkeypatch):
    source=tmp_path/'source.py';source.write_text('print(1)')
    output=tmp_path/'output';output.mkdir()
    with (output/'experiment.bin').open('wb') as f:f.truncate(2*1024**3)
    for i in range(500):(output/f'{i}.log').touch()
    opened=[];original=os.open
    def observe(path,*args,**kwargs):
        opened.append(str(path));return original(path,*args,**kwargs)
    monkeypatch.setattr(os,'open',observe)
    index=SourceIndex();expected=index.scan(tmp_path,['source.py'],boundary=True)
    assert index.scan(tmp_path,['source.py'])==expected
    assert not any(name=='output' or name=='experiment.bin' or name.endswith('.log') for name in opened)


def test_large_hash_has_bounded_python_allocation(tmp_path):
    path=tmp_path/'large'
    with path.open('wb') as f:f.truncate(128*1024**2)
    tracemalloc.start();stream_digest(path);_,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    assert peak<16*1024**2


def test_reject_links_and_mid_read_replacement(tmp_path,monkeypatch):
    source=tmp_path/'source';source.write_bytes(b'a'*2000000)
    symlink=tmp_path/'sym';symlink.symlink_to(source)
    with pytest.raises(Conflict):stream_digest(symlink)
    hard=tmp_path/'hard';os.link(source,hard)
    with pytest.raises(Conflict):stream_digest(source)
    hard.unlink()
    original=os.read;changed=False
    def change(fd,n):
        nonlocal changed
        data=original(fd,n)
        if not changed:changed=True;source.write_bytes(b'b')
        return data
    monkeypatch.setattr(os,'read',change)
    with pytest.raises(Conflict,match='changed'):stream_digest(source)


def test_source_index_changes_and_boundary_rehash(tmp_path,monkeypatch):
    path=tmp_path/'a';path.write_text('a')
    index=SourceIndex();first=index.scan(tmp_path,['a'])
    path.write_text('b');assert index.scan(tmp_path,['a'])!=first
    path.rename(tmp_path/'b')
    with pytest.raises(Conflict):index.scan(tmp_path,['a'])
    assert index.scan(tmp_path,['b'],boundary=True)['files']['b']==hashlib.sha256(b'b').hexdigest()


def test_mutation_of_previously_hashed_source_is_rejected(tmp_path,monkeypatch):
    from rlflow import files
    (tmp_path/'a').write_text('one');(tmp_path/'b').write_text('two')
    original=files.stream_digest
    def mutate(path,**kwargs):
        digest=original(path,**kwargs)
        if Path(path).name=='b':(tmp_path/'a').write_text('late change')
        return digest
    monkeypatch.setattr(files,'stream_digest',mutate)
    with pytest.raises(Conflict,match='during scan'):SourceIndex().scan(tmp_path,['a','b'],boundary=True)
