#!/usr/bin/env python3
"""OHOS port integration test: upstream sync -> patch queue -> native build -> unit tests.

This is the chain that broke silently on 2026-11-17. A merge of upstream/main applied cleanly
in git and passed every unit test, yet the port no longer linked: upstream had replaced the
hand-written linker-section attributes with a DM_REGISTER macro that hardcodes the Mach-O
segment name, and added NVN2 ray-tracing entry points the Vulkan backend does not implement.
Git reported two trivial conflicts; the real breakage was five undefined symbols at link time,
which no existing gate covered. test_ohos_patches.py checks the patch queue against upstream
main, but nothing checked that the merged tree still builds.

    python dm/ohos/integration_test.py                # full chain
    python dm/ohos/integration_test.py --skip-build   # everything but the native build
    python dm/ohos/integration_test.py --game 01002B30028F6000
    python dm/ohos/integration_test.py --json out.json

Stages, each reported pass/fail/skip with its own evidence:

  1. upstream   upstream/main exists in the nested repo and is reachable (sync_upstream.py runs
                it; a missing ref is a skip for the patch stage, not a failure of this script)
  2. patches    dm/tools/test_ohos_patches.py: every patch applies to upstream main and
                reproduces the working tree exactly
  3. build      build_ohos.py --lib for one game: compiles AND links
  4. tests      dm/ohos/tests/run_tests.py: the port's unit suite with its coverage gate

Stage 3 is the one this script exists for. build_ohos.py exits non-zero on a link failure but
still prints "compiled N sources, 0 failed" first, so a caller that greps only the compile line
concludes success while no library was produced. The verdict therefore requires the linked
artifact to exist and to be newer than the run started.

Exit code: 0 all stages passed, 1 a stage failed, 2 the device-independent prerequisites are
missing (no nested repo, no game profile).
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent          # dm/ohos/
DM = HERE.parent                                        # dm/
REPO = DM.parent                                        # repository root
DEFAULT_GAME = '01007EF00011E000'                       # BOTW: the game the port is brought up on
os.environ.setdefault('PYTHONUTF8', '1')                # the children open game paths this console's page cannot name


def run(cmd, cwd=None, timeout=None):
    """Run a child and return (returncode, combined output). Never raises on a non-zero exit."""
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=timeout)
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def tail(text, n=40):
    lines = text.strip().splitlines()
    return '\n'.join(lines[-n:])


class Stage:
    def __init__(self, name):
        self.name = name
        self.status = 'skip'
        self.detail = ''
        self.log = ''

    def ok(self, detail='', log=''):
        self.status, self.detail, self.log = 'pass', detail, log
        return self

    def fail(self, detail, log=''):
        self.status, self.detail, self.log = 'fail', detail, log
        return self

    def skip(self, detail):
        self.status, self.detail = 'skip', detail
        return self

    def as_dict(self):
        return {'stage': self.name, 'status': self.status, 'detail': self.detail}


def stage_upstream():
    """upstream/main must exist: the patch guard reads it, and a stale ref makes the guard lie."""
    st = Stage('upstream')
    rc, out = run(['git', 'rev-parse', '--verify', '--quiet', 'upstream/main'], cwd=REPO)
    if rc != 0:
        return st.skip('no upstream/main ref (run dm/tools/sync_upstream.py)')
    sha = out.strip()
    rc2, date = run(['git', 'log', '-1', '--format=%cI %s', 'upstream/main'], cwd=REPO)
    # How far the port is behind: informational, never a failure. A merge that lags upstream is a
    # normal state between syncs; what must not happen is merging without re-checking the queue.
    rc3, behind = run(['git', 'rev-list', '--count', 'HEAD..upstream/main'], cwd=REPO)
    n = behind.strip() if rc3 == 0 else '?'
    return st.ok('%s (%s), %s commits behind' % (sha[:8], date.strip(), n))


def stage_patches():
    """The queue must apply to upstream main and reproduce the tree: the port's syncability contract."""
    st = Stage('patches')
    script = DM / 'tools' / 'test_ohos_patches.py'
    if not script.is_file():
        return st.fail('missing %s' % script)
    rc, out = run([sys.executable, str(script)], cwd=REPO)
    if rc != 0:
        return st.fail('patch guard failed', out)
    # The guard's own summary line: "guard: N patches checked, M failures, ..."
    line = next((l for l in out.splitlines() if l.startswith('guard:')), '')
    return st.ok(line.strip() or 'all patches apply', out)


def stage_build(game, out_dir, started):
    """Compile AND link. The link is the assertion: a missing backend symbol still compiles clean."""
    st = Stage('build')
    script = HERE / 'build_ohos.py'
    lib = pathlib.Path(out_dir) / game / 'libdmhost.so'
    try:
        if lib.exists():
            lib.unlink()          # so a stale library from an earlier run cannot pass this stage
    except OSError as e:
        return st.fail('cannot clear %s: %s' % (lib, e))
    rc, out = run([sys.executable, str(script), '--lib', '--game', game], cwd=REPO)
    if rc != 0:
        # Name the linker symbols when that is what went wrong: it is the failure this stage exists for.
        undef = sorted({l.split('undefined symbol:')[-1].strip()
                        for l in out.splitlines() if 'undefined symbol:' in l})
        why = 'undefined symbols: ' + ', '.join(undef) if undef else 'build failed'
        return st.fail(why, out)
    if not lib.is_file():
        return st.fail('build reported success but %s was not produced' % lib, out)
    if lib.stat().st_mtime < started:
        return st.fail('%s was not rewritten by this run' % lib, out)
    compiled = next((l.strip() for l in out.splitlines() if l.startswith('compiled ')), '')
    return st.ok('%s; linked %s (%.1f MB)' % (compiled, lib.name, lib.stat().st_size / 1e6), out)


def stage_tests():
    """The port's unit suite and its coverage gate."""
    st = Stage('tests')
    script = HERE / 'tests' / 'run_tests.py'
    if not script.is_file():
        return st.fail('missing %s' % script)
    rc, out = run([sys.executable, str(script)], cwd=REPO)
    if rc != 0:
        return st.fail('unit tests or the coverage gate failed', out)
    # run_tests prints a pytest summary line and a coverage TOTAL row; quote both when present.
    passed = next((l.strip() for l in out.splitlines() if ' passed' in l and ('==' in l or ' in ' in l)), '')
    total = next((l.strip() for l in out.splitlines() if l.strip().startswith('TOTAL')), '')
    return st.ok('; '.join(x for x in (passed, total) if x) or 'suite passed', out)


def main(argv=None):
    ap = argparse.ArgumentParser(description='OHOS port integration test: upstream -> patches -> build -> tests.')
    ap.add_argument('--game', default=DEFAULT_GAME, help='title ID for the build stage (default: %(default)s)')
    ap.add_argument('--out-dir', default=str(HERE / 'out'),
                    help='where build_ohos.py writes (default: dm/ohos/out)')
    ap.add_argument('--skip-build', action='store_true', help='skip the native build (fast: patches and tests only)')
    ap.add_argument('--json', help='write the verdict here (default: none)')
    a = ap.parse_args(argv)

    if not (REPO / 'dm' / 'host').is_dir():
        print('integration_test: %s is not the nested nxnative repo' % REPO, file=sys.stderr)
        return 2
    profile = REPO / 'dm' / 'games' / a.game
    if not profile.is_dir():
        print('integration_test: no game profile dm/games/%s' % a.game, file=sys.stderr)
        return 2

    started = time.time()
    stages = [stage_upstream(), stage_patches()]
    stages.append(Stage('build').skip('--skip-build') if a.skip_build else stage_build(a.game, a.out_dir, started))
    stages.append(stage_tests())

    width = max(len(s.name) for s in stages)
    print()
    for s in stages:
        print('  %-*s  %-4s  %s' % (width, s.name, s.status.upper(), s.detail))
    failed = [s for s in stages if s.status == 'fail']
    print()
    if failed:
        for s in failed:
            print('--- %s output (tail) ---' % s.name)
            print(tail(s.log))
            print()
        print('integration_test: FAIL (%d of %d stages)' % (len(failed), len(stages)))
    else:
        print('integration_test: PASS (%d stages, %.1fs)' % (len(stages), time.time() - started))

    if a.json:
        verdict = {'result': 'fail' if failed else 'pass',
                   'game': a.game,
                   'elapsed_s': round(time.time() - started, 1),
                   'stages': [s.as_dict() for s in stages]}
        pathlib.Path(a.json).write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding='utf-8')
        print('verdict: %s' % a.json)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
