// usage: node render.js <dir> preview <frame,frame,...>   |   node render.js <dir> range <start> <end>
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const dir = path.resolve(process.argv[2]);
  const mode = process.argv[3];
  const TL = JSON.parse(fs.readFileSync(path.join(dir, 'timeline.json'), 'utf8'));
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto('file://' + path.join(dir, 'scene.html'));
  await page.evaluate(tl => { window.TL = tl; }, TL);
  await page.evaluate(async () => {
    await Promise.all([
      document.fonts.load('400 40px "Bebas Neue"'), document.fonts.load('600 40px "Oswald"'),
      document.fonts.load('700 40px "Oswald"'), document.fonts.load('700 40px "Courier Prime"'),
      document.fonts.load('400 40px "Special Elite"')]);
    await document.fonts.ready;
    await Promise.all([...document.images].map(i => i.complete ? 1 : new Promise(r => { i.onload = r; i.onerror = r; })));
  });
  const fonts = await page.evaluate(() => [...document.fonts].filter(f => f.status === 'loaded').map(f => f.family + ' ' + f.weight));
  let frames = [];
  if (mode === 'preview') frames = process.argv[4].split(',').map(Number);
  else { const s = +process.argv[4], e = +process.argv[5]; for (let f = s; f < e; f++) frames.push(f); }
  const out = path.join(dir, mode === 'preview' ? 'preview' : 'frames');
  fs.mkdirSync(out, { recursive: true });
  const t0 = Date.now();
  for (const f of frames) {
    await page.evaluate(fr => window.renderFrame(fr), f);
    const name = mode === 'preview' ? `p_${String(f).padStart(5, '0')}.png` : `f_${String(f).padStart(5, '0')}.jpg`;
    await page.screenshot({ path: path.join(out, name), type: mode === 'preview' ? 'png' : 'jpeg', ...(mode === 'preview' ? {} : { quality: 92 }) });
  }
  console.log(JSON.stringify({ frames: frames.length, ms: Date.now() - t0, fonts, errors: errors.slice(0, 5) }));
  await browser.close();
})();
