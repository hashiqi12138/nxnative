/*
 * GamePerf.ets - a game's measured performance, as the library shows it.
 *
 * The record lives beside the game, in <filesDir>/games/<titleId>/perf.json, written by dm/ohos/perf_capture.py (or
 * by the app's own sampler later). It sits in the game's root rather than in mods/, RomFS/ or aoc/ on purpose:
 * PackImport.ets clears exactly those three folders when a pack is re-imported, so a measurement survives a data
 * update.
 *
 * A field the capture could not measure is -1, never 0: 0 would read as "perfect", and the UI must say "not
 * measured" instead. `bestFor` picks the sample for the device in hand, so a library carried between phones shows the
 * number that applies to this one.
 */

import { fileIo as fs } from '@kit.CoreFileKit';
import dmhost from 'libdmhost.so';

/** One measurement of one scene on one device. Schema 1, matching dm/ohos/perf_capture.py. */
export interface PerfRecord {
  /** 1. A newer schema gets its own reader rather than being misread. */
  schema: number;
  /** The 16-hex title ID this was measured on. */
  titleId: string;
  /** 'device' for a run captured on hardware. */
  source: string;
  /** Where the game was: 'title', 'shrine', 'field', ... Empty when the capture did not say. */
  scene: string;
  deviceModel: string;
  deviceApi: string;
  deviceWidth: number;
  deviceHeight: number;
  /** Frames per second, median of the per-second samples. -1 when unknown. */
  fpsP50: number;
  /** Frame time in ms: p50, p95 and max. -1 when unknown. */
  frameMsP50: number;
  frameMsP95: number;
  frameMsMax: number;
  /** GPU timestamp span, median. -1 when unknown. */
  gpuMsP50: number;
  /** Replay-thread time, median. -1 when unknown. */
  replayMsP50: number;
  /** Stage-set time, median. -1 when unknown. */
  setsMsP50: number;
  /** Percentage of frames slower than 33.3 ms. -1 when unknown. */
  slowPct: number;
  /** The frame counter the timing line reported, so a stale sample is recognisable. -1 when unknown. */
  frames: number;
  /** ISO-8601 local time of the capture. */
  capturedAt: string;
  appVersion: string;
}

/** The file a game's measurements live in, relative to its root. */
export const PERF_FILE: string = '/perf.json';

/** Read one number, keeping -1 for anything absent so "not measured" never becomes 0. */
function num(o: Record<string, Object>, key: string): number {
  const v = o[key];
  return typeof v === 'number' ? v as number : -1;
}

/** Read one string, '' for anything absent. */
function str(o: Record<string, Object>, key: string): string {
  const v = o[key];
  return typeof v === 'string' ? v as string : '';
}

/** Parse one record, or null when the shape is not one this reader understands. */
function parseRecord(o: Record<string, Object>): PerfRecord | null {
  const schema = num(o, 'schema');
  if (schema !== 1) return null;   // a future schema is not guessed at
  const dev = o['device'];
  const d: Record<string, Object> = (typeof dev === 'object' && dev !== null)
    ? dev as Record<string, Object> : {};
  return {
    schema: 1,
    titleId: str(o, 'titleId'),
    source: str(o, 'source'),
    scene: str(o, 'scene'),
    deviceModel: str(d, 'model'),
    deviceApi: str(d, 'api'),
    deviceWidth: num(d, 'width'),
    deviceHeight: num(d, 'height'),
    fpsP50: num(o, 'fpsP50'),
    frameMsP50: num(o, 'frameMsP50'),
    frameMsP95: num(o, 'frameMsP95'),
    frameMsMax: num(o, 'frameMsMax'),
    gpuMsP50: num(o, 'gpuMsP50'),
    replayMsP50: num(o, 'replayMsP50'),
    setsMsP50: num(o, 'setsMsP50'),
    slowPct: num(o, 'slowPct'),
    frames: num(o, 'frames'),
    capturedAt: str(o, 'capturedAt'),
    appVersion: str(o, 'appVersion')
  };
}

/**
 * Read a game's measurements. The file holds one record; a list is accepted too, so several scenes can be collected
 * without changing the format. An unreadable or unknown file yields []: a game with no measurement is normal, not an
 * error, and the UI says "not measured".
 */
export function readPerf(root: string): PerfRecord[] {
  let text: string = '';
  try {
    text = fs.readTextSync(root + PERF_FILE);
  } catch (e) {
    return [];
  }
  let parsed: object | null = null;
  try {
    parsed = JSON.parse(text) as object;
  } catch (e) {
    return [];
  }
  if (Array.isArray(parsed)) {
    const out: PerfRecord[] = [];
    for (const item of parsed as object[]) {
      const r = parseRecord(item as Record<string, Object>);
      if (r !== null) out.push(r);
    }
    return out;
  }
  const one = parseRecord(parsed as Record<string, Object>);
  if (one === null) {
    // The file is there but did not parse into a record. Say why once per call: a silent [] is indistinguishable
    // from "never measured", which is exactly the wrong reading when a measurement exists (hit on 2026-11-23:
    // perf.json was on disk with schema 1 and the card still showed no badge).
    const o = parsed as Record<string, Object>;
    dmhost.log(`perf: ${root}${PERF_FILE} did not parse (schema=${num(o, 'schema')}, fpsP50=${num(o, 'fpsP50')})`);
    return [];
  }
  return [one];
}/**
 * The sample to show for a device: an exact model match first, then any sample (a library carried between phones
 * should still show something rather than nothing). Null when the game has never been measured.
 */
export function bestFor(list: PerfRecord[], model: string): PerfRecord | null {
  if (list.length === 0) return null;
  for (const r of list) {
    if (model.length > 0 && r.deviceModel === model) return r;
  }
  return list[0];
}

/**
 * The one-line performance label for a card, or '' when there is nothing to say.
 *
 * Deliberately terse: a card has room for a badge, and "60 fps" is the whole message. The scene and the frame times
 * belong to the detail sheet, where there is space to be precise.
 */
export function perfBadge(r: PerfRecord | null): string {
  if (r === null || r.fpsP50 < 0) return '';
  return `${Math.round(r.fpsP50)} fps`;
}

/**
 * The severity of a measured frame rate, for the badge colour.
 * 'good' at 55 fps and up, 'fair' from 30, 'poor' below that, and 'none' when nothing was measured.
 */
export function perfGrade(r: PerfRecord | null): string {
  if (r === null || r.fpsP50 < 0) return 'none';
  if (r.fpsP50 >= 55) return 'good';
  if (r.fpsP50 >= 30) return 'fair';
  return 'poor';
}

/** A measurement as a number with one decimal, or '未测' when it was not measured. */
export function ms(v: number): string {
  return v < 0 ? '未测' : `${v.toFixed(2)} ms`;
}

/** A percentage with one decimal, or '未测'. */
export function pct(v: number): string {
  return v < 0 ? '未测' : `${v.toFixed(1)}%`;
}

/** The scene as a player-facing label; '' becomes a neutral word rather than an empty cell. */
export function sceneLabel(r: PerfRecord): string {
  const s: string = r.scene;
  if (s.length === 0) return '未标注';
  if (s === 'title') return '标题画面';
  if (s === 'shrine') return '神庙';
  if (s === 'field') return '野外';
  if (s === 'menu') return '菜单';
  return s;
}
