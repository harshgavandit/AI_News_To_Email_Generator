// Informa AI "Signal Globe": a dependency-free WebGL planet of regional technology coverage.
// A ray-cast shader draws real coastlines as a dot matrix, the live day/night terminator and
// city lights; hubs mark publisher regions with light pillars, and packets travel the arcs
// between them. The globe is decoration plus a shortcut: every hub is also exposed as
// a real button by the page, so nothing here is required to read or filter the news.

import { LAND_MASK, MASK_HEIGHT, MASK_WIDTH } from "./land-mask.js";

const TAU = Math.PI * 2;

// Decode the 1-degree land mask once: one byte per cell, row 0 at latitude 89.5.
let landCells = null;
export function landCellsGrid() {
  if (landCells) return landCells;
  const binary = typeof atob === "function" ? atob(LAND_MASK) : Buffer.from(LAND_MASK, "base64").toString("binary");
  landCells = new Uint8Array(MASK_WIDTH * MASK_HEIGHT);
  for (let i = 0; i < landCells.length; i++) {
    if (binary.charCodeAt(i >> 3) & (1 << (i & 7))) landCells[i] = 255;
  }
  return landCells;
}

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
  const row = Math.min(MASK_HEIGHT - 1, Math.max(0, Math.floor(90 - lat)));
  const column = ((Math.floor(lon + 180) % MASK_WIDTH) + MASK_WIDTH) % MASK_WIDTH;
  return landCellsGrid()[row * MASK_WIDTH + column] > 0;
}

// The point on Earth where the sun is overhead, accurate to about a degree: enough to draw
// the live day/night terminator. Returns { lat, lon } in degrees.
export function subsolarPoint(date = new Date()) {
  const start = Date.UTC(date.getUTCFullYear(), 0, 0);
  const day = (date.getTime() - start) / 86400000;
  const gamma = TAU / 365 * (day - 1);
  const declination = 0.006918 - 0.399912 * Math.cos(gamma) + 0.070257 * Math.sin(gamma)
    - 0.006758 * Math.cos(2 * gamma) + 0.000907 * Math.sin(2 * gamma);
  const equation = 229.18 * (0.000075 + 0.001868 * Math.cos(gamma) - 0.032077 * Math.sin(gamma)
    - 0.014615 * Math.cos(2 * gamma) - 0.040849 * Math.sin(2 * gamma));
  const minutes = date.getUTCHours() * 60 + date.getUTCMinutes() + date.getUTCSeconds() / 60;
  let lon = -((minutes + equation) / 4 - 180);
  lon = ((lon + 540) % 360) - 180;
  return { lat: declination * 180 / Math.PI, lon };
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

// Orbital rings that frame the planet like an instrument bezel: [x, y, z, t] per point.
export function orbitRing(radius, tilt, node, count = 160) {
  const points = [];
  for (let i = 0; i < count; i++) {
    const a = (i / count) * TAU;
    const px = Math.cos(a) * radius, pz = Math.sin(a) * radius;
    const y = pz * Math.sin(tilt), z1 = pz * Math.cos(tilt);
    const cn = Math.cos(node), sn = Math.sin(node);
    points.push([px * cn + z1 * sn, y, -px * sn + z1 * cn, i / count]);
  }
  return points;
}

// Shared view transform: yaw around Y, then pitch around X. Points behind the planet's disc
// are hidden so the planet reads as solid.
const ROTATE_GLSL = `
uniform float uYaw, uPitch, uScale, uAspect;
vec3 view(vec3 a) {
  float cy = cos(uYaw), sy = sin(uYaw), cp = cos(uPitch), sp = sin(uPitch);
  vec3 p = vec3(a.x * cy + a.z * sy, a.y, -a.x * sy + a.z * cy);
  return vec3(p.x, p.y * cp - p.z * sp, p.y * sp + p.z * cp);
}
float occluded(vec3 p) { return (p.z < 0.0 && length(p.xy) < 0.995) ? 1.0 : 0.0; }`;

const POINT_VS = `
attribute vec3 aPos; attribute float aSize; attribute vec4 aColor; attribute float aGlow;
uniform float uDpr, uPx;
varying vec4 vColor; varying float vGlow, vHidden;
${ROTATE_GLSL}
void main() {
  vec3 p = view(aPos);
  vColor = aColor; vGlow = aGlow; vHidden = occluded(p);
  gl_Position = vec4(p.x * uScale / uAspect, p.y * uScale, -p.z * 0.3, 1.0);
  gl_PointSize = aSize * uDpr * uPx * (0.62 + 0.38 * clamp(p.z + 0.4, 0.0, 1.0));
}`;
const POINT_FS = `
precision mediump float;
varying vec4 vColor; varying float vGlow, vHidden;
void main() {
  if (vHidden > 0.5) discard;
  float d = length(gl_PointCoord - 0.5) * 2.0;
  if (d > 1.0) discard;
  float a = vGlow > 0.0 ? pow(1.0 - d, 2.2) + (1.0 - smoothstep(0.0, 0.22, d)) * 0.9 : 1.0 - smoothstep(0.5, 1.0, d);
  gl_FragColor = vec4(vColor.rgb, vColor.a * a);
}`;
const LINE_VS = `
attribute vec4 aPos;
varying float vT, vFront, vHidden;
${ROTATE_GLSL}
void main() {
  vec3 p = view(aPos.xyz);
  vT = aPos.w; vFront = p.z; vHidden = occluded(p);
  gl_Position = vec4(p.x * uScale / uAspect, p.y * uScale, -p.z * 0.3, 1.0);
}`;
const LINE_FS = `
precision mediump float;
uniform vec3 uColor; uniform float uAlpha;
varying float vT, vFront, vHidden;
void main() {
  if (vHidden > 0.5) discard;
  float edge = smoothstep(0.0, 0.1, vT) * (1.0 - smoothstep(0.9, 1.0, vT));
  gl_FragColor = vec4(uColor, uAlpha * edge);
}`;

// The planet itself is ray-cast per pixel on one full-canvas quad: ocean, a dot-matrix of
// land from the mask texture, the graticule, sunlight with a live terminator, city lights on
// the night side, a Fresnel rim and an atmospheric halo.
const PLANET_VS = `
attribute vec2 aQuad; varying vec2 vUv;
void main() { vUv = aQuad; gl_Position = vec4(aQuad, 0.0, 1.0); }`;
const PLANET_FS = `
precision highp float;
uniform vec2 uRes; uniform float uScale, uYaw, uPitch, uTime, uDots;
uniform vec3 uSun, uSunView;
uniform sampler2D uLand;
uniform vec3 uOcean, uOceanDeep, uLandTint, uDot, uCity, uRim;
varying vec2 vUv;
const float PI = 3.14159265;
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float landAt(float lat, float lon) {
  vec2 uv = vec2((lon + PI) / (2.0 * PI), (PI * 0.5 - lat) / PI);
  return texture2D(uLand, uv).r;
}
void main() {
  vec2 p = vec2(vUv.x * uRes.x / uRes.y, vUv.y) / uScale;
  float r = length(p);
  float px = 2.0 / (uScale * uRes.y);           // one pixel in sphere units
  // Atmosphere halo outside the disc, brighter on the sunlit limb.
  float halo = exp(-max(r - 1.0, 0.0) * 7.5) * smoothstep(1.0 - px, 1.0 + px, r);
  float sunSide = 0.55 + 0.45 * dot(normalize(p + 1e-5), normalize(uSunView.xy + 1e-5));
  vec4 outside = vec4(uRim, halo * 0.5 * sunSide);
  if (r > 1.0 + px) { gl_FragColor = outside; return; }

  vec3 n = vec3(p, sqrt(max(0.0, 1.0 - r * r)));
  // Undo pitch, then yaw, to find the world-space point under this pixel.
  float cy = cos(uYaw), sy = sin(uYaw), cp = cos(uPitch), sp = sin(uPitch);
  float y = n.y * cp + n.z * sp, z1 = -n.y * sp + n.z * cp;
  vec3 w = vec3(n.x * cy - z1 * sy, y, n.x * sy + z1 * cy);
  float lat = asin(clamp(w.y, -1.0, 1.0)), lon = atan(w.x, w.z);
  float land = smoothstep(0.3, 0.7, landAt(lat, lon));

  // Sunlight: a soft terminator and a thin bright dawn line that sweeps with the real clock.
  float ndl = dot(w, uSun);
  float day = smoothstep(-0.18, 0.28, ndl);
  float dawn = exp(-abs(ndl) * 48.0);

  vec3 color = mix(uOceanDeep, uOcean, 0.25 + 0.55 * day + 0.2 * n.z);
  color = mix(color, uLandTint, land * (0.22 + 0.25 * day));

  // Dot matrix: each cell samples land at its centre so dots are whole.
  float latDeg = lat * 180.0 / PI, lonDeg = lon * 180.0 / PI;
  float gy = latDeg / uDots, cyc = floor(gy) + 0.5;
  float rowLat = cyc * uDots;
  float span = uDots / max(cos(rowLat * PI / 180.0), 0.08);
  float gx = (lonDeg + 180.0) / span, cxc = floor(gx) + 0.5;
  float cellLand = smoothstep(0.35, 0.65, landAt(rowLat * PI / 180.0, (cxc * span - 180.0) * PI / 180.0));
  vec2 f = vec2(fract(gx), fract(gy)) - 0.5;
  float dotMask = (1.0 - smoothstep(0.2, 0.34, length(f))) * cellLand;
  float seed = hash(vec2(cxc, cyc));
  float shimmer = 0.75 + 0.25 * sin(uTime * 1.3 + seed * 40.0);
  color += uDot * dotMask * (0.12 + 0.88 * day) * shimmer * (0.6 + 0.4 * n.z);
  // City lights: a scatter of land cells glows on the night side, twinkling slowly.
  float city = step(0.9, seed) * dotMask * (1.0 - day);
  color += uCity * city * (0.7 + 0.3 * sin(uTime * 2.0 + seed * 90.0)) * 0.9;

  // Graticule every 15 degrees, fading toward the limb.
  float gLat = abs(fract(latDeg / 15.0 + 0.5) - 0.5) * 15.0;
  float gLon = abs(fract(lonDeg / 15.0 + 0.5) - 0.5) * 15.0 * cos(lat);
  float grid = (1.0 - smoothstep(0.0, 0.32, min(gLat, gLon))) * 0.10 * n.z;
  color += uRim * grid;

  color += uRim * dawn * 0.14;
  // Ocean glint and a Fresnel rim of atmosphere.
  vec3 h = normalize(uSunView + vec3(0.0, 0.0, 1.0));
  color += vec3(0.85, 0.95, 1.0) * pow(max(dot(n, h), 0.0), 60.0) * (1.0 - land) * 0.45 * day;
  float fresnel = pow(1.0 - n.z, 2.6);
  color = mix(color, uRim, fresnel * (0.35 + 0.4 * day));

  float edge = clamp((1.0 - r) / px, 0.0, 1.0);
  gl_FragColor = vec4(mix(outside.rgb, color, edge), mix(outside.a, 1.0, edge));
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
  return {
    land: color("--globe-land", "bfefff"), hub: color("--globe-hub", "5fe3ff"),
    active: color("--globe-active", "ffffff"), arc: color("--globe-arc", "7dd3fc"),
    ocean: color("--globe-ocean", "123a74"), oceanDeep: color("--globe-ocean-deep", "040d24"),
    landTint: color("--globe-land-tint", "2a6fb8"), dot: color("--globe-dot", "9ff0ff"),
    city: color("--globe-city", "ffe3a3"), rim: color("--globe-rim", "6fd8ff"),
  };
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

  let points, lines, planet;
  try {
    points = program(gl, POINT_VS, POINT_FS);
    lines = program(gl, LINE_VS, LINE_FS);
    planet = program(gl, PLANET_VS, PLANET_FS);
  } catch {
    return null;  // Keep the accessible region list when shaders cannot compile.
  }
  const palette = readPalette(canvas);
  const small = window.matchMedia?.("(max-width: 760px)").matches;

  // Land mask texture: bilinear filtering turns the 1-degree grid into soft coastlines.
  const landTexture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, landTexture);
  gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.LUMINANCE, MASK_WIDTH, MASK_HEIGHT, 0, gl.LUMINANCE, gl.UNSIGNED_BYTE, landCellsGrid());
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  const quadBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, quadBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);

  const hubs = HUBS.map((hub) => ({ ...hub, vector: toVector(hub.lat, hub.lon), weight: 0.5 }));
  const arcs = LINKS.map(([a, b], index) => ({
    path: arcPoints(hubs.find((h) => h.id === a).vector, hubs.find((h) => h.id === b).vector, 64),
    offset: index * 0.37, speed: 0.09 + (index % 3) * 0.03,
  }));
  const rings = [orbitRing(1.32, 0.42, 0.6, small ? 90 : 180), orbitRing(1.46, -0.28, 2.2, small ? 90 : 200)];

  // Arcs are also drawn as dotted trails: WebGL lines are one pixel wide on most devices.
  const trail = arcs.flatMap((arc) => arc.path.filter((_, i) => i % 2 === 0 && i > 1 && i < arc.path.length - 2));
  const ringDots = rings.flatMap((ring) => ring.filter((_, i) => i % 2 === 0));
  const staticCount = trail.length + ringDots.length;
  const staticData = new Float32Array(staticCount * 9);
  trail.forEach(([x, y, z], i) => {
    staticData.set([x, y, z, 2.2, palette.arc[0], palette.arc[1], palette.arc[2], 0.42, 0], i * 9);
  });
  ringDots.forEach(([x, y, z], i) => {
    staticData.set([x, y, z, 1.6, palette.rim[0], palette.rim[1], palette.rim[2], 0.28, 0], (trail.length + i) * 9);
  });
  const staticBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, staticBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, staticData, gl.STATIC_DRAW);

  const lineData = [];
  for (const path of [...arcs.map((arc) => arc.path), ...rings]) {
    for (let i = 0; i < path.length - 1; i++) lineData.push(...path[i], ...path[i + 1]);
  }
  const arcLineCount = arcs.reduce((sum, arc) => sum + (arc.path.length - 1) * 2, 0);
  const lineBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, lineBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(lineData), gl.STATIC_DRAW);
  const dynamicBuffer = gl.createBuffer();
  const satellites = orbitals(small ? 40 : 110);
  const ripples = [];
  const RIPPLE_POINTS = 48, MAX_RIPPLES = 6, TRAIL = 12, BEAM = 14;
  const dynamic = new Float32Array((hubs.length * (2 + BEAM) + arcs.length * TRAIL + satellites.length +
    MAX_RIPPLES * RIPPLE_POINTS * 2) * 9);

  const state = { yaw: -0.35, pitch: 0.32, velocity: reduceMotion ? 0 : 0.0014, dragging: false, active: null,
    hover: null, lastX: 0, lastY: 0, tiltX: 0, tiltY: 0, visible: true, frame: 0, start: performance.now() };
  let width = 1, height = 1, dpr = 1, scale = 0.8, pxScale = 1;
  let sun = toVector(0, 0), sunChecked = 0;

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, small ? 1.5 : 2);
    const box = canvas.getBoundingClientRect();
    width = Math.max(1, Math.round(box.width * dpr));
    height = Math.max(1, Math.round(box.height * dpr));
    canvas.width = width;
    canvas.height = height;
    gl.viewport(0, 0, width, height);
    // The globe's pixel radius is scale * height / 2; leave room for the halo and rings.
    scale = 0.8 * Math.min(1, width / height);
    // Point sizes were tuned for a ~440px globe; keep small orbs proportionate.
    pxScale = Math.max(0.35, Math.min(1.15, box.height / 440));
  }

  function attrib(prog, name, size, stride, offset) {
    const location = gl.getAttribLocation(prog, name);
    if (location < 0) return;
    gl.enableVertexAttribArray(location);
    gl.vertexAttribPointer(location, size, gl.FLOAT, false, stride * 4, offset * 4);
  }
  const u = (prog, name) => gl.getUniformLocation(prog, name);

  function uniforms(prog, yaw, pitch) {
    gl.uniform1f(u(prog, "uYaw"), yaw);
    gl.uniform1f(u(prog, "uPitch"), pitch);
    gl.uniform1f(u(prog, "uScale"), scale);
    gl.uniform1f(u(prog, "uAspect"), width / height);
    const dprLocation = u(prog, "uDpr");
    if (dprLocation) gl.uniform1f(dprLocation, dpr);
    const pxLocation = u(prog, "uPx");
    if (pxLocation) gl.uniform1f(pxLocation, pxScale);
  }

  function project(vector, yaw, pitch) {
    const [x, y, z] = rotate(vector, yaw, pitch);
    return { x: (x * scale / (width / height) + 1) / 2 * width / dpr, y: (1 - (y * scale + 1) / 2) * height / dpr, z };
  }

  function drawPlanet(yaw, pitch, time) {
    gl.useProgram(planet);
    gl.bindBuffer(gl.ARRAY_BUFFER, quadBuffer);
    attrib(planet, "aQuad", 2, 2, 0);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, landTexture);
    gl.uniform1i(u(planet, "uLand"), 0);
    gl.uniform2f(u(planet, "uRes"), width, height);
    gl.uniform1f(u(planet, "uScale"), scale);
    gl.uniform1f(u(planet, "uYaw"), yaw);
    gl.uniform1f(u(planet, "uPitch"), pitch);
    gl.uniform1f(u(planet, "uTime"), reduceMotion ? 0 : time);
    // Finer dots on bigger globes; never below ~3 device pixels per cell.
    gl.uniform1f(u(planet, "uDots"), Math.max(1.1, Math.min(3.2, 520 / (scale * height))));
    gl.uniform3fv(u(planet, "uSun"), sun);
    gl.uniform3fv(u(planet, "uSunView"), rotate(sun, yaw, pitch));
    gl.uniform3fv(u(planet, "uOcean"), palette.ocean);
    gl.uniform3fv(u(planet, "uOceanDeep"), palette.oceanDeep);
    gl.uniform3fv(u(planet, "uLandTint"), palette.landTint);
    gl.uniform3fv(u(planet, "uDot"), palette.dot);
    gl.uniform3fv(u(planet, "uCity"), palette.city);
    gl.uniform3fv(u(planet, "uRim"), palette.rim);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  function draw(now) {
    const time = (now - state.start) / 1000;
    if (now - sunChecked > 60000) {  // The terminator follows the real clock, minute by minute.
      const point = subsolarPoint(new Date());
      sun = toVector(point.lat, point.lon);
      sunChecked = now;
    }
    if (state.target && !state.dragging) {
      // Critically damped glide toward a focused hub; the spin resumes once it arrives.
      const dy = shortestAngle(state.yaw, state.target.yaw), dp = state.target.pitch - state.pitch;
      state.yaw += dy * 0.075; state.pitch += dp * 0.075; state.velocity = 0;
      if (Math.abs(dy) < 0.002 && Math.abs(dp) < 0.002) state.target = null;
    } else if (!state.dragging) {
      state.yaw += state.velocity;
      if (!reduceMotion) state.velocity += ((state.hold ? 0 : 0.0014) - state.velocity) * 0.02;
    }
    const yaw = state.yaw + state.tiltX, pitch = state.pitch + state.tiltY;
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.enable(gl.BLEND);
    // Keep the canvas alpha unpremultiplied so the halo stays bright over the page.
    gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

    drawPlanet(yaw, pitch, time);
    // Light adds up from here on: arcs, beams and packets glow over the planet.
    gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE, gl.ONE, gl.ONE);

    gl.useProgram(lines);
    uniforms(lines, yaw, pitch);
    gl.bindBuffer(gl.ARRAY_BUFFER, lineBuffer);
    attrib(lines, "aPos", 4, 4, 0);
    gl.uniform3fv(u(lines, "uColor"), palette.arc);
    gl.uniform1f(u(lines, "uAlpha"), 0.5);
    gl.drawArrays(gl.LINES, 0, arcLineCount);
    gl.uniform3fv(u(lines, "uColor"), palette.rim);
    gl.uniform1f(u(lines, "uAlpha"), 0.16);
    gl.drawArrays(gl.LINES, arcLineCount, lineData.length / 4 - arcLineCount);

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
      const size = 12 + 20 * hub.weight + (selected ? 12 : 0);
      const color = selected ? palette.active : palette.hub;
      put(hub.vector, size * (2.0 + pulse * 0.8), color, 0.3 + pulse * 0.18, 1);
      put(hub.vector, size * 0.62, color, 1, 1);
      // A light pillar rises from each hub, taller where more stories come from.
      const height = 0.06 + 0.16 * hub.weight + (selected ? 0.06 : 0);
      for (let k = 1; k <= BEAM; k++) {
        const t = k / BEAM, lift = 1 + height * t;
        put(hub.vector.map((c) => c * lift), (5 - 3 * t) + (selected ? 2 : 0), color, (1 - t) * 0.75, 1);
      }
    }
    if (!reduceMotion) {
      for (const arc of arcs) {
        for (let k = 0; k < TRAIL; k++) {
          const t = (((time * arc.speed + arc.offset - k * 0.012) % 1) + 1) % 1;
          const p = arc.path[Math.min(arc.path.length - 1, Math.floor(t * (arc.path.length - 1)))];
          put(p, 14 - k * 1.05, k ? palette.arc : palette.active, (0.95 - k * 0.075) * Math.sin(Math.PI * t), 1);
        }
      }
      for (const orbit of satellites) {
        put(orbitalPosition(orbit, time), orbit.size, palette.arc, 0.6, 0);
      }
    }
    for (let r = ripples.length - 1; r >= 0; r--) {
      const age = (now - ripples[r].start) / 1800;
      if (age >= 1) { ripples.splice(r, 1); continue; }
      const fade = 1 - age;
      for (const [index, radius] of [0.02 + age * 0.34, 0.01 + age * 0.2].entries()) {
        for (const point of ringAround(ripples[r].hub.vector, radius, RIPPLE_POINTS)) {
          put(point, (5 * fade + 2) * (index ? 0.7 : 1), palette.active, 0.9 * fade * (index ? 0.6 : 1), 1);
        }
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
    state.dragging = true; state.moved = 0; state.target = null;
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
      // Flicks carry momentum; friction in draw() brings the spin back to its idle pace.
      state.velocity = Math.max(-0.08, Math.min(0.08, dx * 0.0012));
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
    // An expanding double ring at a hub marks a story arriving from that region.
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
      state.velocity = reduceMotion ? 0 : 0.0014;
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
