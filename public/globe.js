// Informa AI "Signal Globe": a dependency-free WebGL globe of regional technology coverage.
// Dots trace coarse continents, hubs mark publisher regions, and light pulses travel the
// arcs between them. The globe is decoration plus a shortcut: every hub is also exposed as
// a real button by the page, so nothing here is required to read or filter the news.

const TAU = Math.PI * 2;

// Coarse continent outlines as [longitude, latitude] rings. Recognisable at globe scale,
// not cartographically exact.
const LAND = [
  [[-168, 66], [-160, 71], [-140, 70], [-120, 73], [-95, 72], [-82, 73], [-64, 61], [-56, 52], [-66, 44], [-75, 35],
   [-81, 25], [-90, 30], [-97, 26], [-97, 19], [-88, 15], [-83, 9], [-78, 8], [-86, 12], [-92, 15], [-105, 19],
   [-110, 23], [-117, 32], [-124, 40], [-125, 48], [-133, 56], [-150, 60], [-166, 60]],
  [[-80, 10], [-73, 12], [-62, 10], [-50, 0], [-35, -6], [-39, -15], [-48, -26], [-58, -35], [-65, -42],
   [-69, -52], [-75, -50], [-73, -37], [-71, -18], [-77, -12], [-81, -5], [-78, 2]],
  [[-55, 60], [-42, 60], [-20, 70], [-20, 80], [-40, 83], [-62, 82], [-72, 77], [-56, 70]],
  [[-10, 36], [-9, 43], [-2, 44], [-4, 48], [2, 51], [8, 54], [9, 58], [5, 62], [14, 69], [28, 71], [41, 67],
   [40, 60], [31, 55], [31, 46], [40, 44], [28, 41], [23, 37], [15, 38], [12, 44], [3, 42]],
  [[-6, 50], [1, 51], [2, 53], [-2, 57], [-5, 58], [-6, 55]],
  [[-17, 15], [-16, 22], [-10, 30], [-5, 36], [10, 37], [20, 32], [32, 31], [35, 28], [43, 12], [51, 12],
   [42, -2], [40, -15], [35, -25], [20, -35], [17, -29], [12, -17], [13, -6], [9, 4], [-5, 5], [-12, 8]],
  [[44, -25], [47, -25], [50, -15], [49, -12], [44, -17]],
  [[35, 28], [43, 12], [52, 15], [59, 22], [56, 26], [50, 30], [48, 30], [36, 33]],
  [[28, 41], [40, 44], [48, 41], [55, 37], [57, 25], [62, 25], [67, 24], [72, 21], [77, 8], [80, 15], [88, 22],
   [92, 22], [98, 16], [100, 13], [103, 1], [105, 10], [109, 12], [107, 21], [118, 24], [122, 30], [121, 40],
   [125, 40], [129, 35], [131, 43], [140, 48], [143, 59], [160, 61], [170, 66], [180, 68], [180, 72], [140, 73],
   [110, 77], [80, 73], [60, 70], [45, 68], [41, 67], [40, 60], [31, 55], [31, 46], [40, 44]],
  [[95, 5], [105, -6], [115, -8], [125, -9], [135, -4], [141, -3], [130, 1], [119, 5], [110, 2], [100, 3]],
  [[130, 31], [135, 34], [141, 38], [142, 45], [140, 41], [133, 34]],
  [[114, -22], [122, -18], [130, -12], [137, -12], [142, -11], [146, -19], [153, -26], [150, -37], [141, -38],
   [131, -31], [116, -35], [114, -26]],
  [[172, -34], [178, -38], [174, -41], [167, -46], [170, -46]],
];

// Publisher regions used by the Reading Room's region filter.
export const HUBS = [
  { id: "NA", label: "North America", lat: 39, lon: -98 },
  { id: "LatAm", label: "Latin America & Caribbean", lat: -14, lon: -58 },
  { id: "EU", label: "Europe", lat: 50, lon: 10 },
  { id: "Africa", label: "Africa", lat: 3, lon: 21 },
  { id: "MENA", label: "Middle East & North Africa", lat: 26, lon: 44 },
  { id: "APAC", label: "Asia-Pacific", lat: 24, lon: 112 },
];
const LINKS = [["NA", "EU"], ["EU", "APAC"], ["NA", "APAC"], ["EU", "Africa"], ["EU", "MENA"], ["MENA", "APAC"],
  ["NA", "LatAm"], ["LatAm", "EU"], ["Africa", "MENA"], ["APAC", "Africa"]];

export function toVector(lat, lon) {
  const phi = lat * Math.PI / 180, lambda = lon * Math.PI / 180;
  return [Math.cos(phi) * Math.sin(lambda), Math.sin(phi), Math.cos(phi) * Math.cos(lambda)];
}

export function isLand(lat, lon) {
  for (const ring of LAND) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j];
      if ((yi > lat) !== (yj > lat) && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside;
    }
    if (inside) return true;
  }
  return false;
}

// Rotate by yaw (around Y) then pitch (around X); returns view-space coordinates.
export function rotate([x, y, z], yaw, pitch) {
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
  const x1 = x * cy + z * sy, z1 = -x * sy + z * cy;
  return [x1, y * cp - z1 * sp, y * sp + z1 * cp];
}

// Great-circle path lifted off the surface in the middle, for arcs between hubs.
export function arcPoints(a, b, steps = 48) {
  const dot = Math.min(1, Math.max(-1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]));
  const omega = Math.acos(dot), sin = Math.sin(omega) || 1;
  const lift = 0.08 + 0.22 * omega / Math.PI;
  const points = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps, s1 = Math.sin((1 - t) * omega) / sin, s2 = Math.sin(t * omega) / sin;
    const r = 1 + lift * Math.sin(Math.PI * t);
    points.push([(a[0] * s1 + b[0] * s2) * r, (a[1] * s1 + b[1] * s2) * r, (a[2] * s1 + b[2] * s2) * r, t]);
  }
  return points;
}

// Signed smallest turn from one angle to another, in (-PI, PI].
export function shortestAngle(from, to) {
  let delta = (to - from) % TAU;
  if (delta > Math.PI) delta -= TAU;
  if (delta <= -Math.PI) delta += TAU;
  return delta;
}

// Points on a small circle around a surface vector: the expanding "transmission" ripple.
export function ringAround(vector, radius, count = 36) {
  const [x, y, z] = vector;
  // Any vector not parallel to the normal gives a tangent basis.
  const helper = Math.abs(y) < 0.9 ? [0, 1, 0] : [1, 0, 0];
  let u = [helper[1] * z - helper[2] * y, helper[2] * x - helper[0] * z, helper[0] * y - helper[1] * x];
  const ul = Math.hypot(...u) || 1;
  u = u.map((value) => value / ul);
  const v = [y * u[2] - z * u[1], z * u[0] - x * u[2], x * u[1] - y * u[0]];
  const c = Math.cos(radius), s = Math.sin(radius), points = [];
  for (let i = 0; i < count; i++) {
    const a = (i / count) * TAU, ca = Math.cos(a), sa = Math.sin(a);
    points.push([x * c + (u[0] * ca + v[0] * sa) * s, y * c + (u[1] * ca + v[1] * sa) * s, z * c + (u[2] * ca + v[2] * sa) * s]);
  }
  return points;
}

// Deterministic orbital "satellites": each has an inclined circular orbit around the globe.
export function orbitals(count, seed = 7) {
  let state = seed;
  const random = () => ((state = (state * 16807) % 2147483647) - 1) / 2147483646;
  return Array.from({ length: count }, () => ({
    radius: 1.16 + random() * 0.36, tilt: (random() - 0.5) * 2.2, node: random() * TAU,
    phase: random() * TAU, speed: (0.05 + random() * 0.16) * (random() < 0.2 ? -1 : 1), size: 1.6 + random() * 2.4,
  }));
}

export function orbitalPosition(orbit, time) {
  const a = orbit.phase + time * orbit.speed;
  const px = Math.cos(a) * orbit.radius, pz = Math.sin(a) * orbit.radius;
  // Incline the orbit plane, then spin it around the pole to its ascending node.
  const y = pz * Math.sin(orbit.tilt), z1 = pz * Math.cos(orbit.tilt);
  const cn = Math.cos(orbit.node), sn = Math.sin(orbit.node);
  return [px * cn + z1 * sn, y, -px * sn + z1 * cn];
}

function sphereDots(count) {
  const dots = [], golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < count; i++) {
    const y = 1 - (i / (count - 1)) * 2, radius = Math.sqrt(1 - y * y), theta = golden * i;
    const x = Math.cos(theta) * radius, z = Math.sin(theta) * radius;
    const lat = Math.asin(y) * 180 / Math.PI, lon = Math.atan2(x, z) * 180 / Math.PI;
    dots.push([x, y, z, isLand(lat, lon) ? 1 : 0]);
  }
  return dots;
}

const POINT_VS = `
attribute vec3 aPos; attribute float aSize; attribute vec4 aColor; attribute float aGlow;
uniform float uYaw, uPitch, uScale, uAspect, uDpr;
varying vec4 vColor; varying float vGlow, vFront;
void main() {
  float cy = cos(uYaw), sy = sin(uYaw), cp = cos(uPitch), sp = sin(uPitch);
  vec3 p = vec3(aPos.x * cy + aPos.z * sy, aPos.y, -aPos.x * sy + aPos.z * cy);
  p = vec3(p.x, p.y * cp - p.z * sp, p.y * sp + p.z * cp);
  vFront = p.z; vColor = aColor; vGlow = aGlow;
  gl_Position = vec4(p.x * uScale / uAspect, p.y * uScale, -p.z * 0.5, 1.0);
  gl_PointSize = aSize * uDpr * (0.55 + 0.45 * max(p.z, 0.0));
}`;
const POINT_FS = `
precision mediump float;
varying vec4 vColor; varying float vGlow, vFront;
void main() {
  float d = length(gl_PointCoord - 0.5) * 2.0;
  if (d > 1.0) discard;
  float side = vFront < 0.0 ? 0.16 : 1.0;
  float a = vGlow > 0.0 ? pow(1.0 - d, 1.5) + (1.0 - smoothstep(0.0, 0.3, d)) * 0.8 : 1.0 - smoothstep(0.55, 1.0, d);
  gl_FragColor = vec4(vColor.rgb, vColor.a * a * side);
}`;
const LINE_VS = `
attribute vec4 aPos;
uniform float uYaw, uPitch, uScale, uAspect;
varying float vT, vFront;
void main() {
  float cy = cos(uYaw), sy = sin(uYaw), cp = cos(uPitch), sp = sin(uPitch);
  vec3 p = vec3(aPos.x * cy + aPos.z * sy, aPos.y, -aPos.x * sy + aPos.z * cy);
  p = vec3(p.x, p.y * cp - p.z * sp, p.y * sp + p.z * cp);
  vT = aPos.w; vFront = p.z;
  gl_Position = vec4(p.x * uScale / uAspect, p.y * uScale, -p.z * 0.5, 1.0);
}`;
const LINE_FS = `
precision mediump float;
uniform vec3 uColor;
varying float vT, vFront;
void main() {
  float edge = smoothstep(0.0, 0.12, vT) * (1.0 - smoothstep(0.88, 1.0, vT));
  gl_FragColor = vec4(uColor, (vFront < -0.15 ? 0.06 : 0.45) * edge);
}`;

function program(gl, vs, fs) {
  const compile = (type, source) => {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader) || "shader");
    return shader;
  };
  const prog = gl.createProgram();
  gl.attachShader(prog, compile(gl.VERTEX_SHADER, vs));
  gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error("link");
  return prog;
}

function readPalette(element) {
  const style = getComputedStyle(element);
  const color = (name, fallback) => {
    const value = style.getPropertyValue(name).trim();
    const match = /^#([0-9a-f]{6})$/i.exec(value);
    const hex = match ? match[1] : fallback;
    return [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  };
  return { land: color("--globe-land", "bfefff"), sea: color("--globe-sea", "4f7fb8"),
    hub: color("--globe-hub", "5fe3ff"), active: color("--globe-active", "ffffff"), arc: color("--globe-arc", "7dd3fc") };
}

/**
 * Mount the globe on a canvas. Returns null when WebGL is unavailable so callers can keep
 * their accessible fallback. Options: onHover(hub|null, x, y), onSelect(hub).
 */
export function createGlobe(canvas, { onHover = () => {}, onSelect = () => {}, onFrame = () => {}, reduceMotion = false } = {}) {
  let gl;
  try {
    gl = canvas.getContext("webgl", { antialias: true, alpha: true, premultipliedAlpha: false });
  } catch { gl = null; }
  if (!gl) return null;

  let points, lines;
  try {
    points = program(gl, POINT_VS, POINT_FS);
    lines = program(gl, LINE_VS, LINE_FS);
  } catch {
    return null;  // Keep the accessible region list when shaders cannot compile.
  }
  const palette = readPalette(canvas);
  const dots = sphereDots(window.matchMedia?.("(max-width: 760px)").matches ? 1800 : 4200);
  const hubs = HUBS.map((hub) => ({ ...hub, vector: toVector(hub.lat, hub.lon), weight: 0.5 }));
  const arcs = LINKS.map(([a, b], index) => ({
    path: arcPoints(hubs.find((h) => h.id === a).vector, hubs.find((h) => h.id === b).vector),
    offset: index * 0.37, speed: 0.11 + (index % 3) * 0.03,
  }));

  // Arcs are also drawn as dotted trails: WebGL lines are one pixel wide on most devices.
  const trail = arcs.flatMap((arc) => arc.path.filter((_, i) => i % 2 === 0 && i > 1 && i < arc.path.length - 2));
  const staticCount = dots.length + trail.length;
  const staticData = new Float32Array(staticCount * 9);
  dots.forEach(([x, y, z, land], i) => {
    const c = land ? palette.land : palette.sea;
    staticData.set([x, y, z, land ? 3.0 : 2.0, c[0], c[1], c[2], land ? 1.0 : 0.55, 0], i * 9);
  });
  trail.forEach(([x, y, z], i) => {
    staticData.set([x, y, z, 2.4, palette.arc[0], palette.arc[1], palette.arc[2], 0.55, 0], (dots.length + i) * 9);
  });
  const staticBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, staticBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, staticData, gl.STATIC_DRAW);

  const lineData = [];
  for (const arc of arcs) {
    for (let i = 0; i < arc.path.length - 1; i++) lineData.push(...arc.path[i], ...arc.path[i + 1]);
  }
  const lineBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, lineBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(lineData), gl.STATIC_DRAW);
  const dynamicBuffer = gl.createBuffer();
  const satellites = orbitals(window.matchMedia?.("(max-width: 760px)").matches ? 60 : 150);
  const ripples = [];
  const RIPPLE_POINTS = 40, MAX_RIPPLES = 6, TRAIL = 6;
  const dynamic = new Float32Array((hubs.length * 2 + arcs.length * TRAIL + satellites.length +
    MAX_RIPPLES * RIPPLE_POINTS) * 9);

  const state = { yaw: -0.35, pitch: 0.32, velocity: reduceMotion ? 0 : 0.0016, dragging: false, active: null,
    hover: null, lastX: 0, lastY: 0, tiltX: 0, tiltY: 0, visible: true, frame: 0, start: performance.now() };
  let width = 1, height = 1, dpr = 1, scale = 0.8;

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    const box = canvas.getBoundingClientRect();
    width = Math.max(1, Math.round(box.width * dpr));
    height = Math.max(1, Math.round(box.height * dpr));
    canvas.width = width;
    canvas.height = height;
    gl.viewport(0, 0, width, height);
    // The globe's pixel radius is scale * height / 2; keep it inside narrow canvases too.
    scale = 0.86 * Math.min(1, width / height);
  }

  function attrib(prog, name, size, stride, offset) {
    const location = gl.getAttribLocation(prog, name);
    if (location < 0) return;
    gl.enableVertexAttribArray(location);
    gl.vertexAttribPointer(location, size, gl.FLOAT, false, stride * 4, offset * 4);
  }

  function uniforms(prog, yaw, pitch) {
    gl.uniform1f(gl.getUniformLocation(prog, "uYaw"), yaw);
    gl.uniform1f(gl.getUniformLocation(prog, "uPitch"), pitch);
    gl.uniform1f(gl.getUniformLocation(prog, "uScale"), scale);
    gl.uniform1f(gl.getUniformLocation(prog, "uAspect"), width / height);
    const dprLocation = gl.getUniformLocation(prog, "uDpr");
    if (dprLocation) gl.uniform1f(dprLocation, dpr);
  }

  function project(vector, yaw, pitch) {
    const [x, y, z] = rotate(vector, yaw, pitch);
    return { x: (x * scale / (width / height) + 1) / 2 * width / dpr, y: (1 - (y * scale + 1) / 2) * height / dpr, z };
  }

  function draw(now) {
    const time = (now - state.start) / 1000;
    if (state.target && !state.dragging) {
      // Critically damped glide toward a focused hub; the spin resumes once it arrives.
      const dy = shortestAngle(state.yaw, state.target.yaw), dp = state.target.pitch - state.pitch;
      state.yaw += dy * 0.075; state.pitch += dp * 0.075; state.velocity = 0;
      if (Math.abs(dy) < 0.002 && Math.abs(dp) < 0.002) state.target = null;
    } else if (!state.dragging) {
      state.yaw += state.velocity;
      if (!reduceMotion) state.velocity += ((state.hold ? 0 : 0.0016) - state.velocity) * 0.02;
    }
    const yaw = state.yaw + state.tiltX, pitch = state.pitch + state.tiltY;
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    gl.useProgram(lines);
    uniforms(lines, yaw, pitch);
    gl.uniform3fv(gl.getUniformLocation(lines, "uColor"), palette.arc);
    gl.bindBuffer(gl.ARRAY_BUFFER, lineBuffer);
    attrib(lines, "aPos", 4, 4, 0);
    gl.drawArrays(gl.LINES, 0, lineData.length / 4);

    gl.useProgram(points);
    uniforms(points, yaw, pitch);
    gl.bindBuffer(gl.ARRAY_BUFFER, staticBuffer);
    attrib(points, "aPos", 3, 9, 0); attrib(points, "aSize", 1, 9, 3); attrib(points, "aColor", 4, 9, 4); attrib(points, "aGlow", 1, 9, 8);
    gl.drawArrays(gl.POINTS, 0, staticCount);

    let n = 0;
    const put = (v, size, color, alpha, glow) => { dynamic.set([v[0], v[1], v[2], size, color[0], color[1], color[2], alpha, glow], n * 9); n++; };
    for (const hub of hubs) {
      const selected = state.active === hub.id || state.hover === hub.id;
      const pulse = reduceMotion ? 0.5 : 0.5 + 0.5 * Math.sin(time * 2.2 + hub.lon);
      const size = 14 + 22 * hub.weight + (selected ? 12 : 0);
      put(hub.vector, size * (2.2 + pulse * 0.9), selected ? palette.active : palette.hub, 0.38 + pulse * 0.2, 1);
      put(hub.vector, size * 0.7, selected ? palette.active : palette.hub, 1, 1);
    }
    if (!reduceMotion) {
      for (const arc of arcs) {
        for (let k = 0; k < TRAIL; k++) {
          const t = (((time * arc.speed + arc.offset - k * 0.018) % 1) + 1) % 1;
          const p = arc.path[Math.min(arc.path.length - 1, Math.floor(t * (arc.path.length - 1)))];
          put(p, 13 - k * 1.8, k ? palette.arc : palette.active, 0.95 - k * 0.15, 1);
        }
      }
      for (const orbit of satellites) {
        put(orbitalPosition(orbit, time), orbit.size, palette.arc, 0.55, 0);
      }
    }
    for (let r = ripples.length - 1; r >= 0; r--) {
      const age = (now - ripples[r].start) / 1600;
      if (age >= 1) { ripples.splice(r, 1); continue; }
      const fade = 1 - age;
      for (const point of ringAround(ripples[r].hub.vector, 0.02 + age * 0.32, RIPPLE_POINTS)) {
        put(point, 5 * fade + 2, palette.active, 0.9 * fade, 1);
      }
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, dynamicBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, dynamic.subarray(0, n * 9), gl.DYNAMIC_DRAW);
    attrib(points, "aPos", 3, 9, 0); attrib(points, "aSize", 1, 9, 3); attrib(points, "aColor", 4, 9, 4); attrib(points, "aGlow", 1, 9, 8);
    gl.drawArrays(gl.POINTS, 0, n);
    onFrame();
  }

  function loop(now) {
    state.frame = 0;
    if (!state.visible) return;
    draw(now);
    if (!reduceMotion || state.dragging || state.target || ripples.length) state.frame = requestAnimationFrame(loop);
  }
  const kick = () => { if (!state.frame && state.visible) state.frame = requestAnimationFrame(loop); };

  function hubAt(clientX, clientY) {
    const box = canvas.getBoundingClientRect();
    const x = clientX - box.left, y = clientY - box.top;
    let best = null, distance = 26;
    for (const hub of hubs) {
      const p = project(hub.vector, state.yaw + state.tiltX, state.pitch + state.tiltY);
      const d = Math.hypot(p.x - x, p.y - y);
      if (p.z > 0.05 && d < distance) { best = hub; distance = d; }
    }
    return best;
  }

  canvas.addEventListener("pointerdown", (event) => {
    state.dragging = true; state.moved = 0;
    state.lastX = event.clientX; state.lastY = event.clientY;
    canvas.setPointerCapture?.(event.pointerId);
    kick();
  });
  canvas.addEventListener("pointermove", (event) => {
    if (state.dragging) {
      const dx = event.clientX - state.lastX, dy = event.clientY - state.lastY;
      state.moved += Math.abs(dx) + Math.abs(dy);
      state.yaw += dx * 0.006;
      state.pitch = Math.max(-1.1, Math.min(1.1, state.pitch + dy * 0.004));
      state.velocity = dx * 0.0009;
      state.lastX = event.clientX; state.lastY = event.clientY;
    } else if (event.pointerType === "mouse") {
      const box = canvas.getBoundingClientRect();
      if (!reduceMotion) {
        state.tiltX = ((event.clientX - box.left) / box.width - 0.5) * 0.25;
        state.tiltY = ((event.clientY - box.top) / box.height - 0.5) * 0.18;
      }
      const hub = hubAt(event.clientX, event.clientY);
      if ((hub?.id || null) !== state.hover) {
        state.hover = hub?.id || null;
        canvas.style.cursor = hub ? "pointer" : "grab";
      }
      onHover(hub, event.clientX - box.left, event.clientY - box.top);
      if (reduceMotion) kick();
    }
  });
  const release = (event) => {
    if (!state.dragging) return;
    state.dragging = false;
    if (state.moved < 6) {
      const hub = hubAt(event.clientX, event.clientY);
      if (hub) onSelect(hub);
    }
  };
  canvas.addEventListener("pointerup", release);
  canvas.addEventListener("pointercancel", () => { state.dragging = false; });
  canvas.addEventListener("pointerleave", () => {
    state.hover = null; state.tiltX = 0; state.tiltY = 0; onHover(null, 0, 0);
  });

  const observer = new ResizeObserver(() => { resize(); kick(); });
  observer.observe(canvas);
  const visibility = new IntersectionObserver(([entry]) => { state.visible = entry.isIntersecting; kick(); });
  visibility.observe(canvas);
  const pageVisibility = () => { state.visible = !document.hidden; kick(); };
  document.addEventListener("visibilitychange", pageVisibility);
  resize();
  kick();

  return {
    setWeights(weights) {
      const values = hubs.map((hub) => weights[hub.id] || 0);
      const max = Math.max(1, ...values);
      hubs.forEach((hub, i) => { hub.weight = 0.25 + 0.75 * Math.sqrt(values[i] / max); });
      kick();
    },
    setActive(id) { state.active = id || null; kick(); },
    focus(id, { glide = !reduceMotion } = {}) {
      const hub = hubs.find((h) => h.id === id);
      if (!hub) return;
      // Turn the hub toward the viewer, taking the short way round.
      const yaw = state.yaw + shortestAngle(state.yaw, -hub.lon * Math.PI / 180);
      const pitch = Math.max(-0.8, Math.min(0.8, hub.lat * Math.PI / 180 * 0.6));
      if (glide) state.target = { yaw, pitch };
      else { state.yaw = yaw; state.pitch = pitch; state.target = null; }
      kick();
    },
    // An expanding ring at a hub marks a story arriving from that region.
    pulse(id) {
      const hub = hubs.find((h) => h.id === id);
      if (!hub || reduceMotion) return;
      if (ripples.length >= MAX_RIPPLES) ripples.shift();
      ripples.push({ hub, start: performance.now() });
      kick();
    },
    // Screen position of a hub in CSS pixels relative to the canvas; z > 0 faces the reader.
    project(id) {
      const hub = hubs.find((h) => h.id === id);
      return hub ? project(hub.vector, state.yaw + state.tiltX, state.pitch + state.tiltY) : null;
    },
    // Slow the idle spin while a reader is reading something anchored to the globe.
    hold(value) { state.hold = Boolean(value); },
    setMotion(allowed) {
      reduceMotion = !allowed;
      state.velocity = reduceMotion ? 0 : 0.0016;
      if (reduceMotion) { ripples.length = 0; state.tiltX = 0; state.tiltY = 0; }
      kick();
    },
    destroy() {
      cancelAnimationFrame(state.frame);
      observer.disconnect(); visibility.disconnect();
      document.removeEventListener("visibilitychange", pageVisibility);
    },
  };
}
