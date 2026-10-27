// Shapes returned by the backend's Replan endpoints (demos/backend/src/pillar_demos/replan.py).
//
// Demand keys are "store|category" (the toy preset has one category, "units").

export type PresetId = 'toy' | 'storm';

export interface PriorityRule {
  stores: string[];
  category: string;
  fraction: number;
}

export interface Spec {
  priority: PriorityRule[];
  floor: { fraction: number } | null;
  exception: { when: 'emergency_declared'; fraction: number } | null;
  crossStateMultiplier: number | null;
  penalties: { priority: number; other: number } | null;
  tau: number | null;
  joint: boolean;
}

export interface Evidence {
  advisory: 'unknown' | 'none' | 'watch' | 'warning';
  sales: 'unknown' | 'flat' | 'up' | 'sharp';
  txCap: number;
  caLane: 'open' | 'closed';
  emergency: 'unknown' | 'declared' | 'not_declared';
  week: 'normal' | 'snap';
}

/** Normal-week demand loaded from a CSV of M5 aggregates, keyed by "store|category". */
export interface CustomDemand {
  base: Record<string, number>;
  cv: Record<string, number>;
}

/** A discrete distribution: [value, probability] pairs. */
export type Atoms = [number, number][];

export interface Dc {
  id: string;
  state: string;
  cap: number;
}

export interface Lane {
  dc: string;
  store: string;
  cost: number;
}

export interface Config {
  w: number;
  label: { z: string; u: string; e: boolean };
  atoms: Record<string, Atoms>;
  /** Priority fraction in force per priority key (the exception lowers it under emergency). */
  frac: Record<string, number>;
}

export interface Model {
  presetId: PresetId;
  spec: Spec;
  ev: Partial<Evidence>;
  stores: string[];
  cats: string[];
  notes: string[];
  sc: string[];
  storeState: Record<string, string>;
  tau: number;
  prio: Record<string, number>;
  pen: Record<string, number>;
  dcs: Dc[];
  lanes: Lane[];
  forecast: Record<string, number>;
  configs: Config[];
  latentNames?: string[];
  marg: Record<string, Atoms>;
}

export interface Shipment {
  dc: string;
  store: string;
  cat: string;
  qty: number;
  cost?: number;
}

export interface Mpe {
  score: number;
  label: Config['label'];
  demand: Record<string, number>;
  frac: Record<string, number>;
  w: number;
}

export interface Relaxation {
  rule: 'floor' | 'priority';
  key: string;
  units: number;
}

export type Plan =
  | {
      status: 'optimal';
      mode: 'mmap' | 'mpe';
      ship: Shipment[];
      q: Record<string, number>;
      threshold: Record<string, number>;
      tauEach: number;
      mpe: Mpe | null;
      relaxed: Relaxation[];
      ms: number;
      iterations: number;
      nVars: number;
      nRows: number;
    }
  | {
      status: 'infeasible' | 'unbounded' | 'iteration_limit';
      mode: 'mmap' | 'mpe';
      ms: number;
      ship?: undefined;
      relaxed?: undefined;
    };

export interface LlmPlan {
  status: 'proposed';
  ship: Shipment[];
  rationale: string;
}

export interface Evaluation {
  q: Record<string, number>;
  used: Record<string, number>;
  transport: number;
  shortPen: number;
  expShortTotal: number;
  expCost: number;
  rules: { key: string; frac: number; q: number; p: number }[];
  pAll: number;
  issues: string[];
  floorShort: { key: string; units: number }[];
  binding: string[];
  perKey: Record<string, number>;
  feasible: boolean;
}

export interface Posterior {
  z: number[];
  u: number[];
  e: number;
}

export interface Diagnosis {
  M: Model;
  posterior: Posterior | null;
  mpe: Mpe;
  attribution: {
    label: string;
    value: string;
    landfallWithout: number;
    landfallWith: number;
    highWithout: number;
    highWith: number;
  }[];
}

export interface World {
  k: Config;
  d: Record<string, number>;
}

export interface MissingParam {
  param: 'tau' | 'penalties';
  q: string;
  opts: [unknown, string][];
}

export interface ReplanResult {
  missing: MissingParam[];
  diag: Diagnosis;
  plans: Partial<Record<'mmap' | 'mpe', Plan>> & { llm?: LlmPlan };
  evals: Partial<Record<'mmap' | 'mpe' | 'llm', Evaluation>>;
  bt: Partial<Record<'mmap' | 'mpe' | 'llm', { rate: number; avgCost: number }>> | null;
  shadow: { step: number; dc: Record<string, number> } | null;
}
/** POST /api/replan/compute */
export interface ComputeResult extends ReplanResult {
  /** Per demand key: mean and 10th/90th percentiles of the demand distribution given the evidence. */
  stats: Record<string, { mean: number; p10: number; p90: number }>;
}

/** POST /api/replan/verify-lane */
export type LaneCheck = {
  lostUnits: number;
  keptP: number;
  replanP: number | null;
  replanCost: number | null;
  replanRelaxed: Relaxation[];
} | null;

export interface ToyPreset {
  id: 'toy';
  title: string;
  dcs: Dc[];
  stores: { id: string; state: string }[];
  cats: string[];
  cost: Record<string, Record<string, number>>;
  forecast: Record<string, number>;
  defaultSpec: Spec;
  knowledge: string;
}

export interface StormPreset {
  id: 'storm';
  title: string;
  states: string[];
  stores: { id: string; state: string; weekly: number }[];
  cats: string[];
  share: Record<string, number>;
  cv: Record<string, number>;
  capFactor: number;
  laneCost: Record<string, Record<string, number>>;
  defaultSpec: Spec;
  knowledge: string;
  Z: string[];
  pZ: number[];
  pAdv: Record<string, number[]>;
  U: string[];
  pU: number[][];
  surge: number[];
  pSales: Record<string, number[]>;
  /** Keyed by String(txCap). */
  pCap: Record<string, number[]>;
  pLaneClosed: number[];
  pEmerg: number[];
}

/** GET /api/replan/setup */
export interface Setup {
  presets: { toy: ToyPreset; storm: StormPreset };
  defaultEvidence: Evidence;
  /** The toy plan at τ = 70% and 90% (slide 20 reports transport 421 and 429). */
  slideCheck: { tau: number; transport: number; s4: number }[];
}
