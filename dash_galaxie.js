/* Galaxie-Hintergrund für das ORB-Dashboard – passend zu Second Brain (Jarvis Brain).
   Ein einziger WebGL-Shader: Sternenhimmel + Nebel + Schwarzes Loch mit echter Lichtkrümmung (Schwarzschild) –
   seit Version 192 nur noch Sterne und Nebel: das Schwarze Loch ist die ORB-Kugel selbst.
   Sparsam: halbe Auflösung, max. 30 Bilder/s, pausiert wenn ORB versteckt, im Spar-Modus nur ein Standbild. */
(() => {
  const bg = document.getElementById('dbg');
  if (!bg || document.getElementById('d-galaxie')) return;
  const cv = document.createElement('canvas'); cv.id = 'd-galaxie'; bg.appendChild(cv);
  const gl = cv.getContext('webgl', { antialias: false, alpha: false, depth: false, powerPreference: 'low-power', preserveDrawingBuffer: false });
  if (!gl) { bg.classList.add('d-galaxie-aus'); return; }
  document.documentElement.classList.add('galaxie');

  const VS = 'attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}';
  const FS = `precision highp float;
uniform vec2 uRes;uniform float uTime,uZoom;uniform vec3 uAcc;
float h1(vec3 p){p=fract(p*.3183099+.1);p*=17.;return fract(p.x*p.y*p.z*(p.x+p.y+p.z));}
float h2(vec2 p){p=fract(p*vec2(123.34,456.21));p+=dot(p,p+45.32);return fract(p.x*p.y);}
float n2(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(h2(i),h2(i+vec2(1,0)),f.x),mix(h2(i+vec2(0,1)),h2(i+vec2(1,1)),f.x),f.y);}
float fbm(vec2 p){float v=0.,a=.5;for(int i=0;i<5;i++){v+=a*n2(p);p=p*2.03+vec2(1.7,9.2);a*=.5;}return v;}
vec3 sky(vec3 d){
  vec3 c=vec3(0.);
  for(int l=0;l<3;l++){
    float sc=90.+float(l)*70.;vec3 q=d*sc;vec3 id=floor(q);vec3 f=fract(q)-.5;float h=h1(id);
    if(h>.982){float tw=.65+.35*sin(uTime*(1.+h*3.)+h*50.);vec3 col=mix(vec3(1.,.84,.68),vec3(.74,.84,1.),h1(id+7.));c+=col*smoothstep(.16,0.,length(f))*tw*(1.4-float(l)*.35);}
  }
  vec2 uv=vec2(atan(d.z,d.x),asin(clamp(d.y,-1.,1.)));
  float band=exp(-pow((d.y+.18*sin(uv.x*1.3))/.22,2.));
  float neb=fbm(uv*vec2(1.6,3.)+vec2(uTime*.004,0.));
  float neb2=fbm(uv*vec2(3.2,6.)-vec2(0.,uTime*.003));
  vec3 tint=mix(vec3(.85,.8,.75),uAcc,.55);
  c+=tint*pow(neb,3.)*band*.55+vec3(.6,.62,.75)*pow(neb2,4.)*.18;
  return c;
}
void main(){
  vec2 fc=gl_FragCoord.xy;float asp=uRes.x/uRes.y;
  vec2 uv=(fc/uRes-vec2(.62,.47))*vec2(asp,1.)*1.05;
  float a=uTime*.018,R=uZoom;
  vec3 ro=vec3(sin(a)*R,R*(.085+.03*sin(uTime*.05)),cos(a)*R);
  vec3 fw=normalize(-ro),rt=normalize(cross(vec3(0.,1.,0.),fw)),up=cross(fw,rt);
  vec3 rd=normalize(fw+uv.x*rt+uv.y*up);
  vec3 col=vec3(0.);float al=0.;
  float b=dot(ro,rd),cc=dot(ro,ro)-196.,h=b*b-cc;
  vec3 d=rd;
  if(h>0.&&false){   // das Schwarze Loch ist jetzt die ORB-Kugel selbst – im Hintergrund nur Sterne und Nebel
    vec3 p=ro+rd*max(-b-sqrt(h),0.);
    vec3 hc=cross(p,d);float h2v=dot(hc,hc);bool hole=false;
    for(int i=0;i<170;i++){
      float r=length(p);float dt=clamp(.05*r,.015,.7);
      d=normalize(d-1.5*h2v*p/pow(r,5.)*dt);
      vec3 np=p+d*dt;
      if(p.y*np.y<0.){
        vec3 q=mix(p,np,p.y/(p.y-np.y));float rr=length(q.xz);
        if(rr>2.45&&rr<10.5){
          float ang=atan(q.z,q.x),ph=ang-uTime*pow(rr,-1.5)*1.1;
          vec2 dv=vec2(cos(ph),sin(ph))*rr;
          float n=fbm(dv*1.1+vec2(rr*1.9,-rr*.7));
          float prof=smoothstep(2.45,3.,rr)*(1.-smoothstep(5.,10.5,rr))*pow(3./rr,2.);
          vec3 vel=vec3(-sin(ang),0.,cos(ang))*min(.6,sqrt(.5/max(rr-1.,.5)));
          float beam=clamp(pow(1./(1.+dot(vel,d)),3.),.12,3.2);
          float I=prof*(.25+1.15*n*(.75+.25*sin(rr*5.+n*7.)))*beam*1.8;
          vec3 warm=mix(vec3(1.,.72,.42),uAcc,.22),deep=vec3(.85,.42,.18);
          vec3 c2=mix(deep,warm,clamp(I*.9,0.,1.));c2=mix(c2,vec3(1.,.97,.92),clamp(I*.45-.2,0.,1.));
          col+=(1.-al)*c2*I;al+=(1.-al)*clamp(I*1.15,0.,.97);
        }
      }
      p=np;
      if(length(p)<1.){hole=true;break;}
      if(length(p)>14.5&&dot(p,d)>0.)break;
      if(al>.99)break;
    }
    if(hole)al=1.;
  }
  col+=(1.-al)*sky(d);
  float v=1.-.55*smoothstep(.45,1.25,length((fc/uRes-.5)*vec2(asp*.8,1.)));
  gl_FragColor=vec4(col*v,1.);
}`;
  const sh = (t, src) => { const s = gl.createShader(t); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; };
  let prog;
  try { prog = gl.createProgram(); gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(prog); }
  catch (e) { console.warn('Galaxie:', e); bg.classList.add('d-galaxie-aus'); return; }
  gl.useProgram(prog);
  const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, 'p'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const U = n => gl.getUniformLocation(prog, n);
  const uRes = U('uRes'), uTime = U('uTime'), uZoom = U('uZoom'), uAcc = U('uAcc');

  // Akzentfarbe aus dem gewählten Farbthema (färbt Nebel und Scheibe leicht)
  let acc = [0.95, 0.75, 0.5];
  const farbe = () => {
    const v = getComputedStyle(document.documentElement).getPropertyValue('--d-acc1').trim();
    const m = v.match(/^#?([0-9a-f]{6})$/i);
    if (m) { const n = parseInt(m[1], 16); acc = [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255]; }
  };
  farbe(); new MutationObserver(farbe).observe(document.documentElement, { attributes: true, attributeFilter: ['data-thema'] });

  const SKALA = Math.min(devicePixelRatio || 1, 2);   // volle Auflösung bis 4K – ohne Loch im Hintergrund ist der Shader leicht
  const groesse = () => { const w = Math.max(2, Math.round(innerWidth * SKALA)), h = Math.max(2, Math.round(innerHeight * SKALA)); if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; gl.viewport(0, 0, w, h); } };
  addEventListener('resize', groesse); groesse();

  const t0 = performance.now(); let letzt = 0, zoom = 46;
  const spar = () => document.body.classList.contains('lite') || document.body.classList.contains('mini');
  function malen(now) {
    const t = (now - t0) / 1000;
    // Start: Kamera fliegt aus der Ferne auf das Schwarze Loch zu (passend zum ORB-Intro)
    const ziel = 26; zoom += (ziel - zoom) * (document.body.classList.contains('d-intro') ? .012 : .03);
    gl.uniform2f(uRes, cv.width, cv.height); gl.uniform1f(uTime, t); gl.uniform1f(uZoom, zoom); gl.uniform3f(uAcc, acc[0], acc[1], acc[2]);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
  function schleife(now) {
    requestAnimationFrame(schleife);
    if (document.hidden || spar()) { if (!letzt) { malen(now); letzt = now; } return; }
    if (now - letzt < 33) return;   // max. 30 Bilder/s
    letzt = now; malen(now);
  }
  requestAnimationFrame(schleife);
  // Rundes Fenster in der Hauptkarte: dort ist das Schwarze Loch (die ORB-Kugel) klar und tiefschwarz zu sehen
  setInterval(() => {
    const held = document.getElementById('d-held'), k = document.getElementById('d-kugel'); if (!held || !k) return;
    const a = held.getBoundingClientRect(), b = k.getBoundingClientRect(); if (!b.width) return;
    held.style.setProperty('--bhx', (b.left + b.width / 2 - a.left).toFixed(0) + 'px');
    held.style.setProperty('--bhy', (b.top + b.height / 2 - a.top).toFixed(0) + 'px');
    held.style.setProperty('--bhr', (b.width * .62).toFixed(0) + 'px');
  }, 400);
})();
