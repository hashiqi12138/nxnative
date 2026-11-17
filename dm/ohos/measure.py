#!/usr/bin/env python3
"""Measure one device run of a game and report per-frame costs from the port's own counters.

Every earlier performance claim in this port was undermined by the same mistake: subtracting cumulative
counters taken at different moments, across windows that spanned the title screen, a load and gameplay. The
counters only mean something when both samples come from the SAME window of the SAME scene, so this script
takes two samples a fixed number of frames apart and divides by that frame count.

    python dm/ohos/measure.py --samples 2 --gap 20
    python dm/ohos/measure.py --scene shrine --gap 30

It reads the device's hilog, so the game must already be running in the scene to measure. What it refuses to
do is guess: a counter pair whose frame numbers did not advance by the gap it asked for is reported as a
failed sample, not silently averaged with good ones.

Fields, each already per frame (delta / frames):

  frame_ms      the whole frame, p50, from the timing report
  gpu_ms        GPU timestamp span, p50 (includes gaps between early submissions; see P3.4)
  replay_ms     the replay thread's own time, p50 of the slow-replay samples in the window
  sets_ms       stage_set total, p50 of the same samples
  memo_ms       stage_set's memo lookup, from the set-split counters
  collect_ms    collecting each binding's descriptor
  hash_ms       hashing the set's content
  allocw_ms     allocating the set and issuing vkUpdateDescriptorSets
  new_sets      sets built, not reused
  reused_sets   sets taken from the content cache
"""
import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import time

HDC_DEFAULT = r'E:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\toolchains\hdc.exe'
BUNDLE = 'dev.eden_emu.ohos'
TAG = 'dmhost'
os.environ.setdefault('PYTHONUTF8', '1')

# Each counter line the port prints, and the fields taken from it. The numbers are cumulative since start-up.
RE_SETS = re.compile(r'sets \(present (\d+)\): (\d+) reused, (\d+) new; hash ([\d.]+) ms, collect ([\d.]+) ms, alloc\+write ([\d.]+) ms')
RE_SPLIT = re.compile(r'set split: memo ([\d.]+) ms, collect ([\d.]+) ms, hash ([\d.]+) ms, alloc\+write ([\d.]+) ms, bind ([\d.]+) ms')
RE_TIMING = re.compile(r'timing up to frame (\d+): frame time p50 ([\d.]+).*?GPU p50 ([\d.]+)')
RE_REPLAY = re.compile(r'slow replay \(present (\d+)\): ([\d.]+) ms;.*?descriptor sets ([\d.]+) ms')


def hdc_path(arg):
    if arg:
        return arg
    if os.path.isfile(HDC_DEFAULT):
        return HDC_DEFAULT
    found = None
    for base in (os.environ.get('DEVECO_SDK_HOME', ''), os.environ.get('HOS_SDK_HOME', '')):
        cand = os.path.join(base, 'default', 'openharmony', 'toolchains', 'hdc.exe')
        if base and os.path.isfile(cand):
            found = cand
            break
    if not found:
        sys.exit('measure: hdc.exe not found; pass --hdc')
    return found


def read_log(hdc, pid=None):
    """The dmhost hilog as text. `-x` prints the whole buffer rather than following it."""
    cmd = [hdc, 'shell', 'hilog', '-x', '-T', TAG]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
    return p.stdout or ''


def pid_of(hdc):
    p = subprocess.run([hdc, 'shell', 'pidof', BUNDLE], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=30)
    return p.stdout.strip()


def parse(text):
    """The last occurrence of each counter line: the freshest cumulative sample."""
    out = {}
    for m in RE_SETS.finditer(text):
        out['sets'] = dict(frame=int(m.group(1)), reused=int(m.group(2)), new=int(m.group(3)),
                           hash=float(m.group(4)), collect=float(m.group(5)), allocw=float(m.group(6)))
    for m in RE_SPLIT.finditer(text):
        out['split'] = dict(memo=float(m.group(1)), collect=float(m.group(2)),
                            hash=float(m.group(3)), allocw=float(m.group(4)), bind=float(m.group(5)))
    for m in RE_TIMING.finditer(text):
        out['timing'] = dict(frame=int(m.group(1)), frame_ms=float(m.group(2)), gpu_ms=float(m.group(3)))
    replay = [(int(m.group(1)), float(m.group(2)), float(m.group(3))) for m in RE_REPLAY.finditer(text)]
    if replay:
        out['replay'] = replay
    return out


def take(hdc, quiet=False):
    """One sample: the counters plus the p50s of the replay samples seen since the previous take."""
    text = read_log(hdc)
    return parse(text)


def delta(a, b, gap):
    """Per-frame costs between two samples `gap` frames apart, or None when the counters did not move as asked."""
    if 'sets' not in a or 'sets' not in b:
        return None
    frames = b['sets']['frame'] - a['sets']['frame']
    if frames <= 0:
        return None
    d = {'frames': frames}
    for key, name in (('reused', 'reused_sets'), ('new', 'new_sets')):
        d[name] = (b['sets'][key] - a['sets'][key]) / frames
    for key, name in (('hash', 'hash_ms'), ('collect', 'collect_ms'), ('allocw', 'allocw_ms')):
        d[name] = (b['sets'][key] - a['sets'][key]) / frames
    if 'split' in a and 'split' in b:
        d['memo_ms'] = (b['split']['memo'] - a['split']['memo']) / frames
        d['split_collect_ms'] = (b['split']['collect'] - a['split']['collect']) / frames
        d['bind_ms'] = (b['split']['bind'] - a['split']['bind']) / frames
    # p50 of the per-frame replay samples inside the window, which is not a counter delta but a distribution
    if 'replay' in b:
        win = [(f, r, s) for f, r, s in b['replay'] if f > a['sets']['frame']]
        if win:
            d['replay_ms'] = statistics.median(r for _, r, _ in win)
            d['sets_ms'] = statistics.median(s for _, _, s in win)
            d['replay_n'] = len(win)
    if 'timing' in b:
        d['frame_ms'] = b['timing']['frame_ms']
        d['gpu_ms'] = b['timing']['gpu_ms']
    return d


def main(argv=None):
    ap = argparse.ArgumentParser(description='Per-frame cost from the port counters, same window, same scene.')
    ap.add_argument('--hdc', help='hdc.exe path (default: DevEco SDK discovery)')
    ap.add_argument('--samples', type=int, default=3, help='sample pairs to take (default: %(default)s)')
    ap.add_argument('--gap', type=int, default=20, help='frames between the two samples of a pair (default: %(default)s)')
    ap.add_argument('--scene', default='', help='label for the verdict (default: none)')
    ap.add_argument('--json', help='write the result here')
    a = ap.parse_args(argv)

    hdc = hdc_path(a.hdc)
    pid = pid_of(hdc)
    if not pid:
        sys.exit('measure: %s is not running; start it and enter the scene first' % BUNDLE)
    print('measure: pid %s, %d pairs %d frames apart' % (pid, a.samples, a.gap))

    rows = []
    for i in range(a.samples):
        first = take(hdc)
        if 'sets' not in first:
            sys.exit('measure: no "sets (present ...)" counter line; is DM_VK_PROF_SLOW=1 set?')
        # Wait for the counter to advance by at least the gap rather than sleeping a guessed time.
        deadline = time.time() + 120
        second = None
        while time.time() < deadline:
            time.sleep(2)
            cur = take(hdc)
            if 'sets' in cur and cur['sets']['frame'] - first['sets']['frame'] >= a.gap:
                second = cur
                break
        if second is None:
            print('  pair %d: no progress of %d frames in 120 s (scene idle or game paused?)' % (i + 1, a.gap))
            continue
        d = delta(first, second, a.gap)
        if d:
            rows.append(d)
            print('  pair %d: %d frames  frame %.1f ms  gpu %.1f ms  replay %.1f ms  sets %.1f ms'
                  % (i + 1, d['frames'], d.get('frame_ms', 0), d.get('gpu_ms', 0),
                     d.get('replay_ms', 0), d.get('sets_ms', 0)))

    if not rows:
        sys.exit('measure: no usable pair; nothing to report')

    def med(key):
        vals = [r[key] for r in rows if key in r]
        return round(statistics.median(vals), 3) if vals else None

    summary = {'scene': a.scene, 'pairs': len(rows)}
    for key in ('frames', 'frame_ms', 'gpu_ms', 'replay_ms', 'sets_ms', 'memo_ms', 'split_collect_ms',
                'hash_ms', 'allocw_ms', 'bind_ms', 'new_sets', 'reused_sets'):
        v = med(key)
        if v is not None:
            summary[key] = v

    print()
    print('median over %d pairs%s:' % (len(rows), (' (%s)' % a.scene) if a.scene else ''))
    for key in ('frame_ms', 'gpu_ms', 'replay_ms', 'sets_ms', 'memo_ms', 'split_collect_ms',
                'hash_ms', 'allocw_ms', 'new_sets', 'reused_sets'):
        if key in summary:
            unit = '' if key.endswith('sets') else ' ms'
            print('  %-18s %10.2f%s' % (key, summary[key], unit))
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump({'summary': summary, 'pairs': rows}, f, indent=2)
        print('verdict: %s' % a.json)
    return 0


if __name__ == '__main__':
    sys.exit(main())
