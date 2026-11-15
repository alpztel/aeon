import { Activity, Brain, Layers, LayoutGrid, Orbit, Radar, ShieldCheck, type LucideIcon } from "lucide-react";

export type ToolId = "examples" | "diff" | "stack" | "spectrum" | "classify" | "orbit" | "crossmatch";

/** The four steps of the science chain; every tool belongs to one. */
export type ToolStep = 1 | 2 | 3 | 4;

export interface ToolDef {
  id: ToolId;
  icon: LucideIcon;
  step: ToolStep;
  /** Single-key shortcut shown in the rail tooltip (matches the global key handler). */
  key?: string;
}

/**
 * Order follows the chain: 1 pick a target and see it move -> 2 read its spectrum and identity ->
 * 3 age, mass and orbit -> 4 check the result against SIMBAD and the literature.
 */
export const TOOLS: ToolDef[] = [
  { id: "examples", icon: LayoutGrid, step: 1, key: "G" },
  { id: "diff", icon: Layers, step: 1, key: "D" },
  { id: "stack", icon: Radar, step: 1, key: "S" },
  { id: "spectrum", icon: Activity, step: 2 },
  { id: "classify", icon: Brain, step: 2 },
  { id: "orbit", icon: Orbit, step: 3, key: "3" },
  { id: "crossmatch", icon: ShieldCheck, step: 4 },
];
