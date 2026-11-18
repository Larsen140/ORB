/* ================= ORB Glas-Dashboard =================
   Baut die neue Oberfläche (Seitenleiste, Leiste oben, Begrüßung, Hauptkarte mit Kugel im Ring, Kalender,
   Kennzahlen, Trading, Agenten, Gespräch) über die bestehende ORB-Seite. Alle Daten kommen aus den vorhandenen
   Endpunkten; die alten Elemente (Chat, Mikro, Einstellungen) werden wiederverwendet. */
(() => {
  if (document.documentElement.classList.contains('spiel')) return;   // Spiel-Kugel bleibt schlicht
  const $d = id => document.getElementById(id);
  const ls = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } };
  const escH = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;' }[c]));
  const THEMEN = [
    ['koralle', 'Koralle', 'linear-gradient(135deg,#ee5440,#ff7f66,#ffb38c)'], ['sand', 'Sand', 'linear-gradient(135deg,#e6dfd6,#2bb79c)'],
    ['salbei', 'Salbei', 'linear-gradient(135deg,#3f7d5c,#5fa57a,#b4dcae)'], ['ozean', 'Ozean', 'linear-gradient(135deg,#1d5fe0,#2f8bff,#7fd3ff)'],
    ['lavendel', 'Lavendel', 'linear-gradient(135deg,#6d3ef0,#9b6bff,#e0b4ff)'], ['gold', 'Gold', 'linear-gradient(135deg,#b9781a,#e0a63a,#f7d98a)'],
    ['rose', 'Rosé', 'linear-gradient(135deg,#d93a6f,#f2668f,#ffb3c7)'],
  ];
  const IC = {
    home:'<path d="M12 3 2 11.5h3V20h5.5v-5.5h3V20H19v-8.5h3z"/>',
    chart:'<path d="M4 19h16v2H2V3h2zm3-3 4-5 3 3 5-7 1.6 1.2-6.4 9-3-3-2.6 3.3z"/>',
    agenten:'<path d="M9 11a4 4 0 1 1 0-8 4 4 0 0 1 0 8zm7.5 1a3 3 0 1 1 0-6 3 3 0 0 1 0 6zM2 20c0-3.3 3.1-6 7-6s7 2.7 7 6zm15.6 0c0-1.9-.7-3.6-1.9-4.9 3.1.3 5.3 2.3 5.3 4.9z"/>',
    chat:'<path d="M4 4h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H8l-4 4V6a2 2 0 0 1 2-2z"/>',
    mic:'<path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.9V22h2v-3.1a7 7 0 0 0 6-6.9z"/>',
    stop:'<rect x="6" y="6" width="12" height="12" rx="2.5"/>',
    gear:'<path d="M19.4 13a7.5 7.5 0 0 0 0-2l2.1-1.6-2-3.5-2.5 1a7.3 7.3 0 0 0-1.7-1L15 3h-4l-.3 2.9a7.3 7.3 0 0 0-1.7 1l-2.5-1-2 3.5L4.6 11a7.5 7.5 0 0 0 0 2l-2.1 1.6 2 3.5 2.5-1a7.3 7.3 0 0 0 1.7 1L11 21h4l.3-2.9a7.3 7.3 0 0 0 1.7-1l2.5 1 2-3.5zM13 15.5a3.5 3.5 0 1 1 0-7 3.5 3.5 0 0 1 0 7z"/>',
    farbe:'<path d="M12 3a9 9 0 0 0 0 18c1.1 0 2-.9 2-2 0-.5-.2-1-.5-1.3-.3-.4-.5-.8-.5-1.3 0-1.1.9-2 2-2h2.3A4.7 4.7 0 0 0 22 9.7C22 5.9 17.5 3 12 3zM6.5 12a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm3-4a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm5 0a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm3 4a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3z"/>',
    klassik:'<path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 15a5 5 0 1 1 0-10 5 5 0 0 1 0 10z"/>',
    plus:'<path d="M11 5h2v6h6v2h-6v6h-2v-6H5v-2h6z"/>',
    uhr:'<path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm1 10.4 3.5 2.1-1 1.7L11 13V7h2z"/>',
    kal:'<path d="M7 2h2v2h6V2h2v2h3v17H4V4h3zm-1 7v10h12V9z"/>',
    pfeil:'<path d="m9 6 6 6-6 6-1.4-1.4L12.2 12 7.6 7.4z"/>',
  };
  const svg = n => `<svg viewBox="0 0 24 24">${IC[n]}</svg>`;

  // ---------- Aufbau ----------
  const bg = document.createElement('div'); bg.id = 'dbg';
  const d = document.createElement('div'); d.id = 'dash';
  d.innerHTML = `
  <nav id="d-rail" class="dg d-rein" style="animation-delay:.05s">
    <div class="kopf"><div class="orb" title="ORB"></div><div class="lab"><b>ORB</b><span>Jarvis · Glas-Zentrale</span></div>
      <button class="auf" id="d-auf" title="Seitenleiste auf-/zuklappen">${svg('pfeil')}</button></div>
    <form class="suche lab" id="d-suche" onsubmit="return false"><i></i><input placeholder="Frag ORB …" autocomplete="off"></form>
    <div class="rubrik lab">Haupt</div>
    <button data-s="home" class="an">${svg('home')}<span class="lab">Übersicht</span><span class="tip">Übersicht</span></button>
    <button data-s="trading">${svg('chart')}<span class="lab">Trading</span><span class="tip">Trading</span></button>
    <button data-s="agenten">${svg('agenten')}<span class="lab">Agenten</span><span class="tip">Agenten &amp; Aufgaben</span></button>
    <button data-s="chat">${svg('chat')}<span class="lab">Gespräch</span><span class="tip">Gespräch</span></button>
    <div class="unten">
      <button id="d-mic">${svg('mic')}<span class="lab">Sprechen</span><span class="tip">Sprechen (Leertaste halten)</span></button>
      <button id="d-stop">${svg('stop')}<span class="lab">Stopp</span><span class="tip">Stopp</span></button>
      <button id="d-set">${svg('gear')}<span class="lab">Einstellungen</span><span class="tip">Einstellungen</span></button>
    </div>
  </nav>
  <header id="d-top" class="dg d-rein" style="animation-delay:.12s">
    <div class="av">L</div><div class="wil">Willkommen, Larsen</div>
    <form class="mitte" id="d-frag" onsubmit="return false"><i class="punkt"></i><input placeholder="Frag ORB etwas … z. B. „Wie steht Gold?“" autocomplete="off"><span id="d-status">Bereit</span></form>
    <div class="rechts"><button class="d-rund" id="d-farbe" title="Farbthema">${svg('farbe')}</button></div>
  </header>
  <div id="d-themen" class="dg"><div class="d-modus"><button data-m="hell">☀ Hell</button><button data-m="dunkel">☾ Dunkel</button></div>${THEMEN.map(([k, n, g]) => `<button data-t="${k}"><i style="background:${g}"></i>${n}</button>`).join('')}</div>
  <main id="d-main" class="dg d-rein" style="animation-delay:.18s">
    <section class="d-seite an" data-s="home">
      <div class="d-kopf d-rein" style="animation-delay:.3s">
        <div><h1 id="d-gruss">Hallo, Larsen</h1><div class="unter" id="d-unter"></div></div>
        <div class="knoepfe"><button class="d-pill" data-geh="agenten">${svg('uhr')}Aktivität</button><button class="d-pill dunkel" id="d-neu">${svg('plus')}Neuer Auftrag</button></div>
      </div>
      <div class="d-raster">
        <div id="d-held" class="d-karte d-rein" style="animation-delay:.38s">
          <div class="links">
            <span class="d-chipx"><i></i><span id="d-chip">ORB ist bereit</span></span>
            <h2 id="d-titel">Dein Tag läuft <em>rund</em></h2>
            <div class="txt" id="d-txt">Sag „Jarvis“ oder klatsch zweimal – ich bin da.</div>
            <div class="werte">
              <div><b id="d-w1">0</b><span>Termine heute</span></div>
              <div><b id="d-w2">0</b><span>Agenten aktiv</span></div>
              <div><b id="d-w3">–</b><span>Gold heute</span></div>
            </div>
          </div>
          <div id="d-ring">
            <svg class="bogen" viewBox="0 0 100 100"><circle class="spur" cx="50" cy="50" r="46"/><circle class="wert" id="d-bogen" cx="50" cy="50" r="46" stroke-dasharray="289" stroke-dashoffset="289"/></svg>
            <div class="kugelplatz" id="d-kugel"></div>
            <span class="blase" style="left:-4%;top:12%" data-geh="trading" title="Gold">📈</span>
            <span class="blase" style="left:-12%;top:52%;animation-delay:-1.2s" data-geh="agenten" title="Agenten">🤖</span>
            <span class="blase" style="left:8%;top:86%;animation-delay:-2.4s" id="d-bl-musik" title="Musik">🎵</span>
            <span class="blase" style="left:82%;top:-6%;animation-delay:-3.1s" data-geh="chat" title="Gespräch">💬</span>
            <span class="proz" id="d-proz">Tag zu 0 % geschafft</span>
          </div>
        </div>
        <div id="d-kal" class="d-karte d-rein" style="animation-delay:.46s">
          <div class="oben"><div class="tag" id="d-tag">--</div><div><div class="wt" id="d-wt"></div><div class="mon" id="d-mon"></div></div>
            <button class="d-rund" title="Termin sagen: „Termin morgen um 15 Uhr …“">${svg('kal')}</button></div>
          <div id="d-woche"></div>
          <div id="d-termine"><div class="leer">Lädt …</div></div>
          <div id="d-antwort"></div>
          <form class="gespr" id="d-form" onsubmit="return false"><input id="d-eingabe" placeholder="Nachricht an ORB …" autocomplete="off"><button title="Senden">↑</button></form>
        </div>
        <div id="d-kacheln">
          <div class="d-karte d-kachel akzent d-rein" data-geh="trading" style="animation-delay:.54s"><div class="d-h"><span class="ik">$</span><span class="los bad" id="d-gold-d">–</span></div>
            <div class="zahl" id="d-gold">–</div><div class="fuss"><div><div class="lbl">Gold · XAU/USD</div><div class="unt">Vantage · live</div></div>
            <svg class="spark" viewBox="0 0 100 26" preserveAspectRatio="none"><path id="d-spark" d=""/></svg></div></div>
          <div class="d-karte d-kachel d-rein" data-geh="agenten" style="animation-delay:.6s"><div class="d-h"><span class="ik">${svg('agenten')}</span><span class="los bad up" id="d-ag-b">live</span></div>
            <div class="zahl" id="d-ag">0</div><div class="fuss"><div><div class="lbl">Agenten aktiv</div><div class="unt" id="d-ag-l">gerade frei</div></div>
            <svg class="spark" viewBox="0 0 100 26" preserveAspectRatio="none"><path id="d-spark-ag" d=""/></svg></div></div>
          <div class="d-karte d-kachel d-rein" style="animation-delay:.66s"><div class="d-h"><span class="ik">⚡</span><span class="los bad" id="d-ram">RAM –</span></div>
            <div class="zahl" id="d-cpu">–</div><div class="fuss"><div><div class="lbl">CPU-Last</div><div class="unt" id="d-wx">Wetter lädt</div></div>
            <svg class="spark" viewBox="0 0 100 26" preserveAspectRatio="none"><path id="d-spark-cpu" d=""/></svg></div></div>
          <div class="d-karte d-kachel eq d-rein" id="d-musik" style="animation-delay:.72s"><div class="d-h"><span class="ik">♪</span><span class="los bad" id="d-mu-b">Spotify</span></div>
            <div class="zahl" id="d-mu">Gerade keine Musik</div><div class="fuss"><div><div class="lbl" id="d-mu-a">Sag „spiel Musik“</div><div class="unt">Tippen = Play/Pause</div></div>
            <div class="eqbars"><i></i><i></i><i></i><i></i><i></i></div></div></div>
        </div>
        <div id="d-aktionen">
          ${[['📊', 'Gold-Analyse', 'Harmonics-Check', 'Analysiere Gold nach meiner Harmonics-Strategie'],
             ['🗓', 'Mein Tag', 'Termine & Plan', 'Was steht heute an?'],
             ['🎬', 'TikTok-Idee', '3 Vorschläge', 'Gib mir drei TikTok-Video-Ideen für heute'],
             ['🩺', 'PC-Check', 'Doktor fragen', 'Mach einen PC-Check'],
             ['🎵', 'Musik', 'Spotify-DJ', 'Spiel Musik passend zur Stimmung'],
             ['🧱', 'Bau-Idee', 'Minecraft', 'Zeig mir drei Bau-Ideen für Minecraft']]
            .map(([i, t, u, cmd], n) => `<button class="d-aktion d-rein" data-cmd="${escH(cmd)}" style="animation-delay:${.78 + n * .04}s"><span class="ik">${i}</span><span><b>${t}</b><small>${u}</small></span></button>`).join('')}
        </div>
      </div>
    </section>
    <section class="d-seite" data-s="trading">
      <div class="d-kopf"><div><h1>Trading</h1><div class="unter">Gold · XAU/USD bei <b>Vantage</b> · Harmonics-Strategie</div></div>
        <div class="knoepfe"><div class="d-segment" id="d-tf">${[['15', '15 Min'], ['60', '1 Std'], ['240', '4 Std'], ['D', 'Tag']].map(([x, n], i) => `<button data-tf="${x}" class="${i === 0 ? 'an' : ''}">${n}</button>`).join('')}</div>
          <button class="d-pill dunkel" id="d-tv">${svg('chart')}Mein TradingView</button></div></div>
      <div class="d-statreihe" id="d-tstats"></div>
      <div class="d-zweispaltig"><div class="d-karte d-chart" id="d-chart"></div>
        <div class="d-karte d-liste" id="d-goldinfo"><div class="d-h">Heute</div></div></div>
    </section>
    <section class="d-seite" data-s="agenten">
      <div class="d-kopf"><div><h1>Agenten &amp; Aufgaben</h1><div class="unter" id="d-ag-unter">Was ORB gerade im Hintergrund erledigt</div></div></div>
      <div class="d-karte d-liste" id="d-agliste" style="flex:1"></div>
    </section>
    <section class="d-seite" data-s="chat">
      <div class="d-kopf"><div><h1>Gespräch</h1><div class="unter">Alles, was du mit ORB besprochen hast</div></div></div>
      <div id="d-chatplatz"></div>
    </section>
  </main>`;
  document.body.prepend(d); document.body.prepend(bg);

  // ---------- Design & Thema ----------
  const chat = $d('chatp'), chatHeim = chat && chat.parentNode, chatNach = chat && chat.nextSibling;
  function designSetzen(an) {
    document.body.classList.toggle('dash', an); ls('orb_design', an ? 'glas' : 'klassisch');
    if (chat) { if (an) $d('d-chatplatz').appendChild(chat); else chatHeim.insertBefore(chat, chatNach); }
    try { LAY = layout(); } catch (e) {}
  }
  function modusSetzen(m) {
    document.documentElement.dataset.modus = m; ls('orb_modus', m);
    document.querySelectorAll('.d-modus button').forEach(b => b.classList.toggle('an', b.dataset.m === m));
    if (seite === 'trading' && typeof chartLaden === 'function') chartLaden((document.querySelector('#d-tf .an') || {}).dataset?.tf || '15');
  }
  function themaSetzen(t) {
    if (t === 'nacht') { t = 'koralle'; modusSetzen('dunkel'); }   // altes „Nacht“-Thema
    document.documentElement.dataset.thema = t; ls('orb_thema', t);
    const kugel = { koralle:'rot', sand:'cyan', salbei:'gruen', ozean:'blau', lavendel:'lila', gold:'gold', rose:'rot' }[t];
    try { if (kugel && typeof farbeGleiten === 'function') farbeGleiten(kugel); } catch (e) {}   // Kugel färbt sich passend zum Thema
    document.querySelectorAll('[data-t]').forEach(b => b.classList.toggle('an', b.dataset.t === t));
  }
  const qp = new URLSearchParams(location.search);   // Test: /?thema=nacht&seite=trading
  let seite = 'home';
  modusSetzen(qp.get('modus') || ls('orb_modus') || 'hell');
  themaSetzen(qp.get('thema') || ls('orb_thema') || 'koralle');
  designSetzen(true);   // altes Design gibt es nicht mehr
  $d('d-farbe').onclick = e => { e.stopPropagation(); $d('d-themen').classList.toggle('an'); };
  document.addEventListener('click', e => { const t = e.target.closest('[data-t]'), m = e.target.closest('[data-m]');
    if (t) themaSetzen(t.dataset.t); if (m) { e.stopPropagation(); modusSetzen(m.dataset.m); } }, true);
  // Einstellungen aufräumen: alte Farbwahl & Widget-Optionen ausblenden, Hell/Dunkel + Farbthema einsetzen
  (function einstellungen() {
    const sw = $d('swatches'), row = sw && sw.closest('.row');
    if (row) {
      row.classList.add('d-weg');
      const neu = document.createElement('div'); neu.className = 'row col';
      neu.innerHTML = `Darstellung<div class="d-modus"><button data-m="hell">☀ Hell</button><button data-m="dunkel">☾ Dunkel</button></div>
        <div style="margin-top:12px">Farbthema</div><div class="d-farbpunkte">${THEMEN.map(([k, n, g]) => `<button data-t="${k}" title="${n}" style="background:${g}"></button>`).join('')}</div>`;
      row.parentNode.insertBefore(neu, row);
    }
    const rl = $d('resetLayout'); if (rl) rl.closest('.row').classList.add('d-weg');
    const wl = $d('wlist'); if (wl) wl.closest('.grp').classList.add('d-weg');
    const un = $d('s_unter'); if (un) un.closest('.row').classList.add('d-weg');   // Antwort steht in der Hauptkarte
    const mu = $d('s_musik'); if (mu) mu.closest('.row').firstChild.textContent = 'Bei Musik: Klatschen nur bei deutlichem Knall';
    modusSetzen(document.documentElement.dataset.modus || 'hell'); themaSetzen(document.documentElement.dataset.thema || 'koralle');
  })();
  addEventListener('click', e => { if (!e.target.closest('#d-themen')) $d('d-themen').classList.remove('an'); });

  // ---------- Seiten ----------
  function geh(s) {
    seite = s;
    document.querySelectorAll('#d-rail [data-s]').forEach(b => b.classList.toggle('an', b.dataset.s === s));
    document.querySelectorAll('.d-seite').forEach(x => x.classList.toggle('an', x.dataset.s === s));
    if (s === 'trading' && !$d('d-chart').firstChild) chartLaden('15');
    if (s === 'chat') setTimeout(() => { const m = $d('msgs'); if (m) m.scrollTop = m.scrollHeight; }, 50);
  }
  function chartLaden(tf) {
    const dunkel = document.documentElement.dataset.modus === 'dunkel' ? 'dark' : 'light';
    $d('d-chart').innerHTML = `<iframe src="https://s.tradingview.com/widgetembed/?symbol=VANTAGE%3AXAUUSD&interval=${tf}&theme=${dunkel}&style=1&locale=de_DE&hide_side_toolbar=0&allow_symbol_change=1&saveimage=0&studies=%5B%5D" loading="lazy"></iframe>`;
  }
  document.querySelectorAll('#d-tf button').forEach(b => b.onclick = () => {
    document.querySelectorAll('#d-tf button').forEach(x => x.classList.toggle('an', x === b)); chartLaden(b.dataset.tf); });
  $d('d-tv').onclick = () => fetch('/tradingview', { method:'POST', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify({ symbol:'VANTAGE:XAUUSD' }) }).catch(() => {});
  document.querySelectorAll('#d-rail [data-s]').forEach(b => b.onclick = () => geh(b.dataset.s));
  // Seitenleiste auf-/zuklappen (wie im Video), Zustand merken
  const railBreit = an => { document.body.classList.toggle('d-breit', an); ls('orb_rail', an ? '1' : '0'); };
  railBreit(qp.get('breit') === '1' || ls('orb_rail') === '1');
  $d('d-auf').onclick = () => railBreit(!document.body.classList.contains('d-breit'));
  // Text an ORB schicken (oben, Seitenleiste, Kalender, Schnellaktionen)
  function anOrb(v) {
    const t = $d('txt'), s2 = $d('send'); if (!v || !t || !s2) return;
    t.value = v; t.dispatchEvent(new Event('input', { bubbles:true })); s2.click();
  }
  ['d-frag', 'd-suche'].forEach(id => { const f = $d(id); f.onsubmit = () => { const i = f.querySelector('input'); anOrb(i.value.trim()); i.value = ''; i.blur(); return false; }; });
  d.querySelectorAll('.d-aktion').forEach(b => b.onclick = () => { anOrb(b.dataset.cmd); b.classList.add('klick'); setTimeout(() => b.classList.remove('klick'), 500); });
  $d('d-bl-musik').onclick = () => $d('d-musik').click();
  d.querySelectorAll('[data-geh]').forEach(b => b.addEventListener('click', () => geh(b.dataset.geh)));
  $d('d-set').onclick = () => $d('gear') && $d('gear').click();
  $d('d-stop').onclick = () => $d('stopb') && $d('stopb').click();
  const mic = $d('mic'), dmic = $d('d-mic');
  ['pointerdown', 'pointerup', 'pointerleave', 'pointercancel', 'click'].forEach(ev => dmic.addEventListener(ev, e => {
    if (mic) mic.dispatchEvent(new PointerEvent(ev, { bubbles:true, pointerId:e.pointerId, button:e.button, buttons:e.buttons }));
  }));
  $d('d-neu').onclick = () => { geh('home'); const i = $d('d-eingabe'); i.focus(); i.placeholder = 'Was soll ORB erledigen?'; };
  $d('d-form').onsubmit = () => { anOrb($d('d-eingabe').value.trim()); $d('d-eingabe').value = ''; return false; };

  // ---------- Zahlen hochzählen ----------
  function zaehlen(el, ziel, fmt = v => Math.round(v)) {
    if (!el) return; const von = parseFloat(el.dataset.v || '0') || 0; el.dataset.v = ziel;
    if (von === ziel) { el.textContent = fmt(ziel); return; }
    const t0 = performance.now(), dauer = 900;
    (function s() { const u = Math.max(0, Math.min(1, (performance.now() - t0) / dauer)), e = 1 - Math.pow(1 - u, 3);
      el.textContent = fmt(von + (ziel - von) * e); if (u < 1) requestAnimationFrame(s); })();
  }
  function spark(id, werte) {
    const el = $d(id), v = werte.filter(x => typeof x === 'number'); if (!el || v.length < 2) return;
    const lo = Math.min(...v), hi = Math.max(...v), r = hi - lo || 1;
    el.setAttribute('d', 'M' + v.map((x, i) => `${(i / (v.length - 1) * 100).toFixed(1)},${(24 - (x - lo) / r * 22).toFixed(1)}`).join(' L'));
  }
  const cpuVerlauf = [], agVerlauf = [];
  const usd = v => '$' + v.toLocaleString('en-US', { minimumFractionDigits:2, maximumFractionDigits:2 });

  // ---------- Begrüßung, Datum, Tagesring ----------
  const WT = ['Sonntag', 'Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag'];
  let termine = [], agenten = [];
  function zeit() {
    const n = new Date(), h = n.getHours();
    $d('d-gruss').textContent = (h < 5 ? 'Gute Nacht' : h < 11 ? 'Guten Morgen' : h < 17 ? 'Guten Tag' : h < 22 ? 'Guten Abend' : 'Gute Nacht') + ', Larsen';
    const heute = termine.filter(t => t.diff === 0).length, offen = heute + agenten.filter(a => a.status === 'laeuft').length;
    $d('d-unter').innerHTML = `${WT[n.getDay()]}, ${n.getDate()}. ${n.toLocaleDateString('de-DE', { month:'long' })} · ` +
      (offen ? `<b>${offen} ${offen === 1 ? 'Ding braucht' : 'Dinge brauchen'}</b> deine Aufmerksamkeit` : 'Alles im Griff');
    $d('d-tag').textContent = String(n.getDate()).padStart(2, '0'); $d('d-wt').textContent = WT[n.getDay()];
    const p = Math.max(0, Math.min(1, (h + n.getMinutes() / 60 - 6) / 18));   // 06–24 Uhr
    $d('d-bogen').style.strokeDashoffset = 289 * (1 - p);
    $d('d-proz').textContent = `Tag zu ${Math.round(p * 100)} % geschafft`;
  }
  function woche() {
    const n = new Date(); n.setHours(0, 0, 0, 0); const mo = new Date(n); mo.setDate(n.getDate() - ((n.getDay() + 6) % 7));
    const hat = new Set(termine.map(t => t.datum));
    $d('d-woche').innerHTML = [...Array(7)].map((_, i) => { const x = new Date(mo); x.setDate(mo.getDate() + i);
      const iso = x.toLocaleDateString('sv-SE'); return `<div class="${+x === +n ? 'heute' : ''} ${hat.has(iso) ? 'hat' : ''}">${'MDMDFSS'[i]}<b>${x.getDate()}</b></div>`; }).join('');
  }

  // ---------- Termine ----------
  async function ladeTermine() {
    try {
      const j = await (await fetch('/termine', { cache:'no-store' })).json(), h0 = new Date(); h0.setHours(0, 0, 0, 0);
      termine = (j.termine || []).map(t => ({ ...t, diff:Math.round((new Date(t.datum + 'T00:00') - h0) / 864e5) })).filter(t => t.diff >= 0);
      const heute = termine.filter(t => t.diff === 0);
      $d('d-mon').textContent = new Date().toLocaleDateString('de-DE', { month:'long', year:'numeric' }) + ` · ${heute.length} ${heute.length === 1 ? 'Termin' : 'Termine'}`;
      zaehlen($d('d-w1'), heute.length);
      const jetzt = new Date(), min = jetzt.getHours() * 60 + jetzt.getMinutes();
      $d('d-termine').innerHTML = termine.length ? termine.slice(0, 8).map((t, i) => {
        const [hh, mm] = String(t.zeit || '').split(/[:.]/).map(Number), tm = hh * 60 + (mm || 0);
        const bald = t.diff === 0 && t.zeit && tm - min > -30 && tm - min < 60;
        const tag = t.diff === 0 ? 'Heute' : t.diff === 1 ? 'Morgen' : new Date(t.datum + 'T00:00').toLocaleDateString('de-DE', { weekday:'short', day:'numeric', month:'numeric' });
        return `<div class="t" style="animation-delay:${.05 * i}s"><div class="z">${escH(t.zeit || '—')}</div><div style="min-width:0"><div class="n">${escH(t.text)}</div><div class="o">${tag}</div></div>${bald ? '<span class="neu">Gleich</span>' : ''}</div>`;
      }).join('') : '<div class="leer">Keine Termine. Sag z. B. „Termin morgen um 15 Uhr Zahnarzt“.</div>';
      woche(); zeit();
    } catch (e) {}
  }

  // ---------- Gold ----------
  const goldVerlauf = [];
  async function ladeGold() {
    try {
      const j = await (await fetch('/gold', { cache:'no-store' })).json(); if (typeof j.preis !== 'number') return;
      zaehlen($d('d-gold'), j.preis, usd);
      goldVerlauf.push(j.preis); if (goldVerlauf.length > 40) goldVerlauf.shift();
      try { const tag = new Date().toDateString(), g = JSON.parse(ls('orb_gold') || '{}');   // eigener Tagesverlauf, falls die Quelle keine Tageswerte liefert
        if (g.tag !== tag) { g.tag = tag; g.start = j.preis; g.hoch = j.preis; g.tief = j.preis; }
        g.hoch = Math.max(g.hoch, j.preis); g.tief = Math.min(g.tief, j.preis); ls('orb_gold', JSON.stringify(g));
        j.heute_hoch = j.heute_hoch || g.hoch; j.heute_tief = j.heute_tief || g.tief; j.tag_start = g.start; } catch (e) {}
      const ref = j.vortag_schluss || j.tag_start || goldVerlauf[0], pr = typeof j.veraenderung === 'number' ? j.veraenderung : ref ? (j.preis - ref) / ref * 100 : 0;
      const b = $d('d-gold-d'); b.textContent = (pr >= 0 ? '▲ +' : '▼ ') + pr.toFixed(2) + ' %'; b.className = 'los bad ' + (pr >= 0 ? 'up' : 'dn');
      $d('d-w3').textContent = (pr >= 0 ? '+' : '') + pr.toFixed(1) + ' %';
      const v = [j.vortag_tief, j.vortag_hoch, j.vortag_schluss, j.heute_tief, j.heute_hoch, ...goldVerlauf].filter(x => typeof x === 'number');
      const lo = Math.min(...v), hi = Math.max(...v), r = hi - lo || 1, pts = v.map((x, i) => `${(i / (v.length - 1 || 1) * 100).toFixed(1)},${(24 - (x - lo) / r * 22).toFixed(1)}`);
      $d('d-spark').setAttribute('d', 'M' + pts.join(' L'));
      const z = (k, w) => w == null ? '' : `<div class="d-agent"><div class="s" style="margin:0">${k}</div><div class="k" style="font-size:18px">${w}</div></div>`;
      const st = (ik, k, w, pill, pk) => `<div class="d-karte d-stat"><div class="d-h"><span class="ik">${ik}</span>${k}</div><div class="zahl">${w}</div>${pill ? `<span class="bad ${pk}">${pill}</span>` : ''}</div>`;
      const spanne = j.heute_hoch && j.heute_tief ? j.heute_hoch - j.heute_tief : null;
      $d('d-tstats').innerHTML = st('$', 'Gold jetzt', usd(j.preis), (pr >= 0 ? '▲ +' : '▼ ') + pr.toFixed(2) + ' %', pr >= 0 ? 'up' : 'dn') +
        st('↑', 'Tageshoch', j.heute_hoch ? usd(j.heute_hoch) : '–', '', '') + st('↓', 'Tagestief', j.heute_tief ? usd(j.heute_tief) : '–', '', '') +
        st('↔', 'Tagesspanne', spanne ? usd(spanne) : '–', j.session ? escH(j.session) : '', '');
      $d('d-goldinfo').innerHTML = '<div class="d-h">Heute</div>' + z('Aktueller Preis', usd(j.preis)) + z('Tageshoch', j.heute_hoch && usd(j.heute_hoch)) +
        z('Tagestief', j.heute_tief && usd(j.heute_tief)) + z('Vortag (Schluss)', j.vortag_schluss && usd(j.vortag_schluss)) + z('Session', j.session && escH(j.session));
    } catch (e) {}
  }

  // ---------- System, Wetter, Musik ----------
  async function ladeSys() {
    try { const s = await (await fetch('/sys')).json();
      if (s.cpu != null && s.cpu >= 0 && s.cpu <= 100) { zaehlen($d('d-cpu'), s.cpu, v => Math.round(v) + ' %'); cpuVerlauf.push(s.cpu); if (cpuVerlauf.length > 30) cpuVerlauf.shift(); spark('d-spark-cpu', cpuVerlauf); }
      if (s.ram != null) $d('d-ram').textContent = 'RAM ' + Math.round(s.ram) + ' %'; } catch (e) {}
  }
  async function ladeWetter() {
    try { const w = await (await fetch('/weather')).json(); if (w && w.temp != null) $d('d-wx').textContent = Math.round(w.temp) + '° ' + (w.text || w.beschreibung || ''); } catch (e) {}
  }
  async function ladeMusik() {
    try { const s = await (await fetch('/spotify', { cache:'no-store' })).json();
      $d('d-mu').textContent = s.spielt ? s.titel : s.laeuft ? 'Pausiert' : 'Gerade keine Musik';
      $d('d-mu-a').textContent = s.spielt ? s.kuenstler : s.laeuft ? 'Spotify' : 'Sag „spiel Musik“';
      $d('d-mu-b').textContent = s.spielt ? '▶ läuft' : 'Spotify'; $d('d-musik').classList.toggle('spielt', !!s.spielt); } catch (e) {}
  }
  $d('d-musik').onclick = () => fetch('/media', { method:'POST', headers:{ 'Content-Type':'application/json' }, body:JSON.stringify({ cmd:'play' }) }).then(() => setTimeout(ladeMusik, 400)).catch(() => {});

  // ---------- Agenten (aus ORBs Zustand) ----------
  if (typeof renderTasks === 'function') {
    const alt = renderTasks;
    renderTasks = list => { alt(list); try { agentenZeigen(list || []); } catch (e) {} };
  }
  let agK = '';
  function agentenZeigen(list) {
    agenten = list; const lauf = list.filter(a => a.status === 'laeuft');
    zaehlen($d('d-w2'), lauf.length); zaehlen($d('d-ag'), lauf.length);
    agVerlauf.push(lauf.length); if (agVerlauf.length > 30) agVerlauf.shift(); spark('d-spark-ag', agVerlauf.length > 1 ? agVerlauf : [0, 0]);
    $d('d-ag-l').textContent = lauf.length ? (lauf[0].titel || 'Aufgabe') + (lauf.length > 1 ? ` + ${lauf.length - 1}` : '') : 'gerade frei';
    const k = JSON.stringify(list.map(a => [a.id, a.status, a.schritt, a.prozent])); if (k === agK) return; agK = k;
    $d('d-agliste').innerHTML = list.length ? list.map((a, i) => `<div class="d-agent ${a.status === 'laeuft' ? '' : 'fertig'}" style="animation-delay:${i * .05}s">
      <div class="k"><i></i>${escH(a.titel || 'Aufgabe')}<span style="margin-left:auto;font-size:12px;opacity:.6">${a.status === 'laeuft' ? (a.prozent ? a.prozent + ' %' : 'läuft') : 'fertig'}</span></div>
      <div class="s">${escH(a.schritt || a.ergebnis || a.auftrag || '')}</div>
      <div class="balken ${a.status === 'laeuft' && !a.prozent ? 'unbest' : ''}"><b style="width:${a.status === 'laeuft' ? (a.prozent || 0) : 100}%"></b></div></div>`).join('')
      : '<div class="leer" style="color:var(--d-sub);font-size:13px">Gerade läuft nichts im Hintergrund. Gib ORB einen größeren Auftrag – er bekommt dann hier einen eigenen Eintrag.</div>';
    zeit();
  }

  // ---------- ORBs Zustand spiegeln (Status, Hauptkarte, letzte Antwort) ----------
  const antwortText = m => m.textContent.replace(/\s*\d{1,2}:\d{2}\s*$/, '').trim();   // Uhrzeit der Nachricht nicht mitlesen
  let txtAlt = '';
  setInterval(() => {
    if (!document.body.classList.contains('dash')) return;
    const st = ($d('status') || {}).textContent || 'Bereit', task = ($d('task') || {}).textContent || '', det = ($d('detail') || {}).textContent || '';
    $d('d-status').textContent = st;
    const hoert = typeof listening !== 'undefined' && (listening || (typeof convoRec !== 'undefined' && convoRec));
    const modus = (typeof S !== 'undefined' && S.mode) || '';
    document.body.classList.toggle('d-hoert', !!hoert);
    const lauf = agenten.filter(a => a.status === 'laeuft').length;
    let titel = 'Dein Tag läuft <em>rund</em>', chip = 'ORB ist bereit', txt = 'Sag „Jarvis“ oder klatsch zweimal – ich bin da.';
    if (hoert) { titel = 'Ich <em>höre</em> dir zu'; chip = 'Hört zu'; txt = 'Sprich einfach – ich schreibe mit.'; }
    else if (modus === 'denkt' || modus === 'auftrag') { titel = 'Ich bin <em>dran</em>'; chip = 'Arbeitet'; txt = (task && task !== 'Bereit' ? task + (det ? ' – ' + det : '') : 'Einen Moment …'); }
    else if (modus === 'spricht') { titel = 'Hier ist deine <em>Antwort</em>'; chip = 'Spricht'; const m = [...document.querySelectorAll('#msgs .msg.orb')].pop(); if (m) txt = antwortText(m).slice(0, 160); }
    else if (lauf) { titel = `${lauf} ${lauf === 1 ? 'Agent ist' : 'Agenten sind'} <em>fleißig</em>`; chip = `${lauf} im Hintergrund`; txt = agenten.filter(a => a.status === 'laeuft').map(a => a.titel + ': ' + (a.schritt || 'läuft')).join(' · ').slice(0, 170); }
    else if (typeof S !== 'undefined' && S.sleep) { titel = 'Ich <em>ruhe</em> mich aus'; chip = 'Schläft'; txt = 'Klatsch zweimal, dann bin ich sofort wieder da.'; }
    if ($d('d-titel').innerHTML !== titel) { const h = $d('d-titel'); h.style.animation = 'none'; h.offsetHeight; h.style.animation = 'd-rein .6s var(--d-ease)'; h.innerHTML = titel; }
    $d('d-chip').textContent = chip;
    if (txt !== txtAlt) { txtAlt = txt; $d('d-txt').textContent = txt; }
    const m = [...document.querySelectorAll('#msgs .msg.orb')].pop(); $d('d-antwort').textContent = m ? antwortText(m).slice(0, 220) : '';
  }, 400);

  // ---------- Kugel in den Ring setzen (gleitet mit, wenn die Seite wechselt) ----------
  const ziel = { x:innerWidth / 2, y:innerHeight * .44, r:100 }, ist = { ...ziel };
  window.DASH_LAY = () => ({ mid:ist.x, cw:innerWidth, cy:ist.y, rb:ist.r });
  function zielBerechnen() {
    const el = seite === 'home' ? $d('d-kugel') : document.querySelector('#d-rail .orb');
    const r = el && el.getBoundingClientRect(); if (!r || !r.width) return;
    ziel.x = r.left + r.width / 2; ziel.y = r.top + r.height / 2; ziel.r = seite === 'home' ? r.width * .34 : r.width * .5;
  }
  (function gleiten() {
    requestAnimationFrame(gleiten);
    if (!document.body.classList.contains('dash') || document.body.classList.contains('mini')) return;
    zielBerechnen();
    ist.x += (ziel.x - ist.x) * .12; ist.y += (ziel.y - ist.y) * .12; ist.r += (ziel.r - ist.r) * .12;
    try { LAY = window.DASH_LAY(); } catch (e) {}
  })();

  // Rechtsklick-Menü des Browsers abschalten (in Eingabefeldern bleibt es für Kopieren/Einfügen)
  addEventListener('contextmenu', e => { if (!e.target.closest('input, textarea, [contenteditable]')) e.preventDefault(); });
  // ---------- Lichtfleck folgt der Maus auf jeder Karte ----------
  d.addEventListener('pointermove', e => { const k = e.target.closest('.d-karte'); if (!k) return; const r = k.getBoundingClientRect();
    k.style.setProperty('--mx', (e.clientX - r.left) + 'px'); k.style.setProperty('--my', (e.clientY - r.top) + 'px'); });
  // Lichtkante folgt
  // ---------- Hintergrund folgt leicht der Maus ----------
  addEventListener('mousemove', e => {
    document.documentElement.style.setProperty('--d-px', ((e.clientX / innerWidth - .5) * -14).toFixed(1) + 'px');
    document.documentElement.style.setProperty('--d-py', ((e.clientY / innerHeight - .5) * -10).toFixed(1) + 'px');
  });

  if (qp.get('seite')) geh(qp.get('seite'));
  if (qp.get('set')) setTimeout(() => $d('gear') && $d('gear').click(), 1500);
  zeit(); woche(); ladeTermine(); ladeGold(); ladeSys(); ladeWetter(); ladeMusik();
  setInterval(zeit, 30000); setInterval(ladeTermine, 30000); setInterval(ladeGold, 20000);
  setInterval(ladeSys, 3000); setInterval(ladeWetter, 600000); setInterval(ladeMusik, 4000);
})();
