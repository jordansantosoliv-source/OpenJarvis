/* ARQUIVO 013 — EP01 Máscaras de Chumbo. Deterministic frame renderer. */
const W = 1080, H = 1920;
const C = {
  ink: '#141414', g0: '#17171a', g1: '#222327', g2: '#2e2f34', g3: '#44454b', g4: '#6c6d74', g5: '#9a9ba2', g6: '#c3c4c8',
  red: '#7A1F1F', red2: '#a3302b', redD: '#3d1212', wood: '#3b2320', wood2: '#4d2e29',
  paper: '#E8DCC0', paper2: '#d5c6a2', paper3: '#b09d72', cork: '#9c8760', skin: '#d8c49b', skinS: '#a8916a', orange: '#e0742c'
};
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const ease = t => { t = clamp(t); return t * t * (3 - 2 * t); };
const lerp = (a, b, t) => a + (b - a) * t;
function rng(seed) {
  let s = ((seed + 1) * 2654435761) >>> 0 || 1;
  return () => { s ^= s << 13; s >>>= 0; s ^= s >>> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
}
const CAP = (id, i) => TL.scenes.find(s => s.id === id).caps[i][0];
const STK = `stroke="${C.ink}" stroke-linejoin="round" stroke-linecap="round"`;

function cam(lt, d, o = {}) {
  const { s0 = 1, s1 = 1.06, x0 = 0, y0 = 0, x1 = 0, y1 = 0, cx = 540, cy = 960 } = o;
  const k = clamp(lt / d);
  const s = lerp(s0, s1, k), x = lerp(x0, x1, k), y = lerp(y0, y1, k);
  return `translate(${cx + x} ${cy + y}) scale(${s}) translate(${-cx} ${-cy})`;
}

/* ---------- reusable pieces ---------- */
function cloud(x, y, w, fill, op) {
  return `<g fill="${fill}" opacity="${op}"><ellipse cx="${x}" cy="${y}" rx="${w * .5}" ry="${w * .13}"/>` +
    `<ellipse cx="${x - w * .22}" cy="${y - w * .05}" rx="${w * .24}" ry="${w * .11}"/>` +
    `<ellipse cx="${x + w * .18}" cy="${y - w * .08}" rx="${w * .26}" ry="${w * .14}"/>` +
    `<ellipse cx="${x + w * .02}" cy="${y - w * .13}" rx="${w * .18}" ry="${w * .11}"/></g>`;
}
function clouds(lt, seed, n, y0, y1, speed, fill, op) {
  const r = rng(seed); let o = '';
  for (let i = 0; i < n; i++) {
    const w = 260 + r() * 380, y = y0 + r() * (y1 - y0), xb = r() * (W + 800), sp = speed * (.6 + r() * .8);
    const x = ((xb + lt * sp) % (W + 800)) - 400;
    o += cloud(x, y, w, fill, op);
  }
  return o;
}
function rain(lt, n, op, seed, speed = 1600, sl = .25) {
  const r = rng(seed); let o = `<g stroke="${C.paper}" stroke-width="2.2" opacity="${op}" stroke-linecap="round">`;
  for (let i = 0; i < n; i++) {
    const x0 = r() * (W + sl * 2300) - 40, y0 = r() * 2300, L = 40 + r() * 55, sp = speed * (.8 + r() * .4);
    const y = ((y0 + lt * sp) % 2300) - 160, x = x0 - sl * y;
    o += `<line x1="${x.toFixed(1)}" y1="${y.toFixed(1)}" x2="${(x - sl * L).toFixed(1)}" y2="${(y + L).toFixed(1)}"/>`;
  }
  return o + '</g>';
}
function grass(lt, seed, n, x0, x1, yTop, yBot, col, sway = 4, topFn = null) {
  const r = rng(seed); let o = `<g stroke="${col}" stroke-width="3.2" stroke-linecap="round" fill="none">`;
  for (let i = 0; i < n; i++) {
    const x = x0 + r() * (x1 - x0);
    const ymin = topFn ? topFn(x) : yTop;
    const y = ymin + 6 + r() * (yBot - ymin);
    const h = 14 + r() * 26, lean = (r() - .5) * 14 + Math.sin(lt * 2 + x * .013) * sway;
    o += `<path d="M${x.toFixed(1)} ${y.toFixed(1)} q${(lean * .3).toFixed(1)} ${(-h * .6).toFixed(1)} ${lean.toFixed(1)} ${(-h).toFixed(1)}"/>`;
  }
  return o + '</g>';
}
function leadMask(x, y, rot, s) {
  return `<g transform="translate(${x} ${y}) rotate(${rot}) scale(${s})">
  <ellipse cx="8" cy="30" rx="142" ry="22" fill="#000" opacity=".5"/>
  <path d="M-128 -30 L-119 -45 L-62 -50 L-24 -38 L-9 -22 L9 -22 L24 -38 L62 -50 L119 -45 L128 -30 L126 8 L111 37 L69 46 L30 36 L14 12 L-14 12 L-30 36 L-69 46 L-111 37 L-126 8 Z" fill="${C.g4}" stroke="${C.ink}" stroke-width="5" stroke-linejoin="round"/>
  <path d="M-112 -36 L-64 -41 L-30 -29 M30 -29 L64 -41 L112 -36" fill="none" stroke="${C.g6}" stroke-width="5" opacity=".75" stroke-linecap="round"/>
  <path d="M-92 8 L-62 22 M70 -8 L96 6 M-42 -18 L-54 2 M40 20 L58 30" fill="none" stroke="${C.g2}" stroke-width="3" stroke-linecap="round"/>
  </g>`;
}
function agentBust(x, y, s, glint = 1) {
  return `<g transform="translate(${x} ${y}) scale(${s})" ${STK} stroke-width="6">
  <path d="M-58 118 C-150 132 -250 170 -300 280 L-330 780 L330 780 L300 280 C250 170 150 132 58 118 Z" fill="${C.g2}"/>
  <path d="M-300 300 L-322 760" fill="none" stroke="${C.red2}" stroke-width="5" opacity=".55"/>
  <path d="M-52 120 L0 300 L52 120 Z" fill="${C.paper}"/>
  <path d="M-15 132 L15 132 L11 160 L-11 160 Z" fill="${C.red}"/>
  <path d="M-11 160 L11 160 L24 285 L0 318 L-24 285 Z" fill="${C.red}"/>
  <path d="M-58 118 L-125 160 L-92 210 L-118 236 L-40 330 L0 300 L-52 120 Z" fill="${C.g3}"/>
  <path d="M58 118 L125 160 L92 210 L118 236 L40 330 L0 300 L52 120 Z" fill="${C.g3}"/>
  <path d="M-60 116 L-118 40 L-150 150 L-125 160 Z" fill="${C.g3}"/>
  <path d="M60 116 L118 40 L150 150 L125 160 Z" fill="${C.g3}"/>
  <circle cx="-150" cy="430" r="12" fill="${C.g1}"/><circle cx="150" cy="430" r="12" fill="${C.g1}"/>
  <circle cx="-165" cy="285" r="17" fill="${C.paper3}"/><circle cx="-165" cy="285" r="7" fill="none" stroke-width="3"/>
  <path d="M-40 70 L-44 128 L0 150 L44 128 L40 70 Z" fill="${C.skinS}"/>
  <path d="M-76 -40 C-80 40 -48 100 0 108 C48 100 80 40 76 -40 C70 -100 -70 -100 -76 -40 Z" fill="${C.skin}"/>
  <path d="M-80 -60 L80 -60 L78 4 C40 18 -40 18 -78 4 Z" fill="${C.g0}" stroke="none" opacity=".93"/>
  <ellipse cx="-30" cy="-16" rx="9" ry="3.5" fill="${C.paper}" stroke="none" opacity="${glint}"/>
  <ellipse cx="30" cy="-16" rx="9" ry="3.5" fill="${C.paper}" stroke="none" opacity="${glint}"/>
  <path d="M6 8 L16 46 L2 52" fill="none" stroke-width="5"/>
  <path d="M-22 76 L22 74" fill="none" stroke-width="5"/>
  <path d="M62 20 C66 58 48 90 18 104" fill="none" stroke="${C.skinS}" stroke-width="8"/>
  <path d="M-96 -76 C-104 -150 -72 -206 0 -210 C72 -206 104 -150 96 -76 Q0 -96 -96 -76 Z" fill="${C.g3}"/>
  <path d="M-34 -200 Q0 -168 34 -200" fill="none" stroke-width="5"/>
  <path d="M-98 -100 Q0 -120 98 -100 L96 -78 Q0 -98 -96 -78 Z" fill="${C.red}"/>
  <path d="M-160 -58 Q0 -98 160 -58 Q172 -40 122 -34 Q0 -52 -122 -34 Q-172 -40 -160 -58 Z" fill="${C.g3}"/>
  <path d="M-150 -56 Q0 -90 150 -56" fill="none" stroke="${C.g5}" stroke-width="3" opacity=".6"/>
  </g>`;
}
function agentBack(x, y, s) {
  return `<g transform="translate(${x} ${y}) scale(${s})" ${STK} stroke-width="6">
  <path d="M-70 120 C-170 140 -250 190 -280 300 L-300 950 L300 950 L280 300 C250 190 170 140 70 120 Z" fill="${C.g1}"/>
  <path d="M-286 560 L286 560 L284 610 L-288 610 Z" fill="${C.g2}"/>
  <path d="M-62 118 L-112 34 L-142 150 Z M62 118 L112 34 L142 150 Z" fill="${C.g1}"/>
  <path d="M-44 60 L-48 132 L48 132 L44 60 Z" fill="${C.skinS}"/>
  <path d="M-72 -40 C-76 30 -42 82 0 86 C42 82 76 30 72 -40 Z" fill="${C.g0}"/>
  <path d="M-96 -76 C-104 -150 -72 -206 0 -210 C72 -206 104 -150 96 -76 Q0 -96 -96 -76 Z" fill="${C.g2}"/>
  <path d="M-98 -100 Q0 -120 98 -100 L96 -78 Q0 -98 -96 -78 Z" fill="${C.red}"/>
  <path d="M-160 -58 Q0 -98 160 -58 Q172 -40 122 -34 Q0 -52 -122 -34 Q-172 -40 -160 -58 Z" fill="${C.g2}"/>
  <path d="M-282 300 L-300 940 M-150 -60 Q-100 -200 0 -208" fill="none" stroke="${C.red2}" stroke-width="5" opacity=".7"/>
  </g>`;
}
function walker(x, y, s, ph) {
  const sw = Math.sin(ph) * 12, fl = Math.sin(ph * 1.7) * 9;
  return `<g transform="translate(${x} ${y}) scale(${s})" ${STK} stroke-width="5">
  <path d="M-26 150 L${-30 + sw} 300 L${-8 + sw} 300 L-4 150 Z" fill="${C.g0}"/>
  <path d="M4 150 L${8 - sw} 300 L${30 - sw} 300 L26 150 Z" fill="${C.g0}"/>
  <path d="M-50 -10 C-60 60 -55 120 -45 170 L45 170 C55 120 60 60 50 -10 Q0 -30 -50 -10 Z" fill="${C.g1}"/>
  <path d="M-58 -14 Q0 -36 58 -14 L74 ${210 + fl} Q0 226 -74 ${210 - fl} Z" fill="${C.g5}" fill-opacity=".8"/>
  <path d="M0 -22 L0 214 M-30 40 L-42 200 M30 40 L44 200" fill="none" stroke="${C.g4}" stroke-width="3"/>
  <path d="M-12 -28 L12 -28 L10 -12 L-10 -12 Z" fill="${C.skinS}"/>
  <ellipse cx="0" cy="-60" rx="30" ry="36" fill="${C.g0}"/>
  <path d="M-58 -14 L-74 ${210 - fl}" fill="none" stroke="${C.red2}" stroke-width="4" opacity=".7"/>
  </g>`;
}
function woman(x, y, s) {
  return `<g transform="translate(${x} ${y}) scale(${s})" ${STK} stroke-width="6">
  <path d="M-90 40 C-120 60 -140 140 -150 300 L-190 760 L190 760 L150 300 C140 140 120 60 90 40 Q0 20 -90 40 Z" fill="${C.redD}"/>
  <path d="M80 60 C140 40 190 -40 220 -150 L250 -140 C230 -20 170 80 110 120 Z" fill="${C.redD}"/>
  <ellipse cx="236" cy="-162" rx="22" ry="28" fill="${C.skinS}"/>
  <path d="M-26 -10 L-28 42 L28 42 L26 -10 Z" fill="${C.skinS}"/>
  <path d="M-90 -60 C-102 -176 102 -176 90 -60 C94 -18 72 12 40 16 L-40 16 C-72 12 -94 -18 -90 -60 Z" fill="${C.g0}"/>
  <path d="M58 -146 C90 -114 98 -72 90 -38 M150 300 L188 740" fill="none" stroke="${C.orange}" stroke-width="5" opacity=".55"/>
  </g>`;
}
function boy(x, y, s) {
  return `<g transform="translate(${x} ${y}) scale(${s})" ${STK} stroke-width="6">
  <path d="M-40 230 L-44 420 L-14 420 L-8 230 Z M8 230 L14 420 L44 420 L40 230 Z" fill="${C.skin}"/>
  <path d="M-50 420 L-8 420 L-8 442 L-54 442 Z M10 420 L50 420 L56 442 L10 442 Z" fill="${C.g0}"/>
  <path d="M-58 150 L58 150 L62 250 L4 250 L0 222 L-4 250 L-62 250 Z" fill="${C.g2}"/>
  <path d="M-70 0 Q0 -20 70 0 L84 40 L66 60 L60 160 L-60 160 L-66 60 L-84 40 Z" fill="${C.paper2}"/>
  <path d="M-66 52 L-82 172 L-62 174 L-56 72 Z" fill="${C.skin}"/>
  <path d="M64 40 L150 -40 L166 -24 L80 66 Z" fill="${C.skin}"/>
  <circle cx="160" cy="-36" r="16" fill="${C.skin}"/>
  <ellipse cx="6" cy="-60" rx="48" ry="54" fill="${C.skin}"/>
  <ellipse cx="54" cy="-56" rx="8" ry="14" fill="${C.skinS}"/>
  <path d="M-46 -70 C-44 -132 58 -132 54 -72 C50 -42 40 -32 30 -26 L-20 -26 C-36 -32 -46 -46 -46 -70 Z" fill="${C.g0}"/>
  </g>`;
}
function kite(x, y, rot, lt) {
  let tail = 'M0 110', bows = '';
  for (let i = 1; i <= 7; i++) {
    const px = Math.sin(lt * 3.2 + i * .8) * (8 + i * 4), py = 110 + i * 42;
    tail += ` L${px.toFixed(1)} ${py}`;
    bows += `<path d="M${px - 14} ${py - 8} L${px} ${py} L${px - 14} ${py + 8} Z M${px + 14} ${py - 8} L${px} ${py} L${px + 14} ${py + 8} Z" fill="${i % 2 ? C.paper : C.red2}" stroke-width="3"/>`;
  }
  return `<g transform="translate(${x} ${y}) rotate(${rot})" ${STK} stroke-width="5">
  <path d="${tail}" fill="none" stroke-width="3"/>${bows}
  <path d="M0 -90 L62 0 L0 110 L-62 0 Z" fill="${C.red2}"/>
  <path d="M0 -90 L62 0 L0 0 Z" fill="${C.red}" stroke="none"/>
  <path d="M0 -90 L0 110 M-62 0 L62 0" fill="none" stroke-width="3"/></g>`;
}
function shelves(seed, rows = [180, 470, 760]) {
  const r = rng(seed); let o = '';
  for (const py of rows) {
    let x = -20;
    while (x < W + 20) {
      const w = 70 + r() * 50, h = 190 + r() * 60, f = r() < .5 ? C.g2 : C.g3;
      o += `<rect x="${x}" y="${py - h}" width="${w - 6}" height="${h}" fill="${f}" stroke="${C.ink}" stroke-width="4"/>`;
      o += `<rect x="${x + w * .18}" y="${py - h * .62}" width="${w * .5}" height="38" fill="${C.paper2}" stroke="${C.ink}" stroke-width="3" opacity=".85"/>`;
      o += `<path d="M${x + w * .24} ${py - h * .62 + 14} h${w * .36} M${x + w * .24} ${py - h * .62 + 26} h${w * .26}" stroke="${C.g3}" stroke-width="3"/>`;
      x += w;
    }
    o += `<rect x="-10" y="${py}" width="${W + 20}" height="20" fill="${C.g3}" stroke="${C.ink}" stroke-width="4"/>`;
  }
  return o;
}
function hangingLamp(x, y, flick) {
  return `<line x1="${x}" y1="-10" x2="${x}" y2="${y - 60}" stroke="${C.ink}" stroke-width="5"/>
  <path d="M${x - 300} 1560 L${x - 90} ${y} L${x + 90} ${y} L${x + 300 + 260} 1560 Z" fill="url(#gCone)" opacity="${.5 * flick}"/>
  <path d="M${x - 90} ${y} L${x - 40} ${y - 70} L${x + 40} ${y - 70} L${x + 90} ${y} Z" fill="${C.red}" stroke="${C.ink}" stroke-width="5" stroke-linejoin="round"/>
  <ellipse cx="${x}" cy="${y + 4}" rx="40" ry="10" fill="${C.paper}" opacity="${.9 * flick}"/>`;
}
const flicker = lt => .9 + .07 * Math.sin(lt * 23.1) * Math.sin(lt * 7.3) + .03 * Math.sin(lt * 51);
function stamp(x, y, rot, text, lt, t0, size = 46, pad = 26) {
  const k = clamp((lt - t0) / .12);
  if (lt < t0) return '';
  const s = lerp(1.9, 1, ease(k));
  const w = text.length * size * .52 + pad * 2;
  return `<g transform="translate(${x} ${y}) rotate(${rot}) scale(${s})" opacity="${.92 * k}">
  <rect x="${-w / 2}" y="${-size * .95}" width="${w}" height="${size * 1.9}" fill="none" stroke="${C.red2}" stroke-width="8" rx="6"/>
  <text x="0" y="${size * .36}" text-anchor="middle" font-family="Oswald" font-weight="700" font-size="${size}" fill="${C.red2}" letter-spacing="2">${text}</text></g>`;
}

/* ---------- scenes ---------- */
function s1(lt, d) {
  const r = rng(11);
  let o = `<rect width="${W}" height="${H}" fill="url(#gDusk)"/>`;
  o += `<ellipse cx="760" cy="880" rx="460" ry="170" fill="url(#gRedGlow)" opacity=".55"/>`;
  o += clouds(lt, 21, 8, 120, 760, 16, C.g1, .95);
  o += `<path d="M0 860 L90 822 L170 842 L260 762 L330 802 L420 792 L520 842 L640 812 L700 732 L760 702 L800 762 L880 802 L980 792 L1080 822 L1080 940 L0 940 Z" fill="${C.g1}"/>`;
  o += `<rect y="900" width="${W}" height="140" fill="#19191d"/>`;
  for (let i = 0; i < 80; i++) {
    const x = r() * W, y = 897 + r() * 34, tw = .5 + .5 * Math.sin(lt * 3 + i * 1.7), red = r() < .15;
    o += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(2 + r() * 1.8).toFixed(1)}" fill="${red ? '#d0573e' : C.paper}" opacity="${(.35 + .55 * tw).toFixed(2)}"/>`;
  }
  const ridge = x => 1010 - x * .065;
  o += `<path d="M0 1010 C200 975 380 990 560 962 C740 936 900 958 1080 940 L1080 1920 L0 1920 Z" fill="${C.g0}"/>`;
  o += `<path d="M0 1010 C200 975 380 990 560 962 C740 936 900 958 1080 940" fill="none" stroke="#5a1c1c" stroke-width="5"/>`;
  o += grass(lt, 12, 170, 0, W, 0, 1700, C.g2, 5, ridge);
  o += leadMask(395, 1125, -10, 1.25) + leadMask(700, 1180, 14, 1.15);
  o += rain(lt, 160, .2, 5);
  o += `<g>
  <text x="540" y="470" text-anchor="middle" font-family="Bebas Neue" font-size="205" fill="${C.paper}" stroke="${C.ink}" stroke-width="12" paint-order="stroke" letter-spacing="6">MÁSCARAS</text>
  <text x="540" y="650" text-anchor="middle" font-family="Bebas Neue" font-size="205" fill="${C.paper}" stroke="${C.ink}" stroke-width="12" paint-order="stroke" letter-spacing="6">DE CHUMBO</text>
  <rect x="290" y="678" width="500" height="9" fill="${C.red2}" stroke="${C.ink}" stroke-width="3"/>
  <text x="540" y="745" text-anchor="middle" font-family="Oswald" font-weight="600" font-size="40" fill="${C.paper}" stroke="${C.ink}" stroke-width="6" paint-order="stroke" letter-spacing="8">NITERÓI • AGOSTO DE 1966</text></g>`;
  return o;
}
function s2(lt, d) {
  const fl = flicker(lt);
  let o = `<rect width="${W}" height="${H}" fill="${C.g1}"/>` + shelves(31);
  o += `<rect width="${W}" height="${H}" fill="#000" opacity=".25"/>`;
  o += hangingLamp(540, 170, fl);
  o += agentBust(540, 700, 1.1, .6 + .4 * fl);
  o += `<path d="M-40 1040 L1120 1040 L1120 1920 L-40 1920 Z" fill="${C.wood}" stroke="${C.ink}" stroke-width="6"/>`;
  o += `<path d="M-40 1046 L1120 1046" stroke="${C.wood2}" stroke-width="10"/>`;
  o += `<path d="M170 1075 L910 1075 L990 1300 L90 1300 Z" fill="${C.paper3}" stroke="${C.ink}" stroke-width="6" stroke-linejoin="round"/>`;
  o += `<path d="M540 1075 L540 1300" stroke="${C.ink}" stroke-width="4" opacity=".6"/>`;
  const card = (cx, cy, rot, n1, n2, k) => `<g transform="translate(${cx} ${cy}) rotate(${rot})" opacity="${k}" ${STK} stroke-width="4">
    <rect x="-170" y="-82" width="340" height="164" fill="${C.paper}"/>
    <rect x="-155" y="-66" width="100" height="132" fill="${C.g3}"/>
    <ellipse cx="-105" cy="-22" rx="24" ry="28" fill="${C.g1}" stroke="none"/><path d="M-148 66 C-145 20 -130 8 -105 8 C-80 8 -65 20 -62 66 Z" fill="${C.g1}" stroke="none"/>
    <text x="-105" y="-8" text-anchor="middle" font-family="Bebas Neue" font-size="40" fill="${C.g4}" stroke="none">?</text>
    <text x="-38" y="-30" font-family="Courier Prime" font-weight="700" font-size="22" fill="${C.ink}" stroke="none">${n1}</text>
    <text x="-38" y="2" font-family="Courier Prime" font-weight="700" font-size="22" fill="${C.ink}" stroke="none">${n2}</text>
    <path d="M-38 24 h180 M-38 44 h140" stroke="${C.paper3}" stroke-width="3"/>
    <text x="-38" y="66" font-family="Courier Prime" font-weight="700" font-size="17" fill="${C.red}" stroke="none">TÉC. ELETRÔNICA</text></g>`;
  const c1 = CAP('s2', 1); const k1 = ease((lt - c1 + .2) / .5), k2 = ease((lt - c1 - .2) / .5);
  o += card(340 - (1 - k1) * 120, 1170, -4, 'MANOEL PEREIRA', 'DA CRUZ', k1);
  o += card(740 + (1 - k2) * 120, 1185, 3, 'MIGUEL JOSÉ', 'VIANA', k2);
  return o;
}
function calendar(x, y) {
  let o = `<g transform="translate(${x} ${y}) rotate(2)"><rect width="270" height="312" fill="${C.paper}" stroke="${C.ink}" stroke-width="5"/>
  <rect width="270" height="64" fill="${C.red}" stroke="${C.ink}" stroke-width="5"/>
  <text x="135" y="46" text-anchor="middle" font-family="Oswald" font-weight="700" font-size="34" fill="${C.paper}" letter-spacing="3">AGOSTO 1966</text>`;
  const hd = 'DSTQQSS';
  for (let i = 0; i < 7; i++) o += `<text x="${30 + i * 35}" y="94" text-anchor="middle" font-family="Courier Prime" font-weight="700" font-size="20" fill="${i === 0 ? C.red : C.ink}">${hd[i]}</text>`;
  for (let dd = 1; dd <= 31; dd++) {
    const idx = dd; // Aug 1 1966 = Monday -> column 1
    const row = Math.floor(idx / 7), col = idx % 7, tx = 30 + col * 35, ty = 130 + row * 36;
    o += `<text x="${tx}" y="${ty}" text-anchor="middle" font-family="Courier Prime" font-weight="700" font-size="21" fill="${col === 0 ? C.red : C.ink}">${dd}</text>`;
    if (dd === 17) o += `<circle cx="${tx}" cy="${ty - 7}" r="19" fill="none" stroke="${C.red2}" stroke-width="4"/>`;
  }
  return o + '</g>';
}
function s3(lt, d) {
  const r = rng(33);
  let o = `<rect width="${W}" height="${H}" fill="${C.g1}"/>`;
  for (let x = 45; x < W; x += 90) o += `<line x1="${x}" y1="0" x2="${x}" y2="${H}" stroke="${C.g0}" stroke-width="4" opacity=".7"/>`;
  o += `<path d="M640 0 L1080 0 L1080 700 L300 1000 Z" fill="${C.paper}" opacity=".06"/>`;
  o += `<rect x="40" y="520" width="560" height="20" fill="${C.g3}" stroke="${C.ink}" stroke-width="4"/>`;
  let jx = 60;
  while (jx < 560) {
    const w = 60 + r() * 30, h = 90 + r() * 60;
    o += `<rect x="${jx}" y="${520 - h}" width="${w}" height="${h}" rx="10" fill="${C.g3}" stroke="${C.ink}" stroke-width="4" opacity=".95"/>`;
    o += `<rect x="${jx - 3}" y="${520 - h - 16}" width="${w + 6}" height="18" fill="${C.g2}" stroke="${C.ink}" stroke-width="4"/>`;
    o += `<rect x="${jx + 10}" y="${520 - h * .6}" width="${w - 20}" height="${h * .3}" fill="${C.paper2}" opacity=".8"/>`;
    jx += w + 16;
  }
  o += calendar(720, 380);
  o += `<path d="M-20 930 L1100 930 L1100 1012 L-20 1012 Z" fill="${C.wood2}" stroke="${C.ink}" stroke-width="6"/>`;
  o += `<path d="M-20 1012 L1100 1012 L1100 1920 L-20 1920 Z" fill="${C.wood}" stroke="${C.ink}" stroke-width="6"/>`;
  for (let x = 120; x < W; x += 240) o += `<rect x="${x}" y="1060" width="180" height="300" fill="none" stroke="${C.ink}" stroke-width="4" opacity=".5"/>`;
  const coat = (x, y, w, h) => `<g ${STK} stroke-width="5"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="18" fill="${C.g5}" fill-opacity=".82"/>
    <path d="M${x + 12} ${y + h * .48} H${x + w - 12} M${x + w * .7} ${y + 8} L${x + w * .62} ${y + h - 8}" fill="none" stroke="${C.g4}" stroke-width="3"/>
    <path d="M${x + 30} ${y + 14} L${x + 120} ${y + 14}" stroke="${C.paper}" stroke-width="4" opacity=".55"/>
    <path d="M${x + w - 70} ${y} L${x + w - 40} ${y + h * .45} L${x + w - 10} ${y}" fill="${C.g6}" fill-opacity=".7" stroke-width="4"/></g>`;
  o += coat(180, 862, 340, 72) + coat(196, 792, 324, 70);
  const by = 932;
  o += `<g transform="translate(640 ${by})" ${STK} stroke-width="5">
    <ellipse cx="10" cy="0" rx="74" ry="12" fill="#000" opacity=".35" stroke="none"/>
    <path d="M-56 0 L-56 -170 C-56 -202 -20 -216 -17 -246 L-17 -302 L17 -302 L17 -246 C20 -216 56 -202 56 -170 L56 0 Z" fill="${C.g4}" fill-opacity=".55"/>
    <path d="M-50 -60 L-50 -4 L50 -4 L50 -60 Z" fill="${C.paper}" opacity=".25" stroke="none"/>
    <rect x="-56" y="-140" width="112" height="70" fill="${C.paper2}"/>
    <rect x="-56" y="-118" width="112" height="14" fill="${C.red}" stroke="none"/>
    <rect x="-20" y="-322" width="40" height="22" fill="${C.g3}"/>
    <path d="M-38 -168 L-38 -20 M-10 -236 L-10 -270" stroke="${C.paper}" stroke-width="5" opacity=".75"/></g>`;
  return o;
}
function s4(lt, d) {
  let o = `<rect width="${W}" height="${H}" fill="url(#gDusk)"/>`;
  o += `<ellipse cx="300" cy="900" rx="500" ry="200" fill="url(#gRedGlow)" opacity=".45"/>`;
  o += clouds(lt, 41, 9, 140, 820, 70, C.g1, .95);
  o += `<path d="M0 1060 C200 990 300 910 420 830 C520 770 600 705 700 645 C800 605 880 640 1080 700 L1080 1920 L0 1920 Z" fill="${C.g1}"/>`;
  o += `<path d="M0 1060 C200 990 300 910 420 830 C520 770 600 705 700 645 C800 605 880 640 1080 700" fill="none" stroke="#5a1c1c" stroke-width="5"/>`;
  o += `<path d="M330 1420 C430 1300 560 1200 520 1080 C490 990 600 930 640 860 C680 790 650 720 700 650" fill="none" stroke="${C.g3}" stroke-width="18" stroke-linecap="round"/>`;
  o += grass(lt, 44, 110, 0, W, 0, 1500, C.g2, 9, x => x < 700 ? 1060 - x * .59 : 645 + (x - 700) * .15);
  const k = lt / d;
  o += walker(lerp(548, 575, k), lerp(985, 925, k), lerp(.5, .46, k), lt * 5.5 + 1.3);
  o += walker(lerp(498, 528, k), lerp(1045, 985, k), lerp(.56, .52, k), lt * 5.5);
  o += `<path d="M0 1380 C260 1270 520 1180 760 1110 C900 1072 1000 1062 1080 1066 L1080 1920 L0 1920 Z" fill="${C.g0}"/>`;
  o += grass(lt, 45, 120, 0, W, 0, 1700, C.g2, 9, x => 1380 - x * .29);
  const r = rng(46);
  o += `<g stroke="${C.paper}" stroke-width="3" opacity=".22" stroke-linecap="round" fill="none">`;
  for (let i = 0; i < 14; i++) {
    const y = 200 + r() * 900, x = ((r() * 1600 + lt * 700 * (0.8 + r() * .5)) % 1600) - 300;
    o += `<path d="M${x.toFixed(1)} ${y.toFixed(1)} q60 -12 140 0"/>`;
  }
  o += '</g>' + rain(lt, 90, .14, 47, 1700, .35);
  o += `<text x="540" y="470" text-anchor="middle" font-family="Bebas Neue" font-size="150" fill="${C.paper}" stroke="${C.ink}" stroke-width="10" paint-order="stroke" letter-spacing="5">MORRO DO VINTÉM</text>
  <rect x="330" y="500" width="420" height="8" fill="${C.red2}" stroke="${C.ink}" stroke-width="3"/>`;
  return o;
}
function s5(lt, d) {
  let o = `<rect width="${W}" height="${H}" fill="url(#gOver)"/>`;
  o += clouds(lt, 51, 10, 90, 820, 12, '#56575c', .85);
  o += `<rect y="925" width="${W}" height="130" fill="#6c6a64"/>`;
  o += `<path d="M0 925 L1080 925" stroke="#85827a" stroke-width="4"/>`;
  o += `<path d="M0 1045 C300 1005 700 1012 1080 985 L1080 1920 L0 1920 Z" fill="${C.g2}"/>`;
  o += `<path d="M0 1045 C300 1005 700 1012 1080 985" fill="none" stroke="${C.g1}" stroke-width="6"/>`;
  o += grass(lt, 52, 200, 0, W, 0, 1750, C.g1, 6, x => 1045 - x * .055);
  const kx = 720 + Math.sin(lt * .9) * 18, ky = 360 + Math.sin(lt * 1.3) * 12, rot = Math.sin(lt * 1.7) * 7;
  const hx = 300 + 160 * .75, hy = 960 - 36 * .75;
  o += `<path d="M${hx} ${hy} Q 640 640 ${kx.toFixed(1)} ${(ky + 108).toFixed(1)}" fill="none" stroke="${C.ink}" stroke-width="2.5"/>`;
  o += kite(kx, ky, rot, lt);
  o += boy(300, 960, .75);
  o += `<path d="M1080 1000 L1080 1500 L900 1500 Z" fill="${C.red}" opacity=".18"/>`;
  return o;
}
function s6(lt, d) {
  const n = TL.scenes.find(s => s.id === 's6').note;
  const hx = Math.sin(lt * 1.3) * 8, hy = Math.cos(lt * 1.1) * 6;
  let o = `<rect width="${W}" height="${H}" fill="#0d0d10"/>`;
  o += `<ellipse cx="${540 + hx * 2}" cy="${770 + hy * 2}" rx="640" ry="600" fill="url(#gLamp)" opacity=".6"/>`;
  const r = rng(61);
  let top = 'M170 440';
  for (let x = 190; x <= 910; x += 20) top += ` L${x} ${(436 + (r() - .5) * 26).toFixed(1)}`;
  let bot = '';
  for (let x = 910; x >= 170; x -= 24) bot += ` L${x} ${(1088 + (r() - .5) * 16).toFixed(1)}`;
  const paperPath = `${top} L910 1088${bot} Z`;
  o += `<g transform="translate(${hx} ${hy}) rotate(-3 540 760)">
  <path d="${paperPath}" transform="translate(10 14)" fill="#000" opacity=".5"/>
  <path d="${paperPath}" fill="url(#pPaper)" stroke="${C.ink}" stroke-width="5" stroke-linejoin="round"/>`;
  for (let i = 0; i < 7; i++) o += `<line x1="185" y1="${505 + i * 80}" x2="900" y2="${505 + i * 80}" stroke="#8d8874" stroke-width="2" opacity=".55"/>`;
  o += `<line x1="232" y1="452" x2="232" y2="1080" stroke="${C.red2}" stroke-width="2.5" opacity=".55"/>`;
  let tt = n.start;
  n.lines.forEach((line, i) => {
    const vis = clamp(Math.floor((lt - tt) * n.cps), 0, line.length);
    const shown = line.slice(0, vis).replace(/&/g, '&amp;');
    const y = 568 + i * 80;
    if (vis > 0) o += `<text x="252" y="${y}" font-family="Special Elite" font-size="52" fill="#1d1a16">${shown}</text>`;
    const typing = lt >= tt && vis < line.length;
    const lastLine = i === n.lines.length - 1 && vis === line.length;
    if ((typing || lastLine) && Math.floor(lt * 3) % 2 === 0) {
      o += `<rect x="${252 + vis * 27.6}" y="${y - 40}" width="5" height="48" fill="${C.red2}"/>`;
    }
    tt += line.length / n.cps + n.gap;
  });
  o += `</g>`;
  o += `<g transform="translate(${hx * 1.2} ${hy * 1.2})" ${STK} stroke-width="6">
  <path d="M-40 1600 C40 1420 120 1260 190 1150 L240 1060 C262 1028 300 1034 296 1068 L262 1132 C306 1128 318 1162 286 1180 L170 1330 L120 1600 Z" fill="#141416"/>
  <path d="M205 1102 C222 1080 248 1064 270 1068" fill="none" stroke="${C.g4}" stroke-width="4"/>
  <path d="M-60 1640 L-10 1520 L160 1560 L120 1680 Z" fill="${C.g2}"/></g>`;
  return o;
}
function s7(lt, d) {
  const fl = flicker(lt + 3);
  let o = `<rect width="${W}" height="${H}" fill="${C.g1}"/>`;
  o += `<g transform="rotate(-18 540 600)" fill="${C.paper}" opacity=".07">`;
  for (let i = 0; i < 9; i++) o += `<rect x="150" y="${140 + i * 72}" width="1100" height="34"/>`;
  o += `</g>`;
  const mn = lt * 120, hr = lt * 10;
  o += `<g transform="translate(820 430)" ${STK}><circle r="98" fill="${C.paper}" stroke-width="9"/>`;
  for (let i = 0; i < 12; i++) o += `<line x1="0" y1="-84" x2="0" y2="${i % 3 ? -74 : -66}" stroke-width="${i % 3 ? 3 : 6}" transform="rotate(${i * 30})"/>`;
  o += `<line x1="0" y1="10" x2="0" y2="-48" stroke-width="10" transform="rotate(${hr})"/>
  <line x1="0" y1="14" x2="0" y2="-74" stroke-width="6" transform="rotate(${mn})"/>
  <circle r="9" fill="${C.red2}" stroke-width="3"/></g>`;
  o += `<path d="M960 960 L880 760 L930 640" fill="none" stroke="${C.ink}" stroke-width="10"/>`;
  o += `<path d="M640 1560 L870 640 L990 640 L1150 1560 Z" fill="url(#gCone)" opacity="${.42 * fl}"/>`;
  o += `<path d="M860 640 L900 560 L990 560 L1010 640 Z" fill="${C.red}" stroke="${C.ink}" stroke-width="5" stroke-linejoin="round"/>`;
  o += `<path d="M-30 960 L1110 960 L1110 1040 L-30 1040 Z" fill="${C.wood2}" stroke="${C.ink}" stroke-width="6"/>`;
  o += `<path d="M-30 1040 L1110 1040 L1110 1920 L-30 1920 Z" fill="${C.wood}" stroke="${C.ink}" stroke-width="6"/>`;
  for (let i = 0; i < 6; i++) o += `<rect x="${60 + i * 6}" y="${940 - i * 16}" width="300" height="22" fill="${i % 2 ? C.paper2 : C.paper3}" stroke="${C.ink}" stroke-width="4"/>`;
  o += `<g ${STK} stroke-width="5"><path d="M330 975 L780 975 L800 1035 L310 1035 Z" fill="${C.paper3}"/>
  <path d="M360 975 L360 958 L470 958 L486 975" fill="${C.paper3}"/></g>`;
  o += `<text x="555" y="1018" text-anchor="middle" font-family="Courier Prime" font-weight="700" font-size="26" fill="${C.ink}">NITERÓI • 1966</text>`;
  o += stamp(560, 1150, -7, 'CAUSA: INDETERMINADA', lt, CAP('s7', 1), 50);
  return o;
}
function s8(lt, d) {
  const pulse = .65 + .35 * Math.sin(lt * 2.2), ox = 620 + Math.sin(lt * .5) * 10, oy = 720 + Math.sin(lt * .7) * 6;
  let o = `<rect width="${W}" height="${H}" fill="#101013"/>`;
  o += `<g clip-path="url(#cWin)"><rect x="170" y="280" width="740" height="880" fill="url(#gNight)"/>`;
  o += clouds(lt, 81, 6, 330, 760, 10, '#2a2b31', .9);
  o += `<ellipse cx="${ox}" cy="${oy}" rx="190" ry="120" fill="url(#gGlow)" opacity="${(.5 * pulse).toFixed(3)}"/>`;
  o += `<ellipse cx="${ox}" cy="${oy}" rx="50" ry="21" fill="#f6a35a" opacity="${(.85 * pulse).toFixed(3)}" filter="url(#blur6)"/>`;
  o += `<ellipse cx="${ox}" cy="${oy}" rx="36" ry="13" fill="#ffd29a" opacity="${(.9 * pulse).toFixed(3)}"/>`;
  o += `<path d="M170 1010 C350 905 500 862 620 882 C740 902 820 962 910 992 L910 1160 L170 1160 Z" fill="#08080a"/>`;
  const r = rng(82);
  for (let i = 0; i < 18; i++) o += `<circle cx="${(180 + r() * 720).toFixed(1)}" cy="${(1060 + r() * 90).toFixed(1)}" r="2.5" fill="${C.paper}" opacity="${(.3 + .4 * r()).toFixed(2)}"/>`;
  o += `<path d="M260 280 L520 280 L260 1160 Z" fill="${C.paper}" opacity=".04"/></g>`;
  o += `<g fill="none" stroke="${C.g2}"><rect x="170" y="280" width="740" height="880" stroke-width="30"/>
  <line x1="540" y1="280" x2="540" y2="1160" stroke-width="18"/><line x1="170" y1="720" x2="910" y2="720" stroke-width="18"/></g>`;
  o += `<rect x="130" y="1160" width="820" height="40" fill="${C.g2}" stroke="${C.ink}" stroke-width="6"/>`;
  o += `<g ${STK} stroke-width="6">
  <path d="M-20 200 L230 200 C200 500 260 900 200 1500 L-20 1500 Z" fill="${C.redD}"/>
  <path d="M60 240 C80 600 50 1000 90 1450 M150 240 C170 600 140 1000 170 1460" fill="none" stroke="#260b0b" stroke-width="6"/>
  <path d="M1100 200 L860 200 C900 500 840 900 900 1500 L1100 1500 Z" fill="${C.redD}"/>
  <path d="M1000 240 C980 600 1010 1000 980 1450" fill="none" stroke="#260b0b" stroke-width="6"/></g>`;
  o += `<g transform="translate(330 1230) scale(-.95 .95)">${woman(0, 0, 1)}</g>`;
  return o;
}
function tube(x, y, lt, i) {
  const g = .45 + .3 * Math.sin(lt * 4 + i * 2);
  return `<g transform="translate(${x} ${y})" ${STK} stroke-width="4">
  <rect x="-30" y="-26" width="60" height="26" fill="${C.g0}"/>
  <path d="M-24 -26 L-24 -126 C-24 -168 24 -168 24 -126 L24 -26 Z" fill="${C.g5}" fill-opacity=".28"/>
  <rect x="-13" y="-110" width="26" height="70" fill="${C.g3}"/>
  <ellipse cx="0" cy="-74" rx="10" ry="26" fill="${C.orange}" stroke="none" opacity="${g.toFixed(2)}" filter="url(#blur6)"/>
  <path d="M-16 -130 L-16 -46" stroke="${C.paper}" stroke-width="4" opacity=".6"/></g>`;
}
function s9(lt, d) {
  const fl = flicker(lt + 7);
  let o = `<rect width="${W}" height="${H}" fill="${C.g1}"/>`;
  o += `<rect x="60" y="260" width="960" height="640" fill="${C.g2}" stroke="${C.ink}" stroke-width="6"/>`;
  let dots = '';
  for (let y = 290; y < 890; y += 40) for (let x = 90; x < 1000; x += 40) dots += `M${x} ${y}h0.1`;
  o += `<path d="${dots}" stroke="${C.g0}" stroke-width="7" stroke-linecap="round"/>`;
  o += `<g ${STK} stroke-width="5" fill="${C.g0}">
  <path d="M200 380 L230 380 L250 560 L236 640 L220 640 L214 560 Z M260 380 L290 380 L280 560 L270 640 L254 640 L248 560 Z"/>
  <circle cx="420" cy="460" r="70" fill="none" stroke="${C.g3}" stroke-width="14"/>
  <path d="M620 360 L640 360 L700 600 L680 604 Z M700 360 L720 360 L660 604 L640 600 Z"/>
  <rect x="820" y="360" width="90" height="220" rx="10" fill="${C.g3}"/></g>`;
  o += hangingLamp(540, 140, fl);
  o += `<path d="M-30 940 L1110 940 L1110 1010 L-30 1010 Z" fill="${C.wood2}" stroke="${C.ink}" stroke-width="6"/>`;
  o += `<path d="M-30 1010 L1110 1010 L1110 1920 L-30 1920 Z" fill="${C.wood}" stroke="${C.ink}" stroke-width="6"/>`;
  o += `<g ${STK} stroke-width="5"><rect x="80" y="880" width="190" height="62" fill="${C.red}"/>
  <rect x="88" y="888" width="174" height="14" fill="${C.paper2}"/><path d="M80 912 L270 912" stroke-width="3"/></g>`;
  o += tube(330, 960, lt, 0) + tube(410, 960, lt, 1) + tube(490, 960, lt, 2);
  o += `<g ${STK} stroke-width="5"><path d="M600 960 L640 900 L690 960 Z" fill="${C.g3}"/>
  <path d="M630 920 L820 800" stroke-width="16"/><path d="M630 920 L820 800" stroke="${C.red}" stroke-width="8"/>
  <path d="M820 800 L870 768" stroke="${C.g5}" stroke-width="7"/></g>`;
  let smoke = '';
  for (let i = 0; i < 3; i++) {
    const ph = lt * 1.6 + i * 2.1, base = 870;
    smoke += `<path d="M${base} 766 C${base + Math.sin(ph) * 30} 700 ${base - 30 + Math.sin(ph + 1) * 40} 640 ${base + Math.sin(ph + 2) * 50} ${560 - i * 20}" fill="none" stroke="${C.paper}" stroke-width="${7 - i * 2}" opacity="${.22 - i * .05}" filter="url(#blur6)"/>`;
  }
  o += smoke;
  const scrap = (x, y, rot, s) => `<path transform="translate(${x} ${y}) rotate(${rot}) scale(${s})" d="M-50 -20 L-10 -30 L30 -18 L52 6 L20 24 L-24 18 L-46 6 Z" fill="${C.g4}" stroke="${C.ink}" stroke-width="4" stroke-linejoin="round"/>`;
  o += scrap(600, 985, 8, 1) + scrap(760, 978, -14, .8) + scrap(930, 990, 20, 1.1);
  o += `<g transform="translate(860 975) rotate(-12)" ${STK} stroke-width="5"><path d="M-70 -6 L0 0 L-70 10 Z M0 0 L60 -26 L66 -16 Z M0 0 L60 26 L54 34 Z" fill="${C.g3}"/><circle r="8" fill="${C.red}"/></g>`;
  return o;
}
function card(x, y, rot, label, icon, state) {
  const sc = state === 2 ? 1.08 : 1;
  const dim = state === 0 ? `<rect x="-150" y="-118" width="300" height="236" fill="#000" opacity=".42"/>` : '';
  const ring = state === 2 ? `<rect x="-158" y="-126" width="316" height="252" fill="none" stroke="${C.red2}" stroke-width="8"/>` : '';
  return `<g transform="translate(${x} ${y}) rotate(${rot}) scale(${sc})" ${STK} stroke-width="5">
  <rect x="-145" y="-113" width="300" height="236" fill="#000" opacity=".4" stroke="none"/>
  <rect x="-150" y="-118" width="300" height="236" fill="${C.paper}"/>${icon}
  <text x="0" y="92" text-anchor="middle" font-family="Oswald" font-weight="700" font-size="34" fill="${C.ink}" stroke="none" letter-spacing="1">${label}</text>
  ${dim}${ring}<circle cx="0" cy="-104" r="13" fill="${C.red2}"/></g>`;
}
function s10(lt, d) {
  const r = rng(101);
  let o = `<rect width="${W}" height="${H}" fill="${C.g1}"/>`;
  o += `<rect x="80" y="270" width="920" height="930" fill="${C.cork}" stroke="${C.g0}" stroke-width="26"/>`;
  let sp = '';
  for (let i = 0; i < 500; i++) sp += `M${(96 + r() * 888).toFixed(0)} ${(286 + r() * 898).toFixed(0)}h0.1`;
  o += `<path d="${sp}" stroke="#7b6844" stroke-width="5" stroke-linecap="round"/>`;
  const q1 = CAP('s10', 1), q2 = CAP('s10', 2), q3 = CAP('s10', 3);
  const ph = lt < q1 ? 0 : lt < q2 ? 1 : lt < q3 ? 2 : 3;
  const st = i => (ph === 3 ? 1 : ph === i ? 2 : 0);
  const P = { c: [540, 720], a: [290, 470], b: [800, 500], e: [560, 1010] };
  o += `<g stroke="${C.red2}" stroke-width="5" fill="none">
  <path d="M${P.c[0]} ${P.c[1] - 125} Q 420 520 ${P.a[0]} ${P.a[1] - 104}"/>
  <path d="M${P.c[0]} ${P.c[1] - 125} Q 680 540 ${P.b[0]} ${P.b[1] - 104}"/>
  <path d="M${P.c[0]} ${P.c[1] - 125} Q 470 860 ${P.e[0]} ${P.e[1] - 104}"/></g>`;
  o += `<g transform="translate(${P.c[0]} ${P.c[1]}) rotate(3)" ${STK} stroke-width="5">
  <rect x="-115" y="-125" width="230" height="250" fill="${C.paper}"/>
  <rect x="-95" y="-110" width="190" height="160" fill="${C.g0}"/>
  <g clip-path="url(#cPhoto)">${leadMask(0, -36, -6, .62)}</g>
  <circle cx="0" cy="-125" r="13" fill="${C.red2}"/></g>`;
  const cap = `<g transform="translate(0 -22) rotate(-28)"><rect x="-70" y="-26" width="140" height="52" rx="26" fill="${C.paper2}"/><path d="M-44 -26 L0 -26 L0 26 L-44 26 A26 26 0 0 1 -44 -26 Z" fill="${C.red2}"/></g>`;
  const mag = `<g transform="translate(-10 -28)"><line x1="26" y1="26" x2="72" y2="72" stroke-width="16"/><circle r="44" fill="${C.g6}" fill-opacity=".45" stroke-width="10"/></g>`;
  const ufo = `<g transform="translate(0 -26)"><ellipse rx="90" ry="50" fill="url(#gGlow)" stroke="none"/><ellipse rx="52" ry="18" fill="${C.orange}"/></g>`;
  o += card(P.a[0], P.a[1], -4, 'EXPERIMENTO?', cap, st(0));
  o += card(P.b[0], P.b[1], 5, 'CRIME?', mag, st(1));
  o += card(P.e[0], P.e[1], -2, 'SEM EXPLICAÇÃO?', ufo, st(2));
  o += stamp(540, 760, -10, 'NENHUMA COMPROVADA', lt, q3, 54);
  o += agentBack(930, 1360, .82);
  return o;
}
function s11(lt, d) {
  const fl = flicker(lt + 11);
  let o = `<rect width="${W}" height="${H}" fill="${C.g1}"/>` + shelves(31);
  o += `<rect width="${W}" height="${H}" fill="#000" opacity=".3"/>`;
  o += hangingLamp(540, 170, fl);
  o += agentBust(540, 740, 1.15, .5 + .5 * fl);
  o += `<path d="M-40 1050 L1120 1050 L1120 1920 L-40 1920 Z" fill="${C.wood}" stroke="${C.ink}" stroke-width="6"/>`;
  o += `<path d="M-40 1056 L1120 1056" stroke="${C.wood2}" stroke-width="10"/>`;
  o += `<g ${STK} stroke-width="6"><path d="M240 1080 L840 1080 L880 1280 L200 1280 Z" fill="${C.paper3}"/>
  <path d="M270 1080 L270 1056 L420 1056 L440 1080" fill="${C.paper3}"/></g>`;
  o += `<text x="540" y="1150" text-anchor="middle" font-family="Courier Prime" font-weight="700" font-size="32" fill="${C.ink}">CASO: MÁSCARAS DE CHUMBO</text>`;
  o += `<text x="540" y="1192" text-anchor="middle" font-family="Courier Prime" font-weight="700" font-size="26" fill="${C.ink}">NITERÓI • 1966</text>`;
  o += stamp(690, 1252, -6, 'SEM SOLUÇÃO', lt, CAP('s11', 0) + 1.6, 40);
  const k = ease((lt - CAP('s11', 1) - .2) / .5);
  if (k > 0) o += `<g opacity="${k}" transform="translate(0 ${(1 - k) * 16})">
    <rect x="160" y="250" width="760" height="190" fill="#0e0e10" stroke="${C.ink}" stroke-width="6" opacity=".92"/>
    <text x="470" y="390" text-anchor="middle" font-family="Bebas Neue" font-size="150" fill="${C.paper}" letter-spacing="6">ARQUIVO</text>
    <rect x="690" y="270" width="210" height="150" fill="${C.red}" stroke="${C.ink}" stroke-width="5"/>
    <text x="795" y="390" text-anchor="middle" font-family="Bebas Neue" font-size="150" fill="${C.paper}" letter-spacing="4">013</text>
    <text x="540" y="490" text-anchor="middle" font-family="Oswald" font-weight="600" font-size="32" fill="${C.paper}" stroke="${C.ink}" stroke-width="6" paint-order="stroke" letter-spacing="5">FONTES NA DESCRIÇÃO</text></g>`;
  return o;
}

const SCENES = { s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11 };
const CAMS = {
  s1: { s0: 1.0, s1: 1.07, cy: 1000 }, s2: { s0: 1.0, s1: 1.07, cy: 950 }, s3: { s0: 1.06, s1: 1.1, x0: 50, x1: -50, cy: 900 },
  s4: { s0: 1.0, s1: 1.09, cx: 540, cy: 950 }, s5: { s0: 1.0, s1: 1.07, cx: 420, cy: 1000 }, s6: { s0: 1.0, s1: 1.06, cy: 760 },
  s7: { s0: 1.0, s1: 1.06, cy: 1000 }, s8: { s0: 1.0, s1: 1.09, cx: 620, cy: 740 }, s9: { s0: 1.0, s1: 1.07, cy: 950 },
  s10: { s0: 1.05, s1: 1.0, cy: 760 }, s11: { s0: 1.0, s1: 1.05, cy: 900 }
};

let STARTS = null;
function setup() { let t = 0; STARTS = TL.scenes.map(s => { const st = t; t += s.dur; return st; }); window.TOTAL = t; }
function capHTML(txt) {
  return txt.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/\[\[(.+?)\]\]/g, '<span class="hl">$1</span>');
}
window.renderFrame = function (f) {
  if (!STARTS) setup();
  const t = f / TL.fps;
  let i = TL.scenes.length - 1; while (i > 0 && t < STARTS[i]) i--;
  const sc = TL.scenes[i], lt = t - STARTS[i], d = sc.dur;
  const last = i === TL.scenes.length - 1;
  const fi = i === 0 ? 1 : clamp(lt / .22), fo = last ? clamp((d - lt) / .5) : clamp((d - lt) / .14);
  const vis = Math.min(fi, fo);
  document.getElementById('scene').innerHTML = `<g transform="${cam(lt, d, CAMS[sc.id])}">${SCENES[sc.id](lt, d)}</g>`;
  document.getElementById('fade').setAttribute('opacity', (1 - vis).toFixed(3));
  const r = rng(f * 7 + 3);
  let sp = '';
  const n = Math.floor(r() * 4);
  for (let k = 0; k < n; k++) {
    const x = r() * W, y = r() * H, big = r() < .25;
    sp += big ? `<path d="M${x.toFixed(0)} ${y.toFixed(0)} q${(r() * 30 - 15).toFixed(0)} 20 ${(r() * 40 - 20).toFixed(0)} 46" stroke="${C.ink}" stroke-width="2" fill="none" opacity=".5"/>`
      : `<circle cx="${x.toFixed(0)}" cy="${y.toFixed(0)}" r="${(1.5 + r() * 2.5).toFixed(1)}" fill="${r() < .5 ? C.paper : C.ink}" opacity=".55"/>`;
  }
  document.getElementById('specks').innerHTML = sp;
  document.getElementById('grain').style.transform = `translate(${(-r() * 110).toFixed(0)}px, ${(-r() * 170).toFixed(0)}px)`;
  document.getElementById('flick').style.opacity = (.015 + r() * .04).toFixed(3);
  const lab = document.getElementById('lab');
  if (sc.label) { lab.style.display = 'block'; lab.textContent = sc.label; lab.style.opacity = vis; } else lab.style.display = 'none';
  const brand = document.getElementById('brand');
  brand.style.display = (i >= 1 && !last) ? 'block' : 'none';
  const capEl = document.getElementById('cap');
  let cur = null;
  for (const c of sc.caps) if (lt >= c[0]) cur = c;
  if (cur && cur[1]) {
    const a = ease((lt - cur[0]) / .18);
    capEl.innerHTML = `<span class="t">${capHTML(cur[1])}</span>`;
    capEl.style.opacity = (a * vis).toFixed(3);
    capEl.style.transform = `translateY(${((1 - a) * 14).toFixed(1)}px)`;
  } else capEl.innerHTML = '';
};
