// Shapes returned by the backend's Circuit Copilot endpoints (demos/backend/src/pillar_demos/copilot.py).
//
// Two depots (A, B) ship to four sites (S1–S4), plus an optional local backup at S4. Three joint
// worlds (Normal, Surge, Storm) set S4 demand. A plan is nine quantities: A→S1..S4, B→S1..S4, backup→S4.

export type Scenario = 'demand' | 'storm';
export type Evidence = 'all' | 'Normal' | 'Surge' | 'Storm';

export interface Params {
  scenario: Scenario;
  capacityA: number;
  capacityB: number;
  service: number;
  tau: number;
  floor: number;
  penaltyPriority: number;
  penaltyOther: number;
  backupEnabled: boolean;
  backupLimit: number;
  backupCost: number;
  exceptionAuthorized: boolean;
  exceptionService: number;
  stormProbability: number;
  evidence: Evidence;
}

export interface World {
  id: number;
  name: string;
  demand: number;
  timely: boolean;
}

type NodeBody =
  | { op: 'weight' | 'evidence' | 'policy'; world: number; label: string }
  | { op: 'product' | 'sum'; children: number[]; label: string };
export type CircuitNode = { id: number } & NodeBody;

export interface Circuit {
  version: string;
  signature: Scenario;
  worlds: World[];
  nodes: CircuitNode[];
  numerator: number;
  denominator: number;
}

export interface WorldState extends World {
  p: number;
  delivered: number[];
  requiredS4: number;
  policy: boolean;
}

export interface Score {
  x: number[];
  probability: number;
  transport: number;
  backupCost: number;
  shortage: number;
  total: number;
  usedA: number;
  usedB: number;
  issues: string[];
  feasible: boolean;
  meetsPolicy: boolean;
  states: WorldState[];
}

export type Candidate = Score & { mask: number };

export interface SolveResult {
  best: Candidate | null;
  maxProbability: number;
  hardFeasible: boolean;
  candidates: Candidate[];
  pivots: number;
  subsets: number;
  status: 'feasible' | 'infeasible';
}

/** POST /api/copilot/analyze */
export interface Analysis {
  p: Params;
  circuit: Circuit;
  /** The service level in force. */
  alpha: number;
  worldWeights: number[];
  result: SolveResult;
  mpe: Score | null;
  /** Gate values for the plan the page shows: the decision, else the most-likely-world plan. */
  circuitValues: number[] | null;
  compileMs: number;
  ms: number;
}

/** GET /api/copilot/setup */
export interface Setup {
  base: Params;
  independence: { x: number[]; joint: number; independent: number; failureJoint: number; failureIndependent: number };
}

/** POST /api/copilot/minimum-backup */
export type MinimumBackup = { units: number; plan: Candidate | null } | null;
