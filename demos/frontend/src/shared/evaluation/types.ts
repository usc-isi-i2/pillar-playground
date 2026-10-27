// Shapes returned by the backend's forecast comparison endpoints
// (demos/backend/src/pillar_demos/evaluation.py and api.py).

export interface Observation {
  date: string;
  x: number[];
}

export interface Dataset {
  rows: Observation[];
  stores: string[];
  source: string;
}

export type DatasetKind = 'correlated' | 'independent' | 'shift';
export type Dependence = 'joint' | 'independent';

export interface Rules {
  priority_floor: number;
  base_floor: number;
  emergency: boolean;
}

export interface Fit {
  train: Observation[];
  test: Observation[];
  mean: number[];
  cut: number;
}

export interface Candidate {
  x: number[];
  cost: number;
  prob: number;
}

export type SolveResult =
  { best: null; maxP: number } | { best: Candidate; maxP: number; violation: number; realCost: number };

/** POST /api/evaluation/compare */
export interface Comparison {
  referenceRules: Rules;
  /** The pasted translation, checked; null when none was pasted. */
  rules: Rules | null;
  matchesReference: boolean;
  trainDates: string[];
  testDates: string[];
  rows: { name: string; demand: string; result: SolveResult | null }[];
  /** Mean absolute error of the point forecast on the test dates. */
  mae: number;
  /** Test dates where the distribution plan misses the 90% rule; null when that plan is infeasible. */
  failureDates: string[] | null;
}
