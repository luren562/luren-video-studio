#!/usr/bin/env node
// Thin wrapper: talkcraft 成品配音复用平台 Python 运行时（providers/cache 同源）。
import {spawnSync} from 'node:child_process';

const python = process.env.VF_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const result = spawnSync(python, ['-m', 'app.speak_cli', ...process.argv.slice(2)], {
  stdio: 'inherit', windowsHide: true, env: {...process.env, PYTHONIOENCODING: 'utf-8'},
});
if (result.error) console.error('口播配音运行环境不可用：', result.error.message);
process.exit(result.status ?? 1);
