declare module "plotly.js-dist-min" {
  export interface PlotData {
    x?: number[];
    y?: number[];
    type?: string;
    mode?: string;
    name?: string;
    line?: {
      color?: string;
      width?: number;
      dash?: string;
    };
    marker?: {
      color?: string | string[];
      size?: number | number[];
      symbol?: string | string[];
    };
    error_y?: {
      type?: "data";
      array?: number[];
      visible?: boolean;
      color?: string;
      thickness?: number;
      width?: number;
    };
    hovertemplate?: string;
  }

  export interface Shape {
    type: "rect" | "line";
    xref?: "x" | "paper";
    yref?: "y" | "paper";
    x0: number;
    x1: number;
    y0: number;
    y1: number;
    fillcolor?: string;
    line?: {
      width?: number;
      color?: string;
      dash?: string;
    };
  }

  export interface Annotation {
    x: number;
    y: number;
    xref?: "x" | "paper";
    yref?: "y" | "paper";
    text: string;
    showarrow?: boolean;
    bgcolor?: string;
    font?: {
      color?: string;
      size?: number;
    };
  }

  export interface Layout {
    paper_bgcolor?: string;
    plot_bgcolor?: string;
    margin?: { l?: number; r?: number; t?: number; b?: number };
    font?: { color?: string; family?: string; size?: number };
    xaxis?: {
      title?: { text: string };
      gridcolor?: string;
      zerolinecolor?: string;
      range?: [number, number];
    };
    yaxis?: {
      title?: { text: string };
      type?: "linear" | "log";
      gridcolor?: string;
      zerolinecolor?: string;
    };
    legend?: {
      orientation?: "h" | "v";
      x?: number;
      y?: number;
      bgcolor?: string;
    };
    shapes?: Shape[];
    annotations?: Annotation[];
    autosize?: boolean;
  }

  export interface Config {
    responsive?: boolean;
    displayModeBar?: boolean;
    displaylogo?: boolean;
  }

  export function react(
    root: HTMLElement,
    data: PlotData[],
    layout?: Layout,
    config?: Config
  ): Promise<HTMLElement>;

  export function purge(root: HTMLElement): void;
}
