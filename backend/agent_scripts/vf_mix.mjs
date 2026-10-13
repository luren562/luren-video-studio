#!/usr/bin/env node
// Mix dry narration with optional ducked music. Supply SFX in the Remotion timeline.
import {spawnSync} from 'node:child_process';
import {parseArgs} from 'node:util';
import {mkdirSync} from 'node:fs';
import {dirname} from 'node:path';

try {
  const {values} = parseArgs({options: {
    narration: {type: 'string'}, bgm: {type: 'string'}, out: {type: 'string'},
    'bgm-enabled': {type: 'string', default: process.env.VF_BGM_ENABLED || 'true'},
  }});
  if (!values.narration || !values.out) throw new Error('用法：--narration <mp3> [--bgm <mp3>] --out <wav>');
  const useBgm = values['bgm-enabled'] !== 'false' && process.env.VF_BGM_ENABLED !== 'false' && values.bgm;
  const args = ['-hide_banner', '-loglevel', 'error', '-y', '-i', values.narration];
  if (useBgm) args.push('-stream_loop', '-1', '-i', values.bgm, '-filter_complex',
    '[0:a]asplit=2[voice][side];[1:a]volume=0.15[music];[music][side]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=300[ducked];[voice][ducked]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[mix]', '-map', '[mix]');
  else args.push('-map', '0:a:0');
  args.push(values.out);
  mkdirSync(dirname(values.out), {recursive: true});
  const result = spawnSync(process.env.FFMPEG_BINARY || 'ffmpeg', args, {stdio: 'inherit', windowsHide: true});
  if (result.error) throw result.error;
  process.exitCode = result.status ?? 1;
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
