// Paper texture (festin-3d6.16). A WebGL shader draws one seamless tile of paper
// once, at load: broad cloudy formation, fine tooth, and a few long fibres. The
// tile becomes --paper-grain, which every paper background multiplies into its
// colour. Nothing is redrawn after that, so it costs no frames.

const TILE = 512 // CSS px; drawn at the device pixel ratio, capped
const STRENGTH = 1 // 0 turns it off; 1 is the tuned default

const VERT = `
attribute vec2 p;
void main() { gl_Position = vec4(p, 0.0, 1.0); }
`

// Value noise on a lattice wrapped at `period`, so the tile repeats without seams.
const FRAG = `
precision highp float;
uniform vec2 size;
uniform float strength;

float hash(vec2 c) {
  return fract(sin(dot(c, vec2(127.1, 311.7))) * 43758.5453);
}

float noise(vec2 x, vec2 period) {
  vec2 i = floor(x);
  vec2 f = fract(x);
  vec2 u = f * f * (3.0 - 2.0 * f);
  float a = hash(mod(i, period));
  float b = hash(mod(i + vec2(1.0, 0.0), period));
  float c = hash(mod(i + vec2(0.0, 1.0), period));
  float d = hash(mod(i + vec2(1.0, 1.0), period));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

float noise(vec2 x, float period) {
  return noise(x, vec2(period));
}

// Short, thin fibres along integer direction d (so the tile still wraps).
float fibres(vec2 uv, vec2 d, float seed) {
  vec2 across = vec2(-d.y, d.x);
  vec2 x = vec2(dot(uv, d) * 10.0, dot(uv, across) * 110.0) + seed;
  float strand = smoothstep(0.80, 0.97, noise(x, vec2(10.0, 110.0)));
  float sparse = smoothstep(0.55, 0.85, noise(uv * 12.0 + seed, 12.0));
  return strand * sparse;
}

float fbm(vec2 x, float period) {
  float sum = 0.0;
  float amp = 0.5;
  for (int k = 0; k < 5; k++) {
    sum += amp * noise(x, period);
    x *= 2.0;
    period *= 2.0;
    amp *= 0.5;
  }
  return sum;
}

void main() {
  vec2 uv = gl_FragCoord.xy / size;
  // Formation: soft clouds where the pulp settled thicker or thinner.
  float formation = fbm(uv * 4.0, 4.0);
  // Tooth: the fine surface grain.
  float tooth = noise(uv * 180.0, 180.0) * 0.6 + noise(uv * 90.0, 90.0) * 0.4;
  // Fibres: short, thin and scattered, in three directions.
  float fibre = max(max(fibres(uv, vec2(1.0, 0.0), 0.0), fibres(uv, vec2(1.0, 2.0), 17.0)), fibres(uv, vec2(2.0, -1.0), 41.0));
  float shade = (formation - 0.5) * 0.030 + (tooth - 0.5) * 0.022 + fibre * 0.018;
  // A multiplier at or just under 1.0: paper only ever darkens a touch.
  float m = 1.0 - strength * clamp(0.012 + shade, 0.0, 0.06);
  gl_FragColor = vec4(vec3(m), 1.0);
}
`

function compile(gl, type, source) {
  const shader = gl.createShader(type)
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(shader) || 'shader failed')
  return shader
}

// Draws the tile and resolves to an object URL, or null when WebGL is missing
// (the paper then stays plain, which is the fallback).
export function drawPaperTile({ strength = STRENGTH, tile = TILE } = {}) {
  const scale = Math.min(2, window.devicePixelRatio || 1)
  const px = Math.round(tile * scale)
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = px
  const gl = canvas.getContext('webgl', { preserveDrawingBuffer: true, antialias: false })
  if (!gl || strength <= 0) return Promise.resolve(null)
  try {
    const program = gl.createProgram()
    gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERT))
    gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAG))
    gl.linkProgram(program)
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error('link failed')
    gl.useProgram(program)
    const buffer = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW)
    const at = gl.getAttribLocation(program, 'p')
    gl.enableVertexAttribArray(at)
    gl.vertexAttribPointer(at, 2, gl.FLOAT, false, 0, 0)
    gl.uniform2f(gl.getUniformLocation(program, 'size'), px, px)
    gl.uniform1f(gl.getUniformLocation(program, 'strength'), strength)
    gl.viewport(0, 0, px, px)
    gl.drawArrays(gl.TRIANGLES, 0, 3)
  } catch {
    gl.getExtension('WEBGL_lose_context')?.loseContext()
    return Promise.resolve(null)
  }
  // Read the pixels out first, then give the GPU context back.
  return new Promise((resolve) =>
    canvas.toBlob((blob) => {
      gl.getExtension('WEBGL_lose_context')?.loseContext()
      resolve(blob ? URL.createObjectURL(blob) : null)
    }, 'image/png'),
  )
}

// Lay the paper under the app: sets --paper-grain and its tile size on :root.
export function layPaper(root = document.documentElement) {
  return drawPaperTile().then((url) => {
    if (!url) return false
    root.style.setProperty('--paper-grain', `url("${url}")`)
    root.style.setProperty('--paper-tile', TILE + 'px')
    return true
  })
}
