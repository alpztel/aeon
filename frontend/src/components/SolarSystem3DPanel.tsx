"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { AlertTriangle, Compass, Loader2, Orbit, Sparkles } from "lucide-react";
import { useI18n } from "@/i18n/context";
import {
  simulateOrbit,
  type AstrometryPoint,
  type CatalogObject,
  type OrbitResult,
} from "@/lib/api";

interface SolarSystem3DPanelProps {
  coords: { ra: number; dec: number };
  selectedObject: CatalogObject | null;
  astrometry?: AstrometryPoint[];
}

function scaleVec(x: number, y: number, z: number, logRadial: boolean): THREE.Vector3 {
  const r = Math.hypot(x, y, z);
  if (r < 1e-9) return new THREE.Vector3(0, 0, 0);
  // Three.js is Y-up; map ecliptic (x, y, z) -> (x, z, -y)
  const factor = logRadial ? (Math.log10(1 + r) * 18) / r : 0.085;
  return new THREE.Vector3(x * factor, z * factor, -y * factor);
}

const PLANET_COLORS: Record<string, number> = {
  Jupiter: 0xf59e0b,
  Saturn: 0xfde047,
  Uranus: 0x38bdf8,
  Neptune: 0x6366f1,
};

export function SolarSystem3DPanel({
  coords,
  selectedObject,
  astrometry,
}: SolarSystem3DPanelProps) {
  const { dict } = useI18n();

  const [orbit, setOrbit] = useState<OrbitResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fromCache, setFromCache] = useState(false);
  const [logScale, setLogScale] = useState(true);

  const mountRef = useRef<HTMLDivElement | null>(null);

  const runSimulation = useCallback(
    async (mode: "px" | "current" | "fit") => {
      setLoading(true);
      setError(null);
      try {
        const req =
          mode === "fit" && astrometry && astrometry.length >= 3
            ? { detections: astrometry, horizons_years: [1, 5, 10], samples_per_year: 24 }
            : mode === "px" || selectedObject?.id === "px-2026-09"
              ? { target_id: "px-2026-09", horizons_years: [1, 5, 10], samples_per_year: 24 }
              : {
                  observation: {
                    ra: coords.ra,
                    dec: coords.dec,
                    distance_au: selectedObject?.distance_au ?? 520,
                    rate_arcsec_yr: 110,
                    pa_deg: 62,
                    radial_velocity_km_s: 0,
                  },
                  horizons_years: [1, 5, 10],
                  samples_per_year: 24,
                };
        const { data, fromCache: cached } = await simulateOrbit(req);
        setOrbit(data);
        setFromCache(cached);
      } catch {
        setError(dict.orbit.error);
      } finally {
        setLoading(false);
      }
    },
    [astrometry, coords.ra, coords.dec, selectedObject, dict.orbit.error]
  );

  useEffect(() => {
    let active = true;
    const isPx = !selectedObject || selectedObject.id === "px-2026-09";
    const req = isPx
      ? { target_id: "px-2026-09", horizons_years: [1, 5, 10], samples_per_year: 24 }
      : {
          observation: {
            ra: coords.ra,
            dec: coords.dec,
            distance_au:
              selectedObject.distance_au ??
              (selectedObject.distance_pc ? selectedObject.distance_pc * 206265 : 520),
            rate_arcsec_yr: Math.hypot(
              selectedObject.pm_ra_cosdec_arcsec_yr ?? 0,
              selectedObject.pm_dec_arcsec_yr ?? 0
            ),
            pa_deg: 275,
            radial_velocity_km_s: 0,
          },
          horizons_years: [1, 5, 10],
          samples_per_year: 24,
        };
    simulateOrbit(req)
      .then(({ data, fromCache: cached }) => {
        if (!active) return;
        setOrbit(data);
        setFromCache(cached);
        setError(null);
      })
      .catch(() => {
        if (!active) return;
        setError(dict.orbit.error);
      });
    return () => {
      active = false;
    };
  }, [coords.ra, coords.dec, selectedObject, dict.orbit.error]);

  // Build Three.js scene
  useEffect(() => {
    const container = mountRef.current;
    if (!container || !orbit) return;

    const width = container.clientWidth || 640;
    const height = container.clientHeight || 420;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x050506);

    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 2000);
    let spherical = { radius: 85, theta: Math.PI / 4, phi: Math.PI / 3.1 };

    const updateCamera = () => {
      camera.position.x =
        spherical.radius * Math.sin(spherical.phi) * Math.cos(spherical.theta);
      camera.position.y = spherical.radius * Math.cos(spherical.phi);
      camera.position.z =
        spherical.radius * Math.sin(spherical.phi) * Math.sin(spherical.theta);
      camera.lookAt(0, 0, 0);
    };
    updateCamera();

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.innerHTML = "";
    container.appendChild(renderer.domElement);

    // Sun at origin
    const sunGeo = new THREE.SphereGeometry(1.4, 24, 24);
    const sunMat = new THREE.MeshBasicMaterial({ color: 0xfbbf24 });
    scene.add(new THREE.Mesh(sunGeo, sunMat));

    // SPHEREx 90-degree scan cone
    const coneGeo = new THREE.ConeGeometry(16, 22, 32, 1, true);
    const coneMat = new THREE.MeshBasicMaterial({
      color: 0x22d3ee,
      wireframe: true,
      transparent: true,
      opacity: 0.14,
    });
    const coneMesh = new THREE.Mesh(coneGeo, coneMat);
    coneMesh.rotation.z = Math.PI / 2;
    scene.add(coneMesh);

    // Kuiper Belt particle ring (30 - 50 AU)
    const kbCount = 450;
    const kbPositions = new Float32Array(kbCount * 3);
    for (let i = 0; i < kbCount; i++) {
      const rAu = 30 + ((i * 73) % 200) / 10;
      const angle = (i / kbCount) * Math.PI * 2 + (i % 7) * 0.13;
      const zAu = (((i * 29) % 100) / 100 - 0.5) * 3.5;
      const v = scaleVec(rAu * Math.cos(angle), rAu * Math.sin(angle), zAu, logScale);
      kbPositions[i * 3] = v.x;
      kbPositions[i * 3 + 1] = v.y;
      kbPositions[i * 3 + 2] = v.z;
    }
    const kbGeo = new THREE.BufferGeometry();
    kbGeo.setAttribute("position", new THREE.BufferAttribute(kbPositions, 3));
    const kbMat = new THREE.PointsMaterial({
      color: 0x64748b,
      size: 0.45,
      transparent: true,
      opacity: 0.65,
    });
    scene.add(new THREE.Points(kbGeo, kbMat));

    // Giant planets (Jupiter - Neptune)
    for (const planet of orbit.planets ?? []) {
      const pts = (planet.trajectory ?? []).map((s) =>
        scaleVec(s.x, s.y, s.z, logScale)
      );
      if (pts.length < 2) continue;
      const color = PLANET_COLORS[planet.name ?? ""] ?? 0x94a3b8;
      const lineGeo = new THREE.BufferGeometry().setFromPoints(pts);
      const lineMat = new THREE.LineBasicMaterial({
        color,
        transparent: true,
        opacity: 0.7,
      });
      scene.add(new THREE.Line(lineGeo, lineMat));

      const last = pts[pts.length - 1];
      const pMesh = new THREE.Mesh(
        new THREE.SphereGeometry(0.55, 12, 12),
        new THREE.MeshBasicMaterial({ color })
      );
      pMesh.position.copy(last);
      scene.add(pMesh);
    }

    // Full Keplerian ellipse of the test particle
    if (orbit.particle.orbit_ellipse && orbit.particle.orbit_ellipse.length > 2) {
      const ellPts = orbit.particle.orbit_ellipse.map((xyz) =>
        scaleVec(xyz[0] ?? 0, xyz[1] ?? 0, xyz[2] ?? 0, logScale)
      );
      const ellGeo = new THREE.BufferGeometry().setFromPoints(ellPts);
      const ellMat = new THREE.LineDashedMaterial({
        color: 0xa78bfa,
        dashSize: 1.5,
        gapSize: 1.0,
        transparent: true,
        opacity: 0.55,
      });
      const ellLine = new THREE.Line(ellGeo, ellMat);
      ellLine.computeLineDistances();
      scene.add(ellLine);
    }

    // 10-year integrated trajectory arc
    if (orbit.particle.trajectory && orbit.particle.trajectory.length > 1) {
      const arcPts = orbit.particle.trajectory.map((s) =>
        scaleVec(s.x, s.y, s.z, logScale)
      );
      const arcGeo = new THREE.BufferGeometry().setFromPoints(arcPts);
      const arcMat = new THREE.LineBasicMaterial({ color: 0xf43f5e, linewidth: 2 });
      scene.add(new THREE.Line(arcGeo, arcMat));
    }

    // 1 / 5 / 10 yr horizon glowing spheres
    for (const h of orbit.particle.horizons ?? []) {
      if (!h.xyz_au || h.xyz_au.length < 3) continue;
      const pos = scaleVec(h.xyz_au[0], h.xyz_au[1], h.xyz_au[2], logScale);
      const hMesh = new THREE.Mesh(
        new THREE.SphereGeometry(0.95, 16, 16),
        new THREE.MeshBasicMaterial({ color: 0x22d3ee })
      );
      hMesh.position.copy(pos);
      scene.add(hMesh);
    }

    let dragging = false;
    let prevX = 0;
    let prevY = 0;

    const onPointerDown = (e: PointerEvent) => {
      dragging = true;
      prevX = e.clientX;
      prevY = e.clientY;
    };
    const onPointerMove = (e: PointerEvent) => {
      if (!dragging) return;
      const dx = e.clientX - prevX;
      const dy = e.clientY - prevY;
      prevX = e.clientX;
      prevY = e.clientY;
      spherical = {
        ...spherical,
        theta: spherical.theta + dx * 0.008,
        phi: Math.max(0.2, Math.min(Math.PI - 0.2, spherical.phi - dy * 0.008)),
      };
      updateCamera();
      renderer.render(scene, camera);
    };
    const onPointerUp = () => {
      dragging = false;
    };
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      spherical = {
        ...spherical,
        radius: Math.max(20, Math.min(240, spherical.radius + e.deltaY * 0.05)),
      };
      updateCamera();
      renderer.render(scene, camera);
    };

    const dom = renderer.domElement;
    dom.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    dom.addEventListener("wheel", onWheel, { passive: false });

    renderer.render(scene, camera);

    return () => {
      dom.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      dom.removeEventListener("wheel", onWheel);
      scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh;
        if (mesh.geometry) {
          mesh.geometry.dispose();
        }
        if (mesh.material) {
          if (Array.isArray(mesh.material)) {
            mesh.material.forEach((m) => m.dispose());
          } else {
            mesh.material.dispose();
          }
        }
      });
      renderer.dispose();
    };
  }, [orbit, logScale]);

  return (
    <section className="aeon-panel rounded-2xl p-4 @xl:p-5">
      {/* Header */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2.5">
          <Orbit className="h-4 w-4 text-amber-400" />
          <h2 className="text-sm font-semibold uppercase tracking-wider text-white">
            {dict.orbit.title}
          </h2>
          {(selectedObject?.is_synthetic ?? true) && (
            <span className="inline-flex items-center gap-1 rounded-full border border-rose-500/40 bg-rose-500/15 px-2.5 py-0.5 text-[10px] font-semibold text-rose-300">
              <AlertTriangle className="h-3 w-3" />
              {dict.badges.synthetic}
            </span>
          )}
          {fromCache && (
            <span className="rounded-full border border-amber-400/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-300">
              {dict.header.dataMode.offline_cache}
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <button
            type="button"
            onClick={() => setLogScale((s) => !s)}
            className={`rounded-lg border px-2.5 py-1.5 font-medium transition ${
              logScale
                ? "border-cyan-400/40 bg-cyan-500/20 text-cyan-200"
                : "border-white/10 bg-white/5 text-slate-300"
            }`}
          >
            {logScale ? dict.orbit.logScale : dict.orbit.linearScale}
          </button>

          <button
            type="button"
            onClick={() => runSimulation("px")}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-amber-400/35 bg-amber-500/15 px-3 py-1.5 font-medium text-amber-200 transition hover:bg-amber-500/25 disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Compass className="h-3.5 w-3.5" />}
            <span>{dict.orbit.simulateTarget}</span>
          </button>

          {astrometry && astrometry.length >= 3 && (
            <button
              type="button"
              onClick={() => runSimulation("fit")}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-lg border border-violet-400/40 bg-violet-500/20 px-3 py-1.5 font-medium text-violet-200 transition hover:bg-violet-500/30 disabled:opacity-50"
            >
              <Sparkles className="h-3.5 w-3.5" />
              <span>{dict.orbit.fitAstrometry}</span>
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-3 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 @4xl:grid-cols-12">
        {/* 3D Canvas */}
        <div className="relative overflow-hidden rounded-xl border border-white/10 bg-black @4xl:col-span-7">
          <div ref={mountRef} className="h-[400px] w-full cursor-grab active:cursor-grabbing" />
          <div className="border-t border-white/10 bg-[#0E0E10]/90 px-3 py-2 text-[11px] text-slate-400">
            {dict.orbit.dragHint}
          </div>
        </div>

        {/* Horizons & Orbit Fit Telemetry */}
        <div className="flex flex-col justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.02] p-4 @4xl:col-span-5">
          <div className="space-y-3">
            {orbit && (
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <span className="aeon-mono rounded border border-white/10 bg-black/40 px-2 py-1 text-cyan-200">
                  {dict.orbit.engine}: {orbit.engine}
                </span>
                {orbit.energy_error !== undefined && (
                  <span className="aeon-mono rounded border border-emerald-400/30 bg-emerald-500/10 px-2 py-1 text-emerald-300">
                    {dict.orbit.energyError}: {orbit.energy_error.toExponential(2)}
                  </span>
                )}
              </div>
            )}

            {/* Astrometric Least-Squares Fit Summary */}
            {orbit?.fit && (
              <div className="rounded-xl border border-violet-400/35 bg-violet-500/10 p-3 text-xs">
                <h3 className="mb-2 font-semibold uppercase tracking-wider text-violet-200">
                  {dict.orbit.fitTitle}
                </h3>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <span className="text-[11px] text-slate-400">{dict.orbit.fitDist}:</span>
                    <p className="aeon-mono font-semibold text-white">
                      {orbit.fit.distance_au?.toFixed(1)}
                      {orbit.fit.distance_err_au ? ` ± ${orbit.fit.distance_err_au.toFixed(1)}` : ""} AU
                    </p>
                  </div>
                  <div>
                    <span className="text-[11px] text-slate-400">{dict.orbit.fitRate}:</span>
                    <p className="aeon-mono font-semibold text-amber-200">
                      {orbit.fit.rate_arcsec_yr?.toFixed(1)}″/yr ({orbit.fit.pa_deg?.toFixed(1)}°)
                    </p>
                  </div>
                  <div>
                    <span className="text-[11px] text-slate-400">{dict.orbit.fitRms}:</span>
                    <p className="aeon-mono text-cyan-200">
                      {orbit.fit.rms_residual_arcsec?.toFixed(3)}″
                    </p>
                  </div>
                  <div>
                    <span className="text-[11px] text-slate-400">{dict.orbit.fitChi2}:</span>
                    <p className="aeon-mono text-emerald-300">
                      {orbit.fit.reduced_chi2?.toFixed(2)}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* 1 / 5 / 10 yr Horizons Table */}
            <div>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-300">
                {dict.orbit.horizonsTitle}
              </h3>
              <div className="overflow-x-auto rounded-xl border border-white/10 bg-black/30">
                <table className="w-full text-left text-xs">
                  <thead className="border-b border-white/10 text-[11px] text-slate-400">
                    <tr>
                      <th className="p-2">{dict.orbit.horizonYr}</th>
                      <th className="p-2">{dict.orbit.raDec}</th>
                      <th className="p-2">{dict.orbit.heliocentricR}</th>
                      <th className="p-2">{dict.orbit.keplerDev}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {(orbit?.particle.horizons ?? []).map((h, i) => (
                      <tr key={i} className="aeon-mono text-[11px]">
                        <td className="p-2 font-semibold text-amber-300">+{h.years} yr</td>
                        <td className="p-2 text-cyan-200">
                          {h.ra?.toFixed(4)}°, {h.dec?.toFixed(4)}°
                        </td>
                        <td className="p-2 text-slate-200">{h.distance_au?.toFixed(2)}</td>
                        <td className="p-2 text-violet-300">
                          {h.kepler_only_deviation_km !== undefined
                            ? h.kepler_only_deviation_km.toLocaleString(undefined, {
                                maximumFractionDigits: 0,
                              })
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
