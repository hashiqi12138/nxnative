"""Build a .nxpk game data pack: an 80-byte header framing a standard ustar tar stream.

The container exists so a game data pack is ONE file a user can copy, share or download, and so the app can
validate it before unpacking 14 GB. The body is a plain tar - we do not invent an archive format, we frame one.

Header layout (little-endian, fixed 80 bytes):

    offset  size  field
    0       8     magic b"NXPK" + version byte (1) + 3 reserved zero bytes
    8       16    title ID, ASCII, NUL-padded ("01007EF00011E000")
    24      48    pack stamp, ASCII sha1-hex of dm.files.tsv's stamp line, NUL-padded
    72      8     tar size in bytes, u64

The stamp is the same one dm.files.tsv carries in its "# DM_DATA <sha1>" header, computed by
gen_pack_manifest.py over (rel, size, mtime_ns). The app compares it against the sandbox's .stamp file and skips
the import entirely when they match - the whole point of the design (see DESIGN-P2.1-GameDataDistribution.md).

    python dm/tools/pack_game.py --pack <porter pack dir> --title 01007EF00011E000 [--out <file>.nxpk]
    python dm/tools/pack_game.py --pack <dir> --title <id> --check <file>.nxpk   # validate an existing pack

The pack dir must hold nx2a-data.json (the porter's marker). dm.files.tsv is generated into the pack dir when it
is absent, so a freshly ported tree can be packed in one command.
"""
import argparse
import hashlib
import os
import struct
import subprocess
import sys
import tarfile

MAGIC = b'NXPK'
VERSION = 1
HEADER_SIZE = 80
TITLE_LEN = 16
STAMP_LEN = 48


def build_header(title, stamp, tar_size):
    if len(title) > TITLE_LEN:
        raise SystemExit('pack_game: title ID longer than %d bytes: %r' % (TITLE_LEN, title))
    if len(stamp) > STAMP_LEN:
        raise SystemExit('pack_game: stamp longer than %d bytes: %r' % (STAMP_LEN, stamp))
    magic = MAGIC + bytes([VERSION]) + b'\x00\x00\x00'
    return (magic
            + title.encode('ascii').ljust(TITLE_LEN, b'\x00')
            + stamp.encode('ascii').ljust(STAMP_LEN, b'\x00')
            + struct.pack('<Q', tar_size))


def read_header(f):
    raw = f.read(HEADER_SIZE)
    if len(raw) != HEADER_SIZE:
        raise SystemExit('pack_game: file shorter than the header (%d bytes)' % len(raw))
    if raw[:4] != MAGIC:
        raise SystemExit('pack_game: not a game pack (magic %r)' % raw[:4])
    ver = raw[4]
    title = raw[8:8 + TITLE_LEN].rstrip(b'\x00').decode('ascii', 'replace')
    stamp = raw[24:24 + STAMP_LEN].rstrip(b'\x00').decode('ascii', 'replace')
    (tar_size,) = struct.unpack('<Q', raw[72:80])
    return {'version': ver, 'title': title, 'stamp': stamp, 'tar_size': tar_size}


def write_profile(pack, title):
    """P4.1: the runtime host's constants for this pack — game.py profile's rows from dm/games/<title>/game.tsv.
    Returns the path, or None when the title has no profile (a builtin host still runs the pack)."""
    here = os.path.dirname(os.path.abspath(__file__))
    gamepy = os.path.join(os.path.dirname(here), 'games', 'game.py')
    if not os.path.isfile(gamepy):
        return None
    dst = os.path.join(pack, 'profile.tsv')
    rc = subprocess.run([sys.executable, gamepy, 'profile', title, dst])
    if rc.returncode != 0:
        print('pack_game: %s has no game profile; the pack carries no profile.tsv (a builtin host still runs it)' % title)
        return None
    print('pack_game: profile.tsv from dm/games/%s/game.tsv' % title)
    return dst


def ensure_manifest(pack, force=False):
    """dm.files.tsv in the pack dir, or None when it cannot be produced (the stamp then falls back to a tar hash).
    force: regenerate it, so a file this run added (profile.tsv) takes part in the stamp."""
    man = os.path.join(pack, 'dm.files.tsv')
    if os.path.isfile(man) and not force:
        return man
    here = os.path.dirname(os.path.abspath(__file__))
    gen = os.path.join(here, 'gen_pack_manifest.py')
    if not os.path.isfile(gen):
        return None
    rc = subprocess.run([sys.executable, gen, '--pack', pack, '--out', man])
    return man if rc.returncode == 0 and os.path.isfile(man) else None


def manifest_stamp(man):
    with open(man, 'r', encoding='utf-8', errors='replace') as f:
        first = f.readline().strip()
    if first.startswith('# DM_DATA '):
        return first[len('# DM_DATA '):].strip()
    return ''


def build(pack, title, out):
    pack = os.path.abspath(pack)
    if not os.path.isdir(pack):
        raise SystemExit('pack_game: no such pack dir: %s' % pack)
    if not os.path.isfile(os.path.join(pack, 'nx2a-data.json')):
        raise SystemExit('pack_game: %s has no nx2a-data.json - point --pack at the porter data pack folder' % pack)
    man = ensure_manifest(pack, force=write_profile(pack, title) is not None)
    stamp = manifest_stamp(man) if man else ''
    if not stamp:
        # no manifest: stamp the pack contents' own shape so the app still has a change detector
        h = hashlib.sha1()
        for d, _, fs_ in os.walk(pack):
            for name in sorted(fs_):
                p = os.path.join(d, name)
                rel = os.path.relpath(p, pack).replace('\\', '/')
                st = os.stat(p)
                h.update(('%s\t%d\t%d\n' % (rel, st.st_size, st.st_mtime_ns)).encode())
        stamp = h.hexdigest()
        print('pack_game: no dm.files.tsv; stamping the tree instead')

    # Build the tar into a temp file beside the output (F: has room; C: TEMP does not for 14 GB)
    # GNU, not ustar: ustar splits a path into a 155-byte prefix and a 100-byte name, so a single file name longer
    # than 100 bytes cannot be encoded at all ("name is too long"). Tears of the Kingdom has 48 such names in its
    # RomFS (RomFS/Event/.../VisibleSageAndNotParticipateCombWithIgnoreDissentPlayFlowchartEvent.engine__event__...).
    # GNU format writes those as a '././@LongLink' member (typeflag 'L') whose data is the full path, then the
    # header; the app's reader (PackImport.ets) takes that member as the next header's name.
    tar_path = out + '.tar.tmp'
    n = 0
    with tarfile.open(tar_path, 'w', format=tarfile.GNU_FORMAT) as tf:
        # The small metadata members go first, RomFS and the rest after them. A reader that wants only the pack's
        # names (pack_server.pack_titles, for the library's list) then finds nx2a-data.json within the first
        # kilobyte instead of walking a multi-GB tar to the end, where the alphabetical order used to put it
        # (measured: Celeste's manifest sat at offset 1.26 GB). The import reads the whole tar either way, so the
        # order costs it nothing.
        names = sorted(os.listdir(pack))
        first = [n_ for n_ in names if n_ in ('nx2a-data.json', 'profile.tsv', 'env.txt', 'settings.txt', 'icon.jpg')]
        rest = [n_ for n_ in names if n_ not in first]
        for name in first + rest:
            if name == 'dm.files.tsv':
                continue   # the manifest rides in the header, not the body: the app must not unpack it
            tf.add(os.path.join(pack, name), arcname=name)
            n += 1
    tar_size = os.path.getsize(tar_path)
    print('pack_game: tar %d top-level entries, %.2f GB' % (n, tar_size / 2**30))

    with open(out, 'wb') as dst, open(tar_path, 'rb') as src:
        dst.write(build_header(title, stamp, tar_size))
        while True:
            buf = src.read(1 << 22)
            if not buf:
                break
            dst.write(buf)
    os.remove(tar_path)
    print('pack_game: wrote %s (%.2f GB, title %s, stamp %s)'
          % (out, os.path.getsize(out) / 2**30, title, stamp[:12]))
    return out


def check(path):
    with open(path, 'rb') as f:
        h = read_header(f)
    size = os.path.getsize(path)
    expect = HEADER_SIZE + h['tar_size']
    ok = size == expect
    print('pack_game: %s' % path)
    print('  version %d, title %s, stamp %s' % (h['version'], h['title'], h['stamp']))
    print('  tar %d bytes, file %d bytes -> %s' % (h['tar_size'], size, 'consistent' if ok else 'MISMATCH'))
    # count the tar's members (streaming, no seek back over 14 GB)
    n = 0
    with open(path, 'rb') as f:
        f.seek(HEADER_SIZE)
        with tarfile.open(fileobj=f, mode='r|') as tf:
            for _ in tf:
                n += 1
    print('  members: %d' % n)
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pack', required=True, help='the porter data pack folder (nx2a-data.json + RomFS/ + mods/)')
    ap.add_argument('--title', required=True, help='title ID, e.g. 01007EF00011E000')
    ap.add_argument('--out', help='output .nxpk (default: <title>.nxpk beside the pack)')
    ap.add_argument('--check', help='validate an existing .nxpk instead of building')
    a = ap.parse_args()
    if a.check:
        sys.exit(check(a.check))
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.pack)), a.title + '.nxpk')
    build(a.pack, a.title, out)


if __name__ == '__main__':
    main()
