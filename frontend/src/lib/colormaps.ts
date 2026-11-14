export type ColormapName = "inferno" | "viridis" | "magma" | "grayscale";

type RGB = [number, number, number];

const STOPS: Record<ColormapName, RGB[]> = {
  inferno: [
    [0, 0, 4],
    [40, 11, 84],
    [101, 21, 110],
    [159, 42, 99],
    [212, 72, 66],
    [245, 125, 21],
    [250, 193, 39],
    [252, 255, 164],
  ],
  viridis: [
    [68, 1, 84],
    [71, 44, 122],
    [59, 81, 139],
    [44, 113, 142],
    [33, 144, 141],
    [39, 173, 129],
    [92, 200, 99],
    [253, 231, 37],
  ],
  magma: [
    [0, 0, 4],
    [28, 16, 68],
    [79, 18, 123],
    [129, 37, 129],
    [181, 54, 122],
    [229, 80, 100],
    [251, 135, 97],
    [252, 253, 191],
  ],
  grayscale: [
    [0, 0, 0],
    [255, 255, 255],
  ],
};

function interpolateStops(stops: RGB[], t: number): RGB {
  const clamped = Math.max(0, Math.min(1, t));
  const scaled = clamped * (stops.length - 1);
  const idx = Math.floor(scaled);
  const frac = scaled - idx;
  const c0 = stops[idx];
  const c1 = stops[Math.min(idx + 1, stops.length - 1)];
  return [
    Math.round(c0[0] + (c1[0] - c0[0]) * frac),
    Math.round(c0[1] + (c1[1] - c0[1]) * frac),
    Math.round(c0[2] + (c1[2] - c0[2]) * frac),
  ];
}

const LUT_CACHE: Partial<Record<ColormapName, Uint8ClampedArray>> = {};

export function getColormapLut(name: ColormapName): Uint8ClampedArray {
  const existing = LUT_CACHE[name];
  if (existing) return existing;

  const lut = new Uint8ClampedArray(256 * 3);
  const stops = STOPS[name];
  for (let i = 0; i < 256; i++) {
    const [r, g, b] = interpolateStops(stops, i / 255);
    lut[i * 3] = r;
    lut[i * 3 + 1] = g;
    lut[i * 3 + 2] = b;
  }
  LUT_CACHE[name] = lut;
  return lut;
}

export interface DetectionOverlay {
  x?: number;
  y?: number;
  snr?: number;
  sign?: "positive" | "negative";
}

/**
 * Renders a row-major sky array (row 0 = south edge, col 0 = east edge)
 * onto an HTMLCanvasElement with north up and east left.
 */
export function renderSkyArrayToCanvas(
  canvas: HTMLCanvasElement,
  data: number[],
  width: number,
  height: number,
  colormap: ColormapName,
  options?: { symmetric?: boolean; detections?: DetectionOverlay[] }
): void {
  if (width <= 0 || height <= 0 || data.length < width * height) return;

  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const sorted = [...data].filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (sorted.length === 0) return;

  let pLow = sorted[Math.floor(sorted.length * 0.02)] ?? sorted[0];
  let pHigh = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.995))] ?? sorted[sorted.length - 1];

  if (options?.symmetric) {
    const maxAbs = Math.max(
      Math.abs(sorted[Math.floor(sorted.length * 0.005)] ?? pLow),
      Math.abs(sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.995))] ?? pHigh),
      1e-6
    );
    pLow = -maxAbs;
    pHigh = maxAbs;
  }

  const span = Math.max(pHigh - pLow, 1e-6);
  const lut = getColormapLut(colormap);
  const imgData = ctx.createImageData(width, height);
  const pixels = imgData.data;

  const asinhScale = 3.0;
  const normMax = Math.asinh(asinhScale);

  for (let row = 0; row < height; row++) {
    const canvasY = height - 1 - row;
    for (let col = 0; col < width; col++) {
      const val = data[row * width + col];
      let stretched: number;
      if (options?.symmetric) {
        const signed = Math.max(-1, Math.min(1, val / (span / 2)));
        stretched = 0.5 + 0.5 * (Math.asinh(signed * asinhScale) / normMax);
      } else {
        const linear = Math.max(0, Math.min(1, (val - pLow) / span));
        stretched = Math.asinh(linear * asinhScale) / normMax;
      }
      const idx = Math.max(0, Math.min(255, Math.round(stretched * 255)));

      const outOffset = (canvasY * width + col) * 4;
      pixels[outOffset] = lut[idx * 3];
      pixels[outOffset + 1] = lut[idx * 3 + 1];
      pixels[outOffset + 2] = lut[idx * 3 + 2];
      pixels[outOffset + 3] = 255;
    }
  }

  ctx.putImageData(imgData, 0, 0);

  if (options?.detections && options.detections.length > 0) {
    for (const det of options.detections) {
      if (det.x === undefined || det.y === undefined) continue;
      const cx = det.x;
      const cy = height - 1 - det.y;
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, 4.2, 0, Math.PI * 2);
      ctx.lineWidth = 1.25;
      ctx.strokeStyle = det.sign === "negative" ? "#f43f5e" : "#10b981";
      ctx.stroke();
      ctx.restore();
    }
  }
}
