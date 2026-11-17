"""integration_test.py: the upstream -> patches -> build -> tests chain.

The stage that matters is `build`, and what it must not do is believe build_ohos.py's compile line.
On 2026-11-17 a merge of upstream/main compiled 196 sources with 0 failures and then failed to link:
upstream had introduced DM_REGISTER (a Mach-O segment name) and NVN2 ray-tracing entry points the
Vulkan backend does not implement. Every gate in the repo passed. These tests pin the verdict logic
that would have caught it: the library must be produced by THIS run, and undefined symbols are named
in the failure detail rather than buried in a log tail.

The child processes are replaced with recorders, so nothing here compiles, links, or touches a device.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import integration_test as it  # noqa: E402


class Recorder:
    """Stands in for integration_test.run: returns canned output and records the commands."""

    def __init__(self, results):
        self.results = results          # list of (returncode, output), consumed in order
        self.calls = []

    def __call__(self, cmd, cwd=None, timeout=None):
        self.calls.append(list(cmd))
        return self.results.pop(0) if self.results else (0, '')


@pytest.fixture
def game(tmp_path, monkeypatch):
    """A repository shape the stage functions accept, with the game profile present."""
    repo = tmp_path / 'repo'
    (repo / 'dm' / 'host').mkdir(parents=True)
    (repo / 'dm' / 'games' / '01007EF00011E000').mkdir(parents=True)
    (repo / 'dm' / 'ohos' / 'tests').mkdir(parents=True)
    (repo / 'dm' / 'ohos' / 'build_ohos.py').write_text('', encoding='utf-8')
    (repo / 'dm' / 'ohos' / 'tests' / 'run_tests.py').write_text('', encoding='utf-8')
    (repo / 'dm' / 'tools').mkdir(parents=True)
    (repo / 'dm' / 'tools' / 'test_ohos_patches.py').write_text('', encoding='utf-8')
    monkeypatch.setattr(it, 'REPO', repo)
    monkeypatch.setattr(it, 'DM', repo / 'dm')
    monkeypatch.setattr(it, 'HERE', repo / 'dm' / 'ohos')
    return repo


def test_upstream_missing_is_a_skip_not_a_failure(game, monkeypatch):
    """No upstream/main ref: the port has not synced. That is a state, not a broken chain."""
    monkeypatch.setattr(it, 'run', Recorder([(1, '')]))
    st = it.stage_upstream()
    assert st.status == 'skip'
    assert 'sync_upstream' in st.detail


def test_upstream_reports_how_far_behind(game, monkeypatch):
    """Behind-ness is informational: a lagging merge is normal between syncs."""
    monkeypatch.setattr(it, 'run', Recorder([
        (0, 'db07cbde1234\n'),
        (0, '2026-11-17T12:00:00+08:00 game: Tropical Freeze\n'),
        (0, '59\n'),
    ]))
    st = it.stage_upstream()
    assert st.status == 'pass'
    assert 'db07cbde' in st.detail
    assert '59 commits behind' in st.detail


def test_patch_guard_failure_keeps_the_guard_line(game, monkeypatch):
    """A failing queue is a failure, and the guard's own summary travels in the detail."""
    monkeypatch.setattr(it, 'run', Recorder([
        (1, 'guard: 17 patches checked, 4 failures, 0 upstream-drift files pending sync\n'
            '  FAIL host/hle.h.patch: does not apply to upstream ()\n'),
    ]))
    st = it.stage_patches()
    assert st.status == 'fail'
    assert 'FAIL' in st.log


def test_patch_guard_pass_quotes_its_summary(game, monkeypatch):
    monkeypatch.setattr(it, 'run', Recorder([(0, 'guard: 17 patches checked, 0 failures, 0 upstream-drift files pending sync\n')]))
    st = it.stage_patches()
    assert st.status == 'pass'
    assert '17 patches checked, 0 failures' in st.detail


def test_build_names_undefined_symbols(game, monkeypatch):
    """The 2026-11-17 failure: compiles clean, does not link. The verdict must say which symbols."""
    out = ('compiled 196 sources, 0 failed\n'
           'ld.lld: error: undefined symbol: mtl_as_sizes\n'
           'ld.lld: error: undefined symbol: mtl_rt_program_set\n'
           'ld.lld: error: undefined symbol: mtl_as_sizes\n'
           'clang: error: linker command failed with exit code 1\n')
    monkeypatch.setattr(it, 'run', Recorder([(1, out)]))
    st = it.stage_build('01007EF00011E000', game / 'out', 0)
    assert st.status == 'fail'
    assert 'undefined symbols' in st.detail
    assert 'mtl_as_sizes' in st.detail
    assert 'mtl_rt_program_set' in st.detail
    # Deduplicated: the same symbol twice in the log is named once.
    assert st.detail.count('mtl_as_sizes') == 1
    # The compile line said success, and the stage still failed: that is the whole point.
    assert 'compiled 196 sources, 0 failed' in st.log


def test_build_without_the_library_is_a_failure(game, monkeypatch):
    """A zero exit with no artifact must not pass: a stale library is indistinguishable from a fresh one."""
    monkeypatch.setattr(it, 'run', Recorder([(0, 'compiled 196 sources, 0 failed\nlinked something\n')]))
    st = it.stage_build('01007EF00011E000', game / 'out', 0)
    assert st.status == 'fail'
    assert 'not produced' in st.detail


def test_build_accepts_a_fresh_library(game, monkeypatch):
    lib = game / 'out' / '01007EF00011E000' / 'libdmhost.so'
    lib.parent.mkdir(parents=True)

    def fake_run(cmd, cwd=None, timeout=None):
        lib.write_bytes(b'\x7fELF' + b'\0' * 1024)
        return 0, 'compiled 196 sources, 0 failed\nlinked %s\n' % lib

    monkeypatch.setattr(it, 'run', fake_run)
    st = it.stage_build('01007EF00011E000', game / 'out', 0)
    assert st.status == 'pass'
    assert 'compiled 196 sources' in st.detail


def test_build_rejects_a_library_this_run_did_not_write(game, monkeypatch):
    """The artifact must be newer than the run: otherwise an earlier build masks a broken one."""
    lib = game / 'out' / '01007EF00011E000' / 'libdmhost.so'
    lib.parent.mkdir(parents=True)
    lib.write_bytes(b'stale')

    def fake_run(cmd, cwd=None, timeout=None):
        lib.write_bytes(b'stale')          # present, but not rewritten
        return 0, 'compiled 196 sources, 0 failed\n'

    monkeypatch.setattr(it, 'run', fake_run)
    st = it.stage_build('01007EF00011E000', game / 'out', 10 ** 12)   # run started in the future
    assert st.status == 'fail'
    assert 'not rewritten' in st.detail


def test_build_clears_a_stale_library_before_running(game, monkeypatch):
    """A library left by an earlier run is removed first, so its presence cannot pass the stage."""
    lib = game / 'out' / '01007EF00011E000' / 'libdmhost.so'
    lib.parent.mkdir(parents=True)
    lib.write_bytes(b'left over')
    seen = {}

    def fake_run(cmd, cwd=None, timeout=None):
        seen['existed'] = lib.exists()
        return 1, 'ld.lld: error: undefined symbol: x\n'

    monkeypatch.setattr(it, 'run', fake_run)
    it.stage_build('01007EF00011E000', game / 'out', 0)
    assert seen['existed'] is False


def test_tests_stage_failure(game, monkeypatch):
    monkeypatch.setattr(it, 'run', Recorder([(1, '1 failed, 272 passed\n')]))
    st = it.stage_tests()
    assert st.status == 'fail'


def test_tests_stage_quotes_summary_and_coverage(game, monkeypatch):
    out = ('== 273 passed in 12.34s ==\n'
           'TOTAL   991   96   90.3%\n')
    monkeypatch.setattr(it, 'run', Recorder([(0, out)]))
    st = it.stage_tests()
    assert st.status == 'pass'
    assert '273 passed' in st.detail
    assert '90.3%' in st.detail


def test_missing_repo_is_exit_2(tmp_path, monkeypatch):
    """Prerequisites missing is a different answer from a failing stage: the caller can tell them apart."""
    monkeypatch.setattr(it, 'REPO', tmp_path)
    assert it.main([]) == 2


def test_missing_game_profile_is_exit_2(game, monkeypatch):
    assert it.main(['--game', '0100000000000000']) == 2


def test_pass_writes_a_verdict(game, monkeypatch):
    """The JSON verdict is what a bot reads: one entry per stage with its status."""
    monkeypatch.setattr(it, 'run', Recorder([
        (0, 'db07cbde1234\n'), (0, '2026-11-17T12:00:00+08:00 msg\n'), (0, '0\n'),   # upstream
        (0, 'guard: 17 patches checked, 0 failures, 0 upstream-drift files pending sync\n'),
        (0, 'compiled 196 sources, 0 failed\n'),                                      # build (skip-build)
        (0, '== 273 passed in 1s ==\nTOTAL 991 96 90.3%\n'),                         # tests
    ]))
    out = game / 'verdict.json'
    rc = it.main(['--skip-build', '--json', str(out)])
    assert rc == 0
    v = json.loads(out.read_text(encoding='utf-8'))
    assert v['result'] == 'pass'
    assert [s['stage'] for s in v['stages']] == ['upstream', 'patches', 'build', 'tests']
    assert v['stages'][2]['status'] == 'skip'


def test_failure_is_exit_1(game, monkeypatch):
    monkeypatch.setattr(it, 'run', Recorder([
        (0, 'db07cbde1234\n'), (0, '2026-11-17T12:00:00+08:00 msg\n'), (0, '0\n'),
        (1, 'guard: 17 patches checked, 1 failures\n'),
        (0, '== 273 passed in 1s ==\nTOTAL 991 96 90.3%\n'),
    ]))
    assert it.main(['--skip-build']) == 1
