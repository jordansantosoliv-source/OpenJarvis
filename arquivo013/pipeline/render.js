// Renderiza quadros de um episódio.
// node pipeline/render.js <ep_dir> <timeline.json> <out_dir> range <ini> <fim>   -> JPEG f_00000.jpg
// node pipeline/render.js <ep_dir> <timeline.json> <out_dir> preview <f1,f2,..>  -> PNG  p_00000.png
// node pipeline/render.js <ep_dir> <timeline.json> <out_dir> scenes <s3,s7>      -> JPEG só dessas cenas
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const [ep, tlp, out, mode, a, b] = process.argv.slice(2);
  const dir = path.resolve(ep);
  const TL = JSON.parse(fs.readFileSync(path.resolve(tlp), 'utf8'));
  let frames = [];
  if (mode === 'preview') frames = a.split(',').map(Number);
  else if (mode === 'range') { for (let f = +a; f < +b; f++) frames.push(f); }
  else if (mode === 'scenes') {
    const want = new Set(a.split(',')); let t = 0;
    for (const s of TL.scenes) {
      const f0 = Math.round(t * TL.fps), f1 = Math.round((t + s.dur) * TL.fps);
      if (want.has(s.id)) for (let f = f0; f < f1; f++) frames.push(f);
      t += s.dur;
    }
  } else throw new Error('modo: range | preview | scenes');
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto('file://' + path.join(dir, 'scene.html'));
  await page.evaluate(tl => { window.TL = tl; }, TL);
  await page.evaluate(async () => {
    await Promise.all(['400 40px "Bebas Neue"', '600 40px "Oswald"', '700 40px "Oswald"', '700 40px "Courier Prime"', '400 40px "Special Elite"'].map(f => document.fonts.load(f)));
    await document.fonts.ready;
    await Promise.all([...document.images].map(i => i.complete ? 1 : new Promise(r => { i.onload = r; i.onerror = r; })));
  });
  const nf = await page.evaluate(() => [...document.fonts].filter(f => f.status === 'loaded').length);
  if (nf < 5) errors.push(`fontes carregadas: ${nf}/5`);
  fs.mkdirSync(out, { recursive: true });
  const t0 = Date.now();
  for (const f of frames) {
    await page.evaluate(fr => window.renderFrame(fr), f);
    const png = mode === 'preview';
    await page.screenshot({ path: path.join(out, `${png ? 'p' : 'f'}_${String(f).padStart(5, '0')}.${png ? 'png' : 'jpg'}`), type: png ? 'png' : 'jpeg', ...(png ? {} : { quality: 92 }) });
  }
  console.log(JSON.stringify({ frames: frames.length, s: Math.round((Date.now() - t0) / 1000), errors: errors.slice(0, 3) }));
  await browser.close();
  if (errors.length) process.exit(1);
})();
