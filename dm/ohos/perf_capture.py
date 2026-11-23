#!/usr/bin/env python3
"""Measure one running game on the device and write its perf record as JSON.

Why this exists next to dm/ohos/measure.py: that tool needs DM_VK_PROF_SLOW=1 for its "sets (present ...)" counter
line and aborts without it, while the frame-time line (`timing up to frame N: frame time p50 X / p95 Y / max Z`) and
the per-second `fps:` line are always in hilog. This reads those two, which is every number the library shows, and
writes the same schema the app's own sampler uses so one reader handles both.

Usage:
    python dm/ohos/perf_capture.py --scene shrine --out perf.json [--seconds 20] [--json-line]

Fields written (schema 1, matching GamePerf.ets):
    titleId, source, scene, device{model,api,width,height},
    fpsP50, frameMsP50, frameMsP95, frameMsMax, gpuMsP50, replayMsP50, setsMsP50,
    slowPct, frames, capturedAt, appVersion
A field with no evidence is -1, never 0: a missing measurement must not read as a good one.
"""
import argparse, json, re, subprocess, sys, time
from datetime import datetime, timezone, timedelta

HDC_DEFAULT = r'E:\Program Files\Huawei\DevEco Studio\sdk\default\openharmony\toolchains\hdc.exe'
BUNDLE = 'dev.eden_emu.ohos'

RE_TIMING = re.compile(r'timing up to frame (\d+): frame time p50 ([\d.]+) / p95 ([\d.]+) / max ([\d.]+) ms')
RE_FPS = re.compile(r'fps: (\d+) frames/s, avg ([\d.]+) ms, max ([\d.]+) ms, (\d+) slow \(>33\.3 ms\)')
RE_GPU = re.compile(r'GPU p50 ([\d.]+)')
RE_REPLAY = re.compile(r'replay p50 ([\d.]+)')
RE_SETS = re.compile(r'sets \(present [^)]*\) p50 ([\d.]+)')


def hdc_run(hdc, args, timeout=60):
    """Run one hdc command and return stdout as text ('' on failure).

    `hilog -x` never exits on its own: it keeps the session open and streams whatever arrives next, so a plain
    `subprocess.run` waits for the timeout and then loses the buffer it had already printed. On a timeout this
    kills the child and keeps what it wrote — that is the whole point of reading a live log.
    """
    try:
        p = subprocess.Popen([hdc] + args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, encoding='utf-8', errors='replace')
    except OSError:
        return ''
    try:
        out, _ = p.communicate(timeout=timeout)
        return out or ''
    except subprocess.TimeoutExpired:
        p.kill()
        try:
            out, _ = p.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            return ''
        return out or ''


def device_info(hdc):
    """The device model and screen, from the properties and the display service.

    `wm size` does not exist on this image (measured: `/bin/sh: wm: inaccessible or not found`), so the resolution
    comes from RenderService's own dump, which reports `render resolution=WxH` (here 1260x2844 — portrait, the
    panel's native orientation, not the landscape the games draw in).
    """
    model = ''
    for prop in ('const.product.model', 'const.product.marketname', 'const.product.name'):
        out = hdc_run(hdc, ['shell', 'param', 'get', prop]).strip()
        if out and out != prop:
            model = out
            break
    w = h = 0
    dump = hdc_run(hdc, ['shell', 'hidumper', '-s', 'RenderService', '-a', 'screen'], timeout=90)
    m = re.search(r'render resolution=(\d+)x(\d+)', dump)
    if m:
        w, h = int(m.group(1)), int(m.group(2))
    api = hdc_run(hdc, ['shell', 'param', 'get', 'const.ohos.apiversion']).strip()
    return {'model': model or 'unknown', 'api': api or '', 'width': w, 'height': h}


def app_version(hdc):
    """The bundle's versionName as installed, or ''."""
    out = hdc_run(hdc, ['shell', 'bm', 'dump', '-n', BUNDLE], timeout=90)
    m = re.search(r'"versionName":\s*"([^"]*)"', out)
    return m.group(1) if m else ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hdc', default=HDC_DEFAULT)
    ap.add_argument('--scene', default='', help='label for where the game was when measured (shrine, title, field)')
    ap.add_argument('--out', required=True, help='the perf.json to write')
    ap.add_argument('--seconds', type=float, default=15.0, help='how long to watch hilog')
    ap.add_argument('--title', default='', help='title ID; taken from the running game when omitted')
    ap.add_argument('--json-line', action='store_true', help='also print the record on one line')
    a = ap.parse_args()

    pid = hdc_run(a.hdc, ['shell', 'pidof', BUNDLE]).strip()
    if not pid:
        sys.exit('perf_capture: %s is not running; start a game first' % BUNDLE)

    # hilog -x dumps the buffer and exits, so a fresh call sees what the game has logged so far; the counters are
    # cumulative (frame numbers only grow), so the last line of each kind is the newest measurement.
    # No shell redirection in the argv: `subprocess` runs it without a shell, so `2>/dev/null` would be passed to
    # hilog as a literal argument (that is why an earlier version parsed nothing).
    deadline = time.time() + a.seconds
    timing = None
    fps_samples = []
    gpu = replay = sets = None
    while time.time() < deadline:
        out = hdc_run(a.hdc, ['shell', 'hilog', '-x'], timeout=180)
        for line in out.splitlines():
            if 'dmhost' not in line:
                continue
            m = RE_TIMING.search(line)
            if m:
                timing = {'frame': int(m.group(1)), 'p50': float(m.group(2)),
                          'p95': float(m.group(3)), 'max': float(m.group(4))}
            m = RE_FPS.search(line)
            if m:
                fps_samples.append({'fps': int(m.group(1)), 'avgMs': float(m.group(2)),
                                    'maxMs': float(m.group(3)), 'slow': int(m.group(4))})
            m = RE_GPU.search(line)
            if m:
                gpu = float(m.group(1))
            m = RE_REPLAY.search(line)
            if m:
                replay = float(m.group(1))
            m = RE_SETS.search(line)
            if m:
                sets = float(m.group(1))
        if timing and len(fps_samples) >= 5:
            break
        time.sleep(2.0)

    if not timing and not fps_samples:
        sys.exit('perf_capture: no frame counters in hilog; is a game actually rendering?')

    # fpsP50: the median of the per-second lines, which is what a player sees across a run rather than one second
    fps_p50 = -1.0
    if fps_samples:
        vals = sorted(s['fps'] for s in fps_samples)
        fps_p50 = float(vals[len(vals) // 2])
    slow_pct = -1.0
    if fps_samples:
        slow = sum(s['slow'] for s in fps_samples)
        frames = sum(s['fps'] for s in fps_samples)
        if frames > 0:
            slow_pct = round(100.0 * slow / frames, 1)

    rec = {
        'schema': 1,
        'titleId': a.title,
        'source': 'device',
        'scene': a.scene,
        'device': device_info(a.hdc),
        'fpsP50': fps_p50,
        'frameMsP50': timing['p50'] if timing else -1.0,
        'frameMsP95': timing['p95'] if timing else -1.0,
        'frameMsMax': timing['max'] if timing else -1.0,
        'gpuMsP50': gpu if gpu is not None else -1.0,
        'replayMsP50': replay if replay is not None else -1.0,
        'setsMsP50': sets if sets is not None else -1.0,
        'slowPct': slow_pct,
        'frames': timing['frame'] if timing else -1,
        'capturedAt': datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),
        'appVersion': app_version(a.hdc),
    }
    with open(a.out, 'w', encoding='utf-8') as f:
        json.dump(rec, f, indent=2, ensure_ascii=False)
    print('perf_capture: %s' % a.out)
    print('  scene %s  device %s  %dx%d' % (rec['scene'], rec['device']['model'],
                                            rec['device']['width'], rec['device']['height']))
    print('  fpsP50 %s   frameMs p50 %s / p95 %s / max %s   slow %s%%'
          % (rec['fpsP50'], rec['frameMsP50'], rec['frameMsP95'], rec['frameMsMax'], rec['slowPct']))
    print('  gpu %s  replay %s  sets %s  frames %s'
          % (rec['gpuMsP50'], rec['replayMsP50'], rec['setsMsP50'], rec['frames']))
    if a.json_line:
        print(json.dumps(rec, ensure_ascii=False))


if __name__ == '__main__':
    main()
