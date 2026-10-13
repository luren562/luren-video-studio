// Fixed platform verification. No model-supplied scripts or executable options.
const fs = require('fs');
const path = require('path');
const [modules, workspace, entry, id, reportPath, bundleDir, scaleArg, samplingPath] = process.argv.slice(2);
const {bundle} = require(path.join(modules, '@remotion/bundler'));
const {getCompositions, renderStill, openBrowser} = require(path.join(modules, '@remotion/renderer'));
const settleOffset = (duration, ratio = 0.9, margin = 2) => duration <= 1 ? 0 :
  Math.min(Math.max(1, Math.round(duration * ratio)), Math.max(1, duration - 1 - margin));
(async () => {
  let browser;
  let bundleCached = false;
  const warnings = [];
  try {
    const plan = JSON.parse(fs.readFileSync(path.join(workspace, 'PLAN.json'), 'utf8'));
    const sampling = samplingPath ? JSON.parse(fs.readFileSync(samplingPath, 'utf8')).scenes : null;
    const scale = scaleArg === undefined ? 1 : Number(scaleArg);
    if (!Number.isFinite(scale) || scale <= 0 || scale > 1) throw new Error('scale must be in (0, 1]');
    const outDir = bundleDir || path.join(path.dirname(reportPath), 'bundle');
    const entryStamp = path.join(outDir, '.agent-entry.json');
    const entryPoint = path.resolve(workspace, entry);
    let savedEntry;
    try { savedEntry = JSON.parse(fs.readFileSync(entryStamp, 'utf8')).entry; } catch {}
    // index.html is installed last, so an interrupted build cannot become a cache hit.
    bundleCached = Boolean(bundleDir && savedEntry === entryPoint && fs.existsSync(path.join(outDir, 'index.html')));
    let serveUrl = outDir;
    if (!bundleCached) {
      const staging = path.join(path.dirname(reportPath), 'bundle-build');
      await bundle({entryPoint, outDir: staging,
        publicDir: path.join(workspace, 'public')});
      fs.mkdirSync(outDir, {recursive: true});
      fs.rmSync(path.join(outDir, 'index.html'), {force: true});
      for (const name of fs.readdirSync(staging).filter(name => name !== 'index.html')) {
        fs.cpSync(path.join(staging, name), path.join(outDir, name), {recursive: true, force: true});
      }
      fs.writeFileSync(entryStamp, JSON.stringify({entry: entryPoint}));
      fs.copyFileSync(path.join(staging, 'index.html'), path.join(outDir, 'index.html'));
      // The staging path is a fixed child of this platform-created report directory.
      fs.rmSync(staging, {recursive: true, force: true});
    }
    fs.utimesSync(outDir, new Date(), new Date());
    browser = await openBrowser('chrome', {logLevel: 'error'});
    const compositions = await getCompositions(serveUrl, {puppeteerInstance: browser, logLevel: 'error'});
    const composition = compositions.find(c => c.id === id);
    if (!composition) throw new Error(`Composition ${id} does not exist`);
    const coverage = [], stills = [], samples = [];
    for (const [index, timing] of plan.timeline.scenes.entries()) {
      const sample = sampling ? sampling[index] : timing;
      if (!sample || sample.start !== timing.start || sample.duration !== timing.duration) {
        throw new Error(`Scene ${index + 1} sampling does not match frozen timing`);
      }
      const settle = Number.isInteger(sample.settle) ? sample.settle : settleOffset(timing.duration);
      if (settle < 0 || settle >= timing.duration) throw new Error('Invalid settle offset');
      let frame = timing.start + settle;
      let kind = 'settle';
      const observed = [];
      const output = path.join(path.dirname(reportPath), `scene-${index + 1}.png`);
      const draw = async () => {
        observed.length = 0;
        await renderStill({serveUrl, composition, output, frame, scale,
          puppeteerInstance: browser, logLevel: 'error',
          onBrowserLog: log => {
            if (log.text.startsWith('AGENT_SCENE:')) {
              try { observed.push(JSON.parse(log.text.slice('AGENT_SCENE:'.length))); } catch {}
            }
          }});
      };
      try {
        await draw();
      } catch (error) {
        const failedFrame = frame;
        frame = timing.start + Math.floor(timing.duration / 2);
        kind = 'settle_fallback';
        warnings.push({scene_index: index, settle_frame: failedFrame, fallback_frame: frame, error: String(error)});
        await draw(); // A failed fallback remains a failed check, never skip this scene.
      }
      if (!observed.some(s => s.index === index && s.start === timing.start &&
          s.duration === timing.duration && s.frame === frame - timing.start && s.hasContent)) {
        throw new Error(`Scene ${index + 1} is not connected at frame ${frame}; wrap its content in <AgentScene index={${index}}>`);
      }
      coverage.push({index, start: timing.start, duration: timing.duration, sampled_frame: frame});
      stills.push(output);
      samples.push({scene_index: index, frame, kind});
    }
    fs.writeFileSync(reportPath, JSON.stringify({ok: true, coverage, stills, samples, warnings,
      bundle_cached: bundleCached, scale,
      composition: {id: composition.id, width: composition.width, height: composition.height,
                    fps: composition.fps, durationInFrames: composition.durationInFrames}}));
  } catch (error) {
    fs.writeFileSync(reportPath, JSON.stringify({ok: false, error: String(error), bundle_cached: bundleCached, warnings}));
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close({silent: true});
  }
})();
