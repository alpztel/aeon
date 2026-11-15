import { Activity, Brain, Layers, LayoutGrid, Orbit, Radar, Satellite, Users, type LucideIcon } from "lucide-react";

export type ToolId = "examples" | "diff" | "spectrum" | "classify" | "crossmatch" | "stack" | "orbit" | "candidates";

export interface ToolDef {
  id: ToolId;
  icon: LucideIcon;
  /** Single-key shortcut shown in the rail tooltip (matches the global key handler). */
  key?: string;
}

/** Order follows the discovery workflow: pick a target → see it move → read it → identify it → recover → forecast → share. */
export const TOOLS: ToolDef[] = [
  { id: "examples", icon: LayoutGrid, key: "G" },
  { id: "diff", icon: Layers, key: "D" },
  { id: "spectrum", icon: Activity },
  { id: "classify", icon: Brain },
  { id: "crossmatch", icon: Satellite },
  { id: "stack", icon: Radar, key: "S" },
  { id: "orbit", icon: Orbit, key: "3" },
  { id: "candidates", icon: Users },
];
