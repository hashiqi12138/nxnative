"""pack_server.py: the HTTP surface the app pulls a pack from.

A real server is started on an ephemeral port and driven with urllib, so the tests exercise the handler as the app
does - including the Range resume, the 80-byte /stamp probe, and the HTTP/1.1 keep-alive that the app's client
depends on (HTTP/1.0 made it report "Transferred a partial file" after every byte had arrived).
"""
import http.client
import json
import socket
import struct
import threading
import time
import urllib.error
import urllib.request

import pytest


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def server(pack_server, tmp_path, monkeypatch):
    """Start pack_server.main() in a thread on a free port; yields (port, pack_dir, nxpk_path, manifest_path)."""
    pack = tmp_path / 'pack'
    (pack / 'RomFS').mkdir(parents=True)
    (pack / 'nx2a-data.json').write_text(json.dumps({'title_id': 'T'}), encoding='utf-8')
    (pack / 'RomFS' / 'a.bin').write_bytes(b'A' * 100)
    (pack / 'env.txt').write_text('X=1\n', encoding='utf-8')
    manifest = tmp_path / 'dm.files.tsv'
    manifest.write_text('# DM_DATA abc123\nRomFS/a.bin\t100\t1\n', encoding='utf-8')

    # a small container: 80-byte header + 300 bytes of body
    header = b'NXPK' + bytes([1]) + b'\x00\x00\x00' + b'T'.ljust(16, b'\x00') + b's'.ljust(48, b'\x00') \
        + struct.pack('<Q', 300)
    nxpk = tmp_path / 'game.nxpk'
    nxpk.write_bytes(header + bytes(range(256)) * 2)[:380] if False else nxpk.write_bytes(header + b'B' * 300)

    port = free_port()
    argv = ['pack_server.py', '--pack', str(pack), '--manifest', str(manifest),
            '--nxpk', str(nxpk), '--port', str(port)]
    monkeypatch.setattr('sys.argv', argv)

    # serve_forever blocks: run main() in a daemon thread and wait for the port to answer
    t = threading.Thread(target=pack_server.main, daemon=True)
    t.start()
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.02)
    else:
        pytest.fail('pack_server did not start')

    yield port, pack, nxpk, manifest


def get(port, path, headers=None, method='GET'):
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    conn.request(method, path, headers=headers or {})
    r = conn.getresponse()
    body = r.read()
    out = (r.status, dict(r.getheaders()), body)
    conn.close()
    return out


# ---- /ping ----

def test_ping_answers_pong(server):
    port = server[0]
    status, headers, body = get(port, '/ping')
    assert status == 200
    assert body == b'PONG'
    assert headers['Content-Length'] == '4'


# ---- /stamp: the 80-byte probe the app makes before pulling 14 GB ----

def test_stamp_returns_exactly_the_header(server):
    port, _pack, nxpk, _man = server
    status, headers, body = get(port, '/stamp')
    assert status == 200
    assert len(body) == 80
    assert body == nxpk.read_bytes()[:80]
    assert body[:4] == b'NXPK'


def test_stamp_body_is_the_stamp_field(server):
    port, _pack, nxpk, _man = server
    _s, _h, body = get(port, '/stamp')
    # the app compares this against its sandbox's .stamp
    assert body[24:72].rstrip(b'\x00') == b's'


# ---- /pack.nxpk: the whole container ----

def test_pack_serves_the_whole_container(server):
    port, _pack, nxpk, _man = server
    status, headers, body = get(port, '/pack.nxpk')
    assert status == 200
    assert body == nxpk.read_bytes()
    assert headers['Content-Length'] == str(nxpk.stat().st_size)
    assert headers['Accept-Ranges'] == 'bytes'


def test_pack_advertises_octet_stream(server):
    port = server[0]
    _s, headers, _b = get(port, '/pack.nxpk')
    assert headers['Content-Type'] == 'application/octet-stream'


# ---- Range: the resume path ----

def test_range_returns_206_with_content_range(server):
    port, _pack, nxpk, _man = server
    status, headers, body = get(port, '/pack.nxpk', {'Range': 'bytes=100-'})
    assert status == 206
    assert headers['Content-Range'] == 'bytes 100-%d/%d' % (nxpk.stat().st_size - 1, nxpk.stat().st_size)
    assert body == nxpk.read_bytes()[100:]


def test_range_start_zero_is_a_plain_200(server):
    """bytes=0- is the same as no Range: the app sends it after a kill at byte 0."""
    port = server[0]
    status, _h, _b = get(port, '/pack.nxpk', {'Range': 'bytes=0-'})
    assert status == 200


def test_range_past_the_end_yields_an_empty_body(server):
    port, _pack, nxpk, _man = server
    status, headers, body = get(port, '/pack.nxpk', {'Range': 'bytes=%d-' % (nxpk.stat().st_size + 50)})
    # start is clamped to the size, so the response is a 206 with nothing left to send
    assert status == 206
    assert body == b''
    assert headers['Content-Length'] == '0'


def test_range_with_a_multi_range_takes_the_first(server):
    port, _pack, nxpk, _man = server
    status, _h, body = get(port, '/pack.nxpk', {'Range': 'bytes=10-19,50-59'})
    assert status == 206
    assert body == nxpk.read_bytes()[10:]


def test_range_that_is_not_a_number_is_ignored(server):
    port = server[0]
    status, _h, _b = get(port, '/pack.nxpk', {'Range': 'bytes=abc-'})
    assert status == 200


def test_range_without_the_bytes_prefix_is_ignored(server):
    port = server[0]
    status, _h, _b = get(port, '/pack.nxpk', {'Range': 'items=10-'})
    assert status == 200


# ---- HEAD ----

def test_head_reports_the_size_without_a_body(server):
    port, _pack, nxpk, _man = server
    status, headers, body = get(port, '/pack.nxpk', method='HEAD')
    assert status == 200
    assert body == b''
    assert headers['Content-Length'] == str(nxpk.stat().st_size)


def test_head_on_another_path_is_404(server):
    port = server[0]
    status, _h, body = get(port, '/nothing', method='HEAD')
    assert status == 404
    assert body == b''


# ---- the manifest and the legacy per-file path ----

def test_manifest_is_served_whole(server):
    port, _pack, _nxpk, man = server
    status, _h, body = get(port, '/dm.files.tsv')
    assert status == 200
    assert body == man.read_bytes()


def test_a_pack_file_is_served_by_path(server):
    """The legacy per-file path: SimpleHTTPRequestHandler serves the pack dir."""
    port = server[0]
    status, _h, body = get(port, '/RomFS/a.bin')
    assert status == 200
    assert body == b'A' * 100


def test_a_missing_file_is_404(server):
    port = server[0]
    status, _h, _b = get(port, '/RomFS/nope.bin')
    assert status == 404


# ---- without --nxpk: the container endpoints do not exist ----

def test_no_container_means_no_stamp(pack_server, tmp_path, monkeypatch):
    pack = tmp_path / 'p'
    pack.mkdir()
    port = free_port()
    monkeypatch.setattr('sys.argv', ['pack_server.py', '--pack', str(pack), '--port', str(port)])
    threading.Thread(target=pack_server.main, daemon=True).start()
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.02)
    status, _h, _b = get(port, '/stamp')
    assert status == 404


def test_no_container_means_no_pack_endpoint(pack_server, tmp_path, monkeypatch):
    pack = tmp_path / 'p'
    pack.mkdir()
    port = free_port()
    monkeypatch.setattr('sys.argv', ['pack_server.py', '--pack', str(pack), '--port', str(port)])
    threading.Thread(target=pack_server.main, daemon=True).start()
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.02)
    status, _h, _b = get(port, '/pack.nxpk')
    assert status == 404


# ---- argument validation ----

def test_missing_pack_dir_exits(pack_server, tmp_path, monkeypatch):
    monkeypatch.setattr('sys.argv', ['pack_server.py', '--pack', str(tmp_path / 'nope')])
    with pytest.raises(SystemExit, match='no such pack'):
        pack_server.main()


def test_missing_manifest_exits(pack_server, tmp_path, monkeypatch):
    pack = tmp_path / 'p'
    pack.mkdir()
    monkeypatch.setattr('sys.argv', ['pack_server.py', '--pack', str(pack), '--manifest', str(tmp_path / 'nope.tsv')])
    with pytest.raises(SystemExit, match='no such manifest'):
        pack_server.main()


def test_missing_container_exits(pack_server, tmp_path, monkeypatch):
    pack = tmp_path / 'p'
    pack.mkdir()
    monkeypatch.setattr('sys.argv', ['pack_server.py', '--pack', str(pack), '--nxpk', str(tmp_path / 'nope.nxpk')])
    with pytest.raises(SystemExit, match='no such container'):
        pack_server.main()

# ---- /list and /packs/<file>: the library's remote source (S4) ----
# A second server, because the plain `server` fixture serves one container and the library lists a folder.

@pytest.fixture
def library_server(pack_server, tmp_path, monkeypatch):
    """Start pack_server with --games-dir holding two containers; yields (port, games_dir)."""
    pack = tmp_path / 'pack2'
    (pack / 'RomFS').mkdir(parents=True)
    (pack / 'nx2a-data.json').write_text(json.dumps({'title_id': 'T'}), encoding='utf-8')
    games = tmp_path / 'library'
    games.mkdir()

    def container(name, title, stamp, size):
        header = (b'NXPK' + bytes([1]) + b'\x00\x00\x00' + title.encode().ljust(16, b'\x00')
                  + stamp.encode().ljust(48, b'\x00') + struct.pack('<Q', size))
        (games / name).write_bytes(header + b'B' * size)

    container('Celeste.nxpk', '01002B30028F6000', 'stamp-celeste', 40)
    container('Zelda.nxpk', '01007EF00011E000', 'stamp-zelda', 60)
    (games / 'notes.txt').write_text('not a container', encoding='utf-8')   # must be ignored
    (games / 'broken.nxpk').write_bytes(b'NOPE' + b'\x00' * 100)             # wrong magic: ignored

    port = free_port()
    monkeypatch.setattr('sys.argv', ['pack_server.py', '--pack', str(pack), '--games-dir', str(games),
                                     '--port', str(port)])
    t = threading.Thread(target=pack_server.main, daemon=True)
    t.start()
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.02)
    else:
        pytest.fail('pack_server did not start')
    yield port, games


def test_list_reports_the_containers_by_name(library_server):
    port, _games = library_server
    status, headers, body = get(port, '/list')
    assert status == 200
    assert headers.get('Content-Type') == 'application/json'
    items = json.loads(body)
    assert [i['file'] for i in items] == ['Celeste.nxpk', 'Zelda.nxpk']   # sorted by name


def test_list_carries_the_title_stamp_and_size(library_server):
    port, _games = library_server
    _s, _h, body = get(port, '/list')
    celeste = json.loads(body)[0]
    assert celeste['title'] == '01002B30028F6000'
    assert celeste['stamp'] == 'stamp-celeste'
    assert celeste['bytes'] == 120            # the 80-byte header and its 40-byte body
    assert celeste['url'] == '/packs/Celeste.nxpk'


def test_list_skips_a_file_that_is_not_a_container(library_server):
    port, _games = library_server
    _s, _h, body = get(port, '/list')
    names = [i['file'] for i in json.loads(body)]
    assert 'notes.txt' not in names
    assert 'broken.nxpk' not in names         # wrong magic


def test_list_is_empty_without_a_games_dir(pack_server, tmp_path, monkeypatch):
    """A server started the old way (one --nxpk) still answers /list, with that one container."""
    pack = tmp_path / 'pack3'
    pack.mkdir()
    header = b'NXPK' + bytes([1]) + b'\x00\x00\x00' + b'0100'.ljust(16, b'\x00') \
        + b'st'.ljust(48, b'\x00') + struct.pack('<Q', 10)
    nxpk = tmp_path / 'one.nxpk'
    nxpk.write_bytes(header + b'B' * 10)
    port = free_port()
    monkeypatch.setattr('sys.argv', ['pack_server.py', '--pack', str(pack), '--nxpk', str(nxpk),
                                     '--port', str(port)])
    threading.Thread(target=pack_server.main, daemon=True).start()
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.02)
    _s, _h, body = get(port, '/list')
    items = json.loads(body)
    assert len(items) == 1
    assert items[0]['url'] == '/pack.nxpk'


def test_packs_serves_one_container(library_server):
    port, games = library_server
    status, _h, body = get(port, '/packs/Celeste.nxpk')
    assert status == 200
    assert body == (games / 'Celeste.nxpk').read_bytes()


def test_packs_resumes_with_range(library_server):
    port, games = library_server
    status, headers, body = get(port, '/packs/Zelda.nxpk', {'Range': 'bytes=100-'})
    assert status == 206
    assert body == (games / 'Zelda.nxpk').read_bytes()[100:]
    assert 'Content-Range' in headers


def test_packs_rejects_a_name_outside_the_folder(library_server):
    """A traversal attempt is answered 404, not the file: the handler takes the basename alone."""
    port, _games = library_server
    for bad in ('/packs/../pack2/nx2a-data.json', '/packs/notes.txt', '/packs/missing.nxpk'):
        status, _h, _b = get(port, bad)
        assert status == 404, bad


def test_packs_is_404_without_a_games_dir(server):
    port, _pack, _nxpk, _man = server
    status, _h, _b = get(port, '/packs/anything.nxpk')
    assert status == 404

# ---- pack_titles: the display names inside a container ----
#
# The 80-byte header carries only the title ID, so /list reads the tar stream until it meets nx2a-data.json. These
# tests build that tar by hand: a real one would need the porter, and what is under test here is the header parsing,
# not the packer.

def tar_header(name, size, prefix=''):
    """A ustar header block, as tarfile writes it: name at 0, size at 124 (octal), prefix at 345."""
    h = bytearray(512)
    h[0:len(name)] = name.encode()
    h[124:124 + len(b'%011o' % size)] = b'%011o' % size
    h[156:157] = b'0'
    h[257:263] = b'ustar\0'
    if prefix:
        h[345:345 + len(prefix)] = prefix.encode()
    return bytes(h)


def tar_member(name, body, prefix=''):
    """One member: its header, its body, and the padding to the next 512-byte boundary."""
    pad = (-len(body)) % 512
    return tar_header(name, len(body), prefix) + body + b'\0' * pad


def container(tmp_path, members, name='t.nxpk', stamp='abc'):
    """An .nxpk: the 80-byte header, then the members."""
    tar = b''.join(members) + b'\0' * 1024
    header = b'NXPK' + bytes([1]) + b'\0\0\0' + b'T'.ljust(16, b'\0') + stamp.encode().ljust(48, b'\0') \
        + struct.pack('<Q', len(tar))
    p = tmp_path / name
    p.write_bytes(header + tar)
    return p


def test_pack_titles_reads_the_name_and_the_chinese_name(pack_server, tmp_path):
    man = json.dumps({'title_id': 'T', 'name': 'Celeste', 'name_zh': '蔚蓝'}).encode()
    p = container(tmp_path, [tar_member('nx2a-data.json', man)])
    assert pack_server.pack_titles(str(p)) == {'name': 'Celeste', 'name_zh': '蔚蓝'}


def test_pack_titles_skips_members_before_the_manifest(pack_server, tmp_path):
    # the porter writes env.txt and profile.tsv first in some pack layouts; the scan has to walk past them
    man = json.dumps({'name': 'After'}).encode()
    p = container(tmp_path, [tar_member('env.txt', b'X=1\n'), tar_member('RomFS/a.bin', b'A' * 700),
                             tar_member('nx2a-data.json', man)])
    assert pack_server.pack_titles(str(p)) == {'name': 'After'}


def test_pack_titles_ignores_a_manifest_under_a_prefix(pack_server, tmp_path):
    # pack_titles wants the manifest at the pack's root: a member whose ustar prefix puts it in a subdirectory is a
    # different file, and the scan walks past it (the porter writes the root one).
    man = json.dumps({'name': 'Prefixed'}).encode()
    p = container(tmp_path, [tar_member('nx2a-data.json', man, prefix='deep')])
    assert pack_server.pack_titles(str(p)) == {}


def test_pack_titles_accepts_a_dot_slash_name(pack_server, tmp_path):
    man = json.dumps({'name': 'Dotted'}).encode()
    p = container(tmp_path, [tar_member('./nx2a-data.json', man)])
    assert pack_server.pack_titles(str(p)) == {'name': 'Dotted'}


def test_pack_titles_omits_a_key_that_is_absent_or_empty(pack_server, tmp_path):
    # only the keys that carry a non-empty string: a reader falls back to `name` rather than showing an empty title
    man = json.dumps({'name': 'Only', 'name_zh': ''}).encode()
    p = container(tmp_path, [tar_member('nx2a-data.json', man)])
    assert pack_server.pack_titles(str(p)) == {'name': 'Only'}


def test_pack_titles_omits_a_key_that_is_not_a_string(pack_server, tmp_path):
    man = json.dumps({'name': 7, 'name_zh': ['x']}).encode()
    p = container(tmp_path, [tar_member('nx2a-data.json', man)])
    assert pack_server.pack_titles(str(p)) == {}


def test_pack_titles_is_empty_without_a_manifest(pack_server, tmp_path):
    p = container(tmp_path, [tar_member('env.txt', b'X=1\n')])
    assert pack_server.pack_titles(str(p)) == {}


def test_pack_titles_is_empty_for_a_missing_file(pack_server, tmp_path):
    assert pack_server.pack_titles(str(tmp_path / 'nope.nxpk')) == {}


def test_pack_titles_is_empty_when_the_size_is_not_octal(pack_server, tmp_path):
    # a corrupt header must not raise: the library falls back to the file name
    bad = bytearray(tar_header('nx2a-data.json', 0))
    bad[124:136] = b'zzzzzzzzzzz\0'
    p = container(tmp_path, [bytes(bad)])
    assert pack_server.pack_titles(str(p)) == {}


def test_pack_titles_is_empty_when_the_manifest_body_is_beyond_the_scan(pack_server, tmp_path):
    # the manifest claims more bytes than the scan window holds: no names rather than a truncated parse
    p = container(tmp_path, [tar_header('nx2a-data.json', 300 * 1024)])
    assert pack_server.pack_titles(str(p)) == {}


def test_pack_titles_is_empty_when_the_manifest_is_not_json(pack_server, tmp_path):
    p = container(tmp_path, [tar_member('nx2a-data.json', b'not json at all')])
    assert pack_server.pack_titles(str(p)) == {}


def test_pack_info_carries_the_names(pack_server, tmp_path):
    man = json.dumps({'name': 'Celeste', 'name_zh': '蔚蓝'}).encode()
    p = container(tmp_path, [tar_member('nx2a-data.json', man)], stamp='deadbeef')
    info = pack_server.pack_info(str(p))
    assert info['title'] == 'T'
    assert info['stamp'] == 'deadbeef'
    assert info['name'] == 'Celeste'
    assert info['name_zh'] == '蔚蓝'
    assert info['file'] == 't.nxpk'
    assert info['bytes'] == p.stat().st_size


def test_pack_info_is_none_for_a_file_that_is_not_a_container(pack_server, tmp_path):
    p = tmp_path / 'x.nxpk'
    p.write_bytes(b'not an nxpk at all, just some bytes that are long enough to be read')
    assert pack_server.pack_info(str(p)) is None


def test_pack_info_is_none_for_a_missing_file(pack_server, tmp_path):
    assert pack_server.pack_info(str(tmp_path / 'nope.nxpk')) is None


def test_list_carries_the_fields_the_library_reads(library_server):
    # /list's contract: every entry names the container, the title inside it, its stamp and its size. `name` is
    # present only when the container carries an nx2a-data.json (the fixture's are bare headers, so they carry none).
    port, games = library_server
    status, headers, body = get(port, '/list')
    assert status == 200
    entries = json.loads(body)
    assert entries, 'the fixture games dir holds one container'
    for e in entries:
        assert set(e) >= {'title', 'stamp', 'bytes', 'file'}, e
        assert e['file'].endswith('.nxpk'), e
        assert e['bytes'] > 0, e
