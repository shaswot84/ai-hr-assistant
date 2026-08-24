"use client";

import { useEffect, useRef } from "react";

const CONFIG = {
  SIM_RESOLUTION: 128,
  DYE_RESOLUTION: 512,
  DENSITY_DISSIPATION: 1.15,
  VELOCITY_DISSIPATION: 0.3,
  PRESSURE: 0.85,
  PRESSURE_ITERATIONS: 18,
  CURL: 26,
  SPLAT_RADIUS: 0.14,
  SPLAT_FORCE: 4800,
  COLOR_INTENSITY: 0.22,
};

const PALETTE = ["#2563eb", "#3b82f6", "#60a5fa", "#f59e0b", "#d4a373", "#fcd34d"];

interface FBO {
  texture: WebGLTexture;
  fbo: WebGLFramebuffer;
  width: number;
  height: number;
  texelSizeX: number;
  texelSizeY: number;
  attach(id: number): number;
}

interface DoubleFBO {
  width: number;
  height: number;
  texelSizeX: number;
  texelSizeY: number;
  read: FBO;
  write: FBO;
  swap(): void;
}

interface Format {
  internalFormat: number;
  format: number;
}

interface PointerState {
  x: number;
  y: number;
  dx: number;
  dy: number;
  moved: boolean;
  color: [number, number, number];
}

const BASE_VERTEX = `
precision highp float;
attribute vec2 aPosition;
varying vec2 vUv;
varying vec2 vL;
varying vec2 vR;
varying vec2 vT;
varying vec2 vB;
uniform vec2 texelSize;
void main () {
    vUv = aPosition * 0.5 + 0.5;
    vL = vUv - vec2(texelSize.x, 0.0);
    vR = vUv + vec2(texelSize.x, 0.0);
    vT = vUv + vec2(0.0, texelSize.y);
    vB = vUv - vec2(0.0, texelSize.y);
    gl_Position = vec4(aPosition, 0.0, 1.0);
}
`;

const COPY_SHADER = `
precision mediump float;
precision mediump sampler2D;
varying highp vec2 vUv;
uniform sampler2D uTexture;
void main () {
    gl_FragColor = texture2D(uTexture, vUv);
}
`;

const CLEAR_SHADER = `
precision mediump float;
precision mediump sampler2D;
varying highp vec2 vUv;
uniform sampler2D uTexture;
uniform float value;
void main () {
    gl_FragColor = value * texture2D(uTexture, vUv);
}
`;

const SPLAT_SHADER = `
precision highp float;
precision highp sampler2D;
varying vec2 vUv;
uniform sampler2D uTarget;
uniform float aspectRatio;
uniform vec3 color;
uniform vec2 point;
uniform float radius;
void main () {
    vec2 p = vUv - point.xy;
    p.x *= aspectRatio;
    vec3 splat = exp(-dot(p, p) / radius) * color;
    vec3 base = texture2D(uTarget, vUv).xyz;
    gl_FragColor = vec4(base + splat, 1.0);
}
`;

const ADVECTION_SHADER = `
precision highp float;
precision highp sampler2D;
varying vec2 vUv;
uniform sampler2D uVelocity;
uniform sampler2D uSource;
uniform vec2 texelSize;
uniform vec2 dyeTexelSize;
uniform float dt;
uniform float dissipation;

vec4 bilerp (sampler2D sam, vec2 uv, vec2 tsize) {
    vec2 st = uv / tsize - 0.5;
    vec2 iuv = floor(st);
    vec2 fuv = fract(st);
    vec4 a = texture2D(sam, (iuv + vec2(0.5, 0.5)) * tsize);
    vec4 b = texture2D(sam, (iuv + vec2(1.5, 0.5)) * tsize);
    vec4 c = texture2D(sam, (iuv + vec2(0.5, 1.5)) * tsize);
    vec4 d = texture2D(sam, (iuv + vec2(1.5, 1.5)) * tsize);
    return mix(mix(a, b, fuv.x), mix(c, d, fuv.x), fuv.y);
}

void main () {
#ifdef MANUAL_FILTERING
    vec2 coord = vUv - dt * bilerp(uVelocity, vUv, texelSize).xy * texelSize;
    vec4 result = bilerp(uSource, coord, dyeTexelSize);
#else
    vec2 coord = vUv - dt * texture2D(uVelocity, vUv).xy * texelSize;
    vec4 result = texture2D(uSource, coord);
#endif
    float decay = 1.0 + dissipation * dt;
    gl_FragColor = result / decay;
}
`;

const DIVERGENCE_SHADER = `
precision mediump float;
precision mediump sampler2D;
varying highp vec2 vUv;
varying highp vec2 vL;
varying highp vec2 vR;
varying highp vec2 vT;
varying highp vec2 vB;
uniform sampler2D uVelocity;
void main () {
    float L = texture2D(uVelocity, vL).x;
    float R = texture2D(uVelocity, vR).x;
    float T = texture2D(uVelocity, vT).y;
    float B = texture2D(uVelocity, vB).y;
    vec2 C = texture2D(uVelocity, vUv).xy;
    if (vL.x < 0.0) { L = -C.x; }
    if (vR.x > 1.0) { R = -C.x; }
    if (vT.y > 1.0) { T = -C.y; }
    if (vB.y < 0.0) { B = -C.y; }
    float div = 0.5 * (R - L + T - B);
    gl_FragColor = vec4(div, 0.0, 0.0, 1.0);
}
`;

const CURL_SHADER = `
precision mediump float;
precision mediump sampler2D;
varying highp vec2 vUv;
varying highp vec2 vL;
varying highp vec2 vR;
varying highp vec2 vT;
varying highp vec2 vB;
uniform sampler2D uVelocity;
void main () {
    float L = texture2D(uVelocity, vL).y;
    float R = texture2D(uVelocity, vR).y;
    float T = texture2D(uVelocity, vT).x;
    float B = texture2D(uVelocity, vB).x;
    float vorticity = R - L - T + B;
    gl_FragColor = vec4(0.5 * vorticity, 0.0, 0.0, 1.0);
}
`;

const VORTICITY_SHADER = `
precision highp float;
precision highp sampler2D;
varying vec2 vUv;
varying vec2 vL;
varying vec2 vR;
varying vec2 vT;
varying vec2 vB;
uniform sampler2D uVelocity;
uniform sampler2D uCurl;
uniform float curl;
uniform float dt;
void main () {
    float L = texture2D(uCurl, vL).x;
    float R = texture2D(uCurl, vR).x;
    float T = texture2D(uCurl, vT).x;
    float B = texture2D(uCurl, vB).x;
    float C = texture2D(uCurl, vUv).x;
    vec2 force = 0.5 * vec2(abs(T) - abs(B), abs(R) - abs(L));
    force /= length(force) + 0.0001;
    force *= curl * C;
    force.y *= -1.0;
    vec2 velocity = texture2D(uVelocity, vUv).xy;
    velocity += force * dt;
    velocity = min(max(velocity, -1000.0), 1000.0);
    gl_FragColor = vec4(velocity, 0.0, 1.0);
}
`;

const PRESSURE_SHADER = `
precision mediump float;
precision mediump sampler2D;
varying highp vec2 vUv;
varying highp vec2 vL;
varying highp vec2 vR;
varying highp vec2 vT;
varying highp vec2 vB;
uniform sampler2D uPressure;
uniform sampler2D uDivergence;
void main () {
    float L = texture2D(uPressure, vL).x;
    float R = texture2D(uPressure, vR).x;
    float T = texture2D(uPressure, vT).x;
    float B = texture2D(uPressure, vB).x;
    float divergence = texture2D(uDivergence, vUv).x;
    float pressure = (L + R + B + T - divergence) * 0.25;
    gl_FragColor = vec4(pressure, 0.0, 0.0, 1.0);
}
`;

const GRADIENT_SUBTRACT_SHADER = `
precision mediump float;
precision mediump sampler2D;
varying highp vec2 vUv;
varying highp vec2 vL;
varying highp vec2 vR;
varying highp vec2 vT;
varying highp vec2 vB;
uniform sampler2D uPressure;
uniform sampler2D uVelocity;
void main () {
    float L = texture2D(uPressure, vL).x;
    float R = texture2D(uPressure, vR).x;
    float T = texture2D(uPressure, vT).x;
    float B = texture2D(uPressure, vB).x;
    vec2 velocity = texture2D(uVelocity, vUv).xy;
    velocity.xy -= vec2(R - L, T - B);
    gl_FragColor = vec4(velocity, 0.0, 1.0);
}
`;

const DISPLAY_SHADER = `
precision highp float;
precision highp sampler2D;
varying vec2 vUv;
uniform sampler2D uTexture;
void main () {
    vec3 c = texture2D(uTexture, vUv).rgb;
    gl_FragColor = vec4(c + 0.039216, 1.0);
}
`;

function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255].map(
    (c) => c * CONFIG.COLOR_INTENSITY
  ) as [number, number, number];
}

export default function FluidCanvas() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const maybeCanvas = canvasRef.current;
    if (!maybeCanvas) return;
    if (typeof window === "undefined") return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const canvas: HTMLCanvasElement = maybeCanvas;

    const contextAttrs: WebGLContextAttributes = {
      alpha: false,
      depth: false,
      stencil: false,
      antialias: false,
      preserveDrawingBuffer: false,
    };

    const gl2Context = canvas.getContext("webgl2", contextAttrs);
    const gl1Context = gl2Context
      ? null
      : canvas.getContext("webgl", contextAttrs) ||
        canvas.getContext("experimental-webgl", contextAttrs);
    if (!gl2Context && !gl1Context) return;
    const isWebGL2 = !!gl2Context;
    const gl = (gl2Context ?? gl1Context) as unknown as WebGLRenderingContext;

    let halfFloatType: number;
    let supportLinearFiltering: boolean;
    if (isWebGL2) {
      gl.getExtension("EXT_color_buffer_float");
      halfFloatType = (gl as WebGL2RenderingContext).HALF_FLOAT;
      supportLinearFiltering = true;
    } else {
      const ext = gl.getExtension("OES_texture_half_float");
      if (!ext || !gl.getExtension("OES_texture_half_float_linear")) return;
      halfFloatType = ext.HALF_FLOAT_OES;
      supportLinearFiltering = true;
    }

    function testRenderTextureFormat(internalFormat: number, format: number): boolean {
      const texture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texImage2D(gl.TEXTURE_2D, 0, internalFormat, 4, 4, 0, format, halfFloatType, null);
      const fbo = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
      gl.framebufferTexture2D(
        gl.FRAMEBUFFER,
        gl.COLOR_ATTACHMENT0,
        gl.TEXTURE_2D,
        texture,
        0
      );
      const ok = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE;
      gl.deleteFramebuffer(fbo);
      gl.deleteTexture(texture);
      return ok;
    }

    function getSupportedFormat(internalFormat: number, format: number): Format | null {
      if (testRenderTextureFormat(internalFormat, format)) {
        return { internalFormat, format };
      }
      if (isWebGL2) {
        switch (internalFormat) {
          case (gl as WebGL2RenderingContext).R16F:
            return getSupportedFormat(
              (gl as WebGL2RenderingContext).RG16F,
              (gl as WebGL2RenderingContext).RG
            );
          case (gl as WebGL2RenderingContext).RG16F:
            return getSupportedFormat(
              (gl as WebGL2RenderingContext).RGBA16F,
              gl.RGBA
            );
          default:
            return null;
        }
      }
      return null;
    }

    let formatRGBA: Format | null;
    let formatRG: Format | null;
    let formatR: Format | null;
    if (isWebGL2) {
      const gl2 = gl as WebGL2RenderingContext;
      formatRGBA = getSupportedFormat(gl2.RGBA16F, gl2.RGBA);
      formatRG = getSupportedFormat(gl2.RG16F, gl2.RG);
      formatR = getSupportedFormat(gl2.R16F, gl2.RED);
    } else {
      formatRGBA = getSupportedFormat(gl.RGBA, gl.RGBA);
      formatRG = formatRGBA;
      formatR = formatRGBA;
    }
    if (!formatRGBA || !formatRG || !formatR) return;

    function compile(type: number, source: string): WebGLShader | null {
      const shader = gl.createShader(type);
      if (!shader) return null;
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        console.warn("fluid shader error:", gl.getShaderInfoLog(shader));
        gl.deleteShader(shader);
        return null;
      }
      return shader;
    }

    function createProgram(vsSource: string, fsSource: string): WebGLProgram | null {
      const vs = compile(gl.VERTEX_SHADER, vsSource);
      const fs = compile(gl.FRAGMENT_SHADER, fsSource);
      if (!vs || !fs) return null;
      const program = gl.createProgram();
      if (!program) return null;
      gl.attachShader(program, vs);
      gl.attachShader(program, fs);
      gl.bindAttribLocation(program, 0, "aPosition");
      gl.linkProgram(program);
      gl.deleteShader(vs);
      gl.deleteShader(fs);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        console.warn("fluid program link error:", gl.getProgramInfoLog(program));
        gl.deleteProgram(program);
        return null;
      }
      return program;
    }

    class Program {
      program: WebGLProgram;
      uniforms: Record<string, WebGLUniformLocation> = {};
      constructor(vsSource: string, fsSource: string) {
        this.program = createProgram(vsSource, fsSource)!;
        const count = gl.getProgramParameter(this.program, gl.ACTIVE_UNIFORMS) as number;
        for (let i = 0; i < count; i++) {
          const name = gl.getActiveUniform(this.program, i)!.name;
          const loc = gl.getUniformLocation(this.program, name);
          if (loc) this.uniforms[name] = loc;
        }
      }
      bind() {
        gl.useProgram(this.program);
      }
    }

    const advectionSource = supportLinearFiltering
      ? ADVECTION_SHADER
      : `#define MANUAL_FILTERING\n${ADVECTION_SHADER}`;

    const copyProgram = new Program(BASE_VERTEX, COPY_SHADER);
    const clearProgram = new Program(BASE_VERTEX, CLEAR_SHADER);
    const splatProgram = new Program(BASE_VERTEX, SPLAT_SHADER);
    const advectionProgram = new Program(BASE_VERTEX, advectionSource);
    const divergenceProgram = new Program(BASE_VERTEX, DIVERGENCE_SHADER);
    const curlProgram = new Program(BASE_VERTEX, CURL_SHADER);
    const vorticityProgram = new Program(BASE_VERTEX, VORTICITY_SHADER);
    const pressureProgram = new Program(BASE_VERTEX, PRESSURE_SHADER);
    const gradientSubtractProgram = new Program(BASE_VERTEX, GRADIENT_SUBTRACT_SHADER);
    const displayProgram = new Program(BASE_VERTEX, DISPLAY_SHADER);

    if (
      !copyProgram.program ||
      !clearProgram.program ||
      !splatProgram.program ||
      !advectionProgram.program ||
      !divergenceProgram.program ||
      !curlProgram.program ||
      !vorticityProgram.program ||
      !pressureProgram.program ||
      !gradientSubtractProgram.program ||
      !displayProgram.program
    ) {
      return;
    }

    const quadVbo = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, quadVbo);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, -1, 1, 1, 1, 1, -1]), gl.STATIC_DRAW);
    const quadIbo = gl.createBuffer();
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, quadIbo);
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array([0, 1, 2, 0, 2, 3]), gl.STATIC_DRAW);
    gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
    gl.enableVertexAttribArray(0);
    gl.disable(gl.BLEND);

    function blit(target: FBO | null) {
      if (target === null) {
        gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
        gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      } else {
        gl.viewport(0, 0, target.width, target.height);
        gl.bindFramebuffer(gl.FRAMEBUFFER, target.fbo);
      }
      gl.drawElements(gl.TRIANGLES, 6, gl.UNSIGNED_SHORT, 0);
    }

    function createFBO(
      w: number,
      h: number,
      internalFormat: number,
      format: number,
      type: number,
      param: number
    ): FBO {
      const texture = gl.createTexture()!;
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, param);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, param);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texImage2D(gl.TEXTURE_2D, 0, internalFormat, w, h, 0, format, type, null);
      const fbo = gl.createFramebuffer()!;
      gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, texture, 0);
      gl.viewport(0, 0, w, h);
      gl.clearColor(0, 0, 0, 1);
      gl.clear(gl.COLOR_BUFFER_BIT);
      return {
        texture,
        fbo,
        width: w,
        height: h,
        texelSizeX: 1 / w,
        texelSizeY: 1 / h,
        attach(id: number) {
          gl.activeTexture(gl.TEXTURE0 + id);
          gl.bindTexture(gl.TEXTURE_2D, texture);
          return id;
        },
      };
    }

    function deleteFBO(target: FBO) {
      gl.deleteTexture(target.texture);
      gl.deleteFramebuffer(target.fbo);
    }

    function createDoubleFBO(
      w: number,
      h: number,
      internalFormat: number,
      format: number,
      type: number,
      param: number
    ): DoubleFBO {
      const fbo1 = createFBO(w, h, internalFormat, format, type, param);
      const fbo2 = createFBO(w, h, internalFormat, format, type, param);
      return {
        width: w,
        height: h,
        texelSizeX: fbo1.texelSizeX,
        texelSizeY: fbo1.texelSizeY,
        read: fbo1,
        write: fbo2,
        swap() {
          const temp = this.read;
          this.read = this.write;
          this.write = temp;
        },
      };
    }

    function deleteDoubleFBO(target: DoubleFBO) {
      deleteFBO(target.read);
      deleteFBO(target.write);
    }

    function getResolution(resolution: number): { width: number; height: number } {
      let aspect = gl.drawingBufferWidth / gl.drawingBufferHeight;
      if (aspect < 1) aspect = 1 / aspect;
      const min = Math.round(resolution);
      const max = Math.round(resolution * aspect);
      if (gl.drawingBufferWidth > gl.drawingBufferHeight) {
        return { width: max, height: min };
      }
      return { width: min, height: max };
    }

    let dye: DoubleFBO;
    let velocity: DoubleFBO;
    let divergence: FBO;
    let curl: FBO;
    let pressure: DoubleFBO;

    function initFramebuffers() {
      const simRes = getResolution(CONFIG.SIM_RESOLUTION);
      const dyeRes = getResolution(CONFIG.DYE_RESOLUTION);
      const filtering = supportLinearFiltering ? gl.LINEAR : gl.NEAREST;

      if (dye) deleteDoubleFBO(dye);
      if (velocity) deleteDoubleFBO(velocity);
      if (divergence) deleteFBO(divergence);
      if (curl) deleteFBO(curl);
      if (pressure) deleteDoubleFBO(pressure);

      dye = createDoubleFBO(
        dyeRes.width,
        dyeRes.height,
        formatRGBA!.internalFormat,
        formatRGBA!.format,
        halfFloatType,
        filtering
      );
      velocity = createDoubleFBO(
        simRes.width,
        simRes.height,
        formatRG!.internalFormat,
        formatRG!.format,
        halfFloatType,
        filtering
      );
      divergence = createFBO(
        simRes.width,
        simRes.height,
        formatR!.internalFormat,
        formatR!.format,
        halfFloatType,
        gl.NEAREST
      );
      curl = createFBO(
        simRes.width,
        simRes.height,
        formatR!.internalFormat,
        formatR!.format,
        halfFloatType,
        gl.NEAREST
      );
      pressure = createDoubleFBO(
        simRes.width,
        simRes.height,
        formatR!.internalFormat,
        formatR!.format,
        halfFloatType,
        gl.NEAREST
      );
    }

    function correctRadius(radius: number): number {
      const aspect = canvas.width / canvas.height;
      if (aspect > 1) radius *= aspect;
      return radius;
    }

    function splat(
      x: number,
      y: number,
      dx: number,
      dy: number,
      color: [number, number, number]
    ) {
      splatProgram.bind();
      gl.uniform1i(splatProgram.uniforms.uTarget, velocity.read.attach(0));
      gl.uniform1f(splatProgram.uniforms.aspectRatio, canvas.width / canvas.height);
      gl.uniform2f(splatProgram.uniforms.point, x, y);
      gl.uniform3f(splatProgram.uniforms.color, dx, dy, 0);
      gl.uniform1f(splatProgram.uniforms.radius, correctRadius(CONFIG.SPLAT_RADIUS / 100));
      blit(velocity.write);
      velocity.swap();

      gl.uniform1i(splatProgram.uniforms.uTarget, dye.read.attach(0));
      gl.uniform3f(splatProgram.uniforms.color, color[0], color[1], color[2]);
      blit(dye.write);
      dye.swap();
    }

    function step(dt: number) {
      gl.disable(gl.BLEND);

      curlProgram.bind();
      gl.uniform2f(curlProgram.uniforms.texelSize, velocity.texelSizeX, velocity.texelSizeY);
      gl.uniform1i(curlProgram.uniforms.uVelocity, velocity.read.attach(0));
      blit(curl);

      vorticityProgram.bind();
      gl.uniform2f(vorticityProgram.uniforms.texelSize, velocity.texelSizeX, velocity.texelSizeY);
      gl.uniform1i(vorticityProgram.uniforms.uVelocity, velocity.read.attach(0));
      gl.uniform1i(vorticityProgram.uniforms.uCurl, curl.attach(1));
      gl.uniform1f(vorticityProgram.uniforms.curl, CONFIG.CURL);
      gl.uniform1f(vorticityProgram.uniforms.dt, dt);
      blit(velocity.write);
      velocity.swap();

      divergenceProgram.bind();
      gl.uniform2f(divergenceProgram.uniforms.texelSize, velocity.texelSizeX, velocity.texelSizeY);
      gl.uniform1i(divergenceProgram.uniforms.uVelocity, velocity.read.attach(0));
      blit(divergence);

      clearProgram.bind();
      gl.uniform1i(clearProgram.uniforms.uTexture, pressure.read.attach(0));
      gl.uniform1f(clearProgram.uniforms.value, CONFIG.PRESSURE);
      blit(pressure.write);
      pressure.swap();

      pressureProgram.bind();
      gl.uniform2f(pressureProgram.uniforms.texelSize, velocity.texelSizeX, velocity.texelSizeY);
      gl.uniform1i(pressureProgram.uniforms.uDivergence, divergence.attach(0));
      for (let i = 0; i < CONFIG.PRESSURE_ITERATIONS; i++) {
        gl.uniform1i(pressureProgram.uniforms.uPressure, pressure.read.attach(1));
        blit(pressure.write);
        pressure.swap();
      }

      gradientSubtractProgram.bind();
      gl.uniform2f(
        gradientSubtractProgram.uniforms.texelSize,
        velocity.texelSizeX,
        velocity.texelSizeY
      );
      gl.uniform1i(gradientSubtractProgram.uniforms.uPressure, pressure.read.attach(0));
      gl.uniform1i(gradientSubtractProgram.uniforms.uVelocity, velocity.read.attach(1));
      blit(velocity.write);
      velocity.swap();

      advectionProgram.bind();
      gl.uniform2f(advectionProgram.uniforms.texelSize, velocity.texelSizeX, velocity.texelSizeY);
      if (!supportLinearFiltering) {
        gl.uniform2f(
          advectionProgram.uniforms.dyeTexelSize,
          velocity.texelSizeX,
          velocity.texelSizeY
        );
      }
      const velocityId = velocity.read.attach(0);
      gl.uniform1i(advectionProgram.uniforms.uVelocity, velocityId);
      gl.uniform1i(advectionProgram.uniforms.uSource, velocityId);
      gl.uniform1f(advectionProgram.uniforms.dt, dt);
      gl.uniform1f(advectionProgram.uniforms.dissipation, CONFIG.VELOCITY_DISSIPATION);
      blit(velocity.write);
      velocity.swap();

      if (!supportLinearFiltering) {
        gl.uniform2f(advectionProgram.uniforms.dyeTexelSize, dye.texelSizeX, dye.texelSizeY);
      }
      gl.uniform1i(advectionProgram.uniforms.uVelocity, velocity.read.attach(0));
      gl.uniform1i(advectionProgram.uniforms.uSource, dye.read.attach(1));
      gl.uniform1f(advectionProgram.uniforms.dissipation, CONFIG.DENSITY_DISSIPATION);
      blit(dye.write);
      dye.swap();
    }

    function render() {
      displayProgram.bind();
      gl.uniform1i(displayProgram.uniforms.uTexture, dye.read.attach(0));
      blit(null);
    }

    function resizeCanvas(): boolean {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const width = Math.floor(canvas.clientWidth * dpr);
      const height = Math.floor(canvas.clientHeight * dpr);
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
        return true;
      }
      return false;
    }

    const pointers = new Map<number, PointerState>();

    function adoptPointer(e: PointerEvent): PointerState {
      const ptr: PointerState = {
        x: e.clientX / canvas.clientWidth,
        y: 1 - e.clientY / canvas.clientHeight,
        dx: 0,
        dy: 0,
        moved: false,
        color: hexToRgb(PALETTE[Math.floor(Math.random() * PALETTE.length)]),
      };
      pointers.set(e.pointerId, ptr);
      return ptr;
    }

    function onPointerDown(e: PointerEvent) {
      adoptPointer(e);
    }

    function onPointerMove(e: PointerEvent) {
      const ptr = pointers.get(e.pointerId) ?? adoptPointer(e);
      const x = e.clientX / canvas.clientWidth;
      const y = 1 - e.clientY / canvas.clientHeight;
      let dx = x - ptr.x;
      let dy = y - ptr.y;
      const aspect = canvas.width / canvas.height;
      if (aspect < 1) dx *= aspect;
      else dy /= aspect;
      ptr.dx = dx;
      ptr.dy = dy;
      ptr.x = x;
      ptr.y = y;
      ptr.moved = dx !== 0 || dy !== 0;
    }

    function releasePointer(e: PointerEvent) {
      pointers.delete(e.pointerId);
    }

    window.addEventListener("pointerdown", onPointerDown, { passive: true });
    window.addEventListener("pointermove", onPointerMove, { passive: true });
    window.addEventListener("pointerup", releasePointer, { passive: true });
    window.addEventListener("pointercancel", releasePointer, { passive: true });

    initFramebuffers();

    let raf = 0;
    let lastTime = performance.now();

    function frame(now: number) {
      const dt = Math.min((now - lastTime) / 1000, 1 / 60);
      lastTime = now;
      if (resizeCanvas()) initFramebuffers();

      pointers.forEach((p) => {
        if (p.moved) {
          p.moved = false;
          splat(p.x, p.y, p.dx * CONFIG.SPLAT_FORCE, p.dy * CONFIG.SPLAT_FORCE, p.color);
        }
      });

      step(dt);
      render();
      raf = requestAnimationFrame(frame);
    }
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", releasePointer);
      window.removeEventListener("pointercancel", releasePointer);

      if (dye) deleteDoubleFBO(dye);
      if (velocity) deleteDoubleFBO(velocity);
      if (divergence) deleteFBO(divergence);
      if (curl) deleteFBO(curl);
      if (pressure) deleteDoubleFBO(pressure);

      [
        copyProgram,
        clearProgram,
        splatProgram,
        advectionProgram,
        divergenceProgram,
        curlProgram,
        vorticityProgram,
        pressureProgram,
        gradientSubtractProgram,
        displayProgram,
      ].forEach((p) => gl.deleteProgram(p.program));

      gl.deleteBuffer(quadVbo);
      gl.deleteBuffer(quadIbo);

      // No WEBGL_lose_context here: React StrictMode remounts effects on the
      // same <canvas>, and a lost context is permanent — the second mount
      // would render nothing. The canvas element is discarded on unmount, so
      // GC reclaims the context naturally.
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 h-full w-full"
    />
  );
}
