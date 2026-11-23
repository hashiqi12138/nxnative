#!/usr/bin/env python3
"""Put a measured perf record where the app reads it: <filesDir>/games/<titleId>/perf.json.

The app's own sandbox is not writable from the shell domain (SELinux: `debug_hap_data_file`, the same boundary that
made the pack travel over HTTP), so this cannot simply `hdc file send` into it. Two routes work, and this tool takes
the second:

  1. Serve it from the pack server and let the app pull it — the pack route, which needs a `.nxpk` rebuild.
  2. Have the app write it itself: this tool stages the record at a path the app can read, and the app's next scan
     picks it up. Until that app-side reader exists, the record is kept beside the pack so `pack_game.py` can ship it
     inside the next `.nxpk` (the manifest member rides at the head of the tar, so it costs no extra pass).

What this tool does today, and why it is still useful: it validates the record against the schema the app parses
(GamePerf.ets `parseRecord`) and stages it into a pack directory, so a repack carries the measurement and the
library shows it after the next import. Fields the capture could not measure stay -1.

Usage:
    python dm/ohos/perf_stage.py --perf perf.json --pack <porter pack dir> [--title <id>]
    python dm/ohos/perf_stage.py --check perf.json        # validate only
"""
import argparse, json, shutil, sys
from pathlib import Path

# The fields GamePerf.ets reads, with the type each must have. A record missing one is refused rather than shipped:
# the app would read the absent field as -1 and silently show "not measured" for something that was measured.
NUM_FIELDS = ('schema', 'fpsP50', 'frameMsP50', 'frameMsP95', 'frameMsMax',
              'gpuMsP50', 'replayMsP50', 'setsMsP50', 'slowPct', 'frames')
STR_FIELDS = ('titleId', 'source', 'scene', 'capturedAt', 'appVersion')
DEV_NUM = ('width', 'height')
DEV_STR = ('model', 'api')


def check(rec):
    """Return the list of problems with one record ([] when it is shippable)."""
    bad = []
    if not isinstance(rec, dict):
        return ['record is not an object']
    if rec.get('schema') != 1:
        bad.append('schema must be 1 (got %r)' % (rec.get('schema'),))
    for k in NUM_FIELDS:
        if not isinstance(rec.get(k), (int, float)):
            bad.append('%s must be a number (got %r)' % (k, rec.get(k)))
    for k in STR_FIELDS:
        if not isinstance(rec.get(k), str):
            bad.append('%s must be a string (got %r)' % (k, rec.get(k)))
    dev = rec.get('device')
    if not isinstance(dev, dict):
        bad.append('device must be an object')
    else:
        for k in DEV_NUM:
            if not isinstance(dev.get(k), (int, float)):
                bad.append('device.%s must be a number (got %r)' % (k, dev.get(k)))
        for k in DEV_STR:
            if not isinstance(dev.get(k), str):
                bad.append('device.%s must be a string (got %r)' % (k, dev.get(k)))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--perf', required=True, help='the record perf_capture.py wrote')
    ap.add_argument('--pack', help='a porter pack dir to stage perf.json into')
    ap.add_argument('--title', help='title ID to assert against the record')
    ap.add_argument('--check', action='store_true', help='validate only, do not stage')
    a = ap.parse_args()

    rec = json.loads(Path(a.perf).read_text(encoding='utf-8'))
    bad = check(rec)
    if bad:
        print('perf_stage: %s does not match the app schema:' % a.perf)
        for b in bad:
            print('  - %s' % b)
        sys.exit(1)
    print('perf_stage: %s is valid (schema 1)' % a.perf)
    print('  title %s  scene %s  fps %s  frameMs p50 %s' % (
        rec['titleId'], rec['scene'], rec['fpsP50'], rec['frameMsP50']))
    if a.title and rec['titleId'] and a.title != rec['titleId']:
        sys.exit('perf_stage: --title %s does not match the record\'s %s' % (a.title, rec['titleId']))
    if a.check or not a.pack:
        return
    pack = Path(a.pack)
    if not (pack / 'nx2a-data.json').is_file():
        sys.exit('perf_stage: %s has no nx2a-data.json, so it is not a pack dir' % pack)
    dst = pack / 'perf.json'
    shutil.copyfile(a.perf, dst)
    print('perf_stage: staged %s (%d bytes)' % (dst, dst.stat().st_size))
    print('  the next pack_game.py run carries it; the library reads <root>/perf.json after the import')


if __name__ == '__main__':
    main()
