"use client";

import React, { useEffect, useRef } from "react";

/** Deterministic PRNG so the sky looks the same on every visit. */
function mulberry32(seed: number) {
  let s = seed;
  return () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface Star {
  x: number;
  y: number;
  r: number;
  a: number;
  depth: number;
  tint: string;
  phase: number;
}

const TINTS = ["255,255,255", "255,238,220", "216,228,255", "255,214,196", "200,214,255"];

/**
 * Decorative background sky (not data): a slow three-layer parallax star field.
 * Stops entirely under prefers-reduced-motion and while the tab is hidden.
 */
export function Starfield() {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const rand = mulberry32(20260914);
    const stars: Star[] = Array.from({ length: 1100 }, () => {
      const roll = rand();
      const layer = roll < 0.72 ? 0 : roll < 0.94 ? 1 : 2;
      return {
        x: rand(),
        y: rand(),
        r: [0.45, 0.8, 1.25][layer] * (0.7 + rand() * 0.6),
        a: [0.28, 0.55, 0.9][layer] * (0.55 + rand() * 0.45),
        depth: [0.35, 0.7, 1.2][layer],
        tint: TINTS[Math.floor(rand() * TINTS.length)],
        phase: rand() * Math.PI * 2,
      };
    });

    let w = 0;
    let h = 0;
    let raf = 0;
    let px = 0;
    let py = 0;
    let tx = 0;
    let ty = 0;

    const draw = (t: number) => {
      ctx.clearRect(0, 0, w, h);
      const glow = ctx.createRadialGradient(w * 0.6, h * 0.45, 0, w * 0.6, h * 0.45, Math.max(w, h) * 0.75);
      glow.addColorStop(0, "rgba(140,150,190,0.075)");
      glow.addColorStop(0.45, "rgba(90,80,90,0.035)");
      glow.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, w, h);

      px += (tx - px) * 0.04;
      py += (ty - py) * 0.04;
      const drift = reduce ? 0 : t * 0.0000035;
      for (const s of stars) {
        let x = (s.x + drift * s.depth) % 1;
        if (x < 0) x += 1;
        const sx = x * w + px * s.depth * 14;
        const sy = s.y * h + py * s.depth * 14;
        const twinkle = reduce ? 1 : 0.78 + 0.22 * Math.sin(t * 0.0011 + s.phase);
        ctx.fillStyle = `rgba(${s.tint},${(s.a * twinkle).toFixed(3)})`;
        if (s.r < 0.9) {
          ctx.fillRect(sx, sy, s.r * 1.6, s.r * 1.6);
        } else {
          ctx.beginPath();
          ctx.arc(sx, sy, s.r, 0, Math.PI * 2);
          ctx.fill();
        }
      }
      if (!reduce && !document.hidden) raf = requestAnimationFrame(draw);
    };

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (reduce) draw(0);
    };
    const onMove = (e: PointerEvent) => {
      tx = e.clientX / Math.max(w, 1) - 0.5;
      ty = e.clientY / Math.max(h, 1) - 0.5;
    };
    const onVisibility = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden && !reduce) raf = requestAnimationFrame(draw);
    };

    resize();
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", onVisibility);
    if (!reduce) {
      window.addEventListener("pointermove", onMove, { passive: true });
      raf = requestAnimationFrame(draw);
    }
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return <canvas ref={ref} aria-hidden="true" className="pointer-events-none fixed inset-0" />;
}
