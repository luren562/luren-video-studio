#!/usr/bin/env node
// Thin wrapper: use the platform Python runtime so providers/cache are shared.
import {spawnSync} from 'node:child_process';

const python = process.env.VF_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const result = spawnSync(python, ['-m', 'app.tts_cli', ...process.argv.slice(2)], {
  stdio: 'inherit', windowsHide: true, env: {...process.env, PYTHONIOENCODING: 'utf-8'},
});
if (result.error) console.error('配音运行环境不可用：', result.error.message);
process.exit(result.status ?? 1);
