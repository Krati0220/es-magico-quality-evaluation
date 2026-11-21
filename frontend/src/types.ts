export interface ProviderSide {
  base_url: string | null;
  model: string | null;
  has_api_key: boolean;
}

export interface ProviderStatus {
  configured: boolean;
  generate: ProviderSide;
  judge: ProviderSide;
  same_model_and_endpoint: boolean;
  default_rate_limit_delay: number;
}

export interface HealthResponse {
  status: string;
  database: string;
  auth_required: boolean;
  provider: ProviderStatus;
}

export interface GoldenCase {
  id: string;
  channel: string;
  conversation: string;
  selection_reason: string;
  tags: string[];
  must_include: string[];
  must_not_include: string[];
  ambiguities: string[];
  final_status: string | null;
  actions_taken: string | null;
  next_action: string | null;
  owner: string | null;
  sensitive_spans?: { type: string; value: string }[];
}

export interface UnselectedCase {
  id: string;
  channel: string;
  conversation: string;
}

export interface CheckRuleResult {
  rule_id: string;
  passed: boolean;
  observed: unknown;
  expected: unknown;
  severity: string;
}

export interface CheckResult {
  passed: boolean;
  critical_failure: boolean;
  rules: CheckRuleResult[];
}

export interface Judgment {
  faithfulness: number;
  completeness: number;
  usefulness: number;
  critical_errors: {
    kind: string;
    explanation: string;
    source_evidence: string;
    summary_evidence: string;
  }[];
  reasons: {
    faithfulness: string;
    completeness: string;
    usefulness: string;
  };
  evidence: { source: string; summary: string }[];
}

export interface OverviewResponse {
  spec: string;
  config: {
    case_count: number;
    repeats: number;
    temperature: number;
    judge_temperature: number;
    checks: Record<string, unknown>;
    rubric: { faithfulness_min: number; completeness_min: number; usefulness_min: number };
    release: Record<string, number>;
    judge_policy: string;
  };
  prompts: Record<string, string>;
  judge_prompt: string;
  static_audit: {
    recommendation: string;
    findings: { kind: string; version: string; product_spec: string; prompt_lines: string[]; conclusion: string }[];
    notes: string[];
  } | null;
  coverage: {
    selected_ids: string[];
    channels: Record<string, number>;
    tag_counts: Record<string, number>;
    unselected_ids: string[];
  } | null;
  golden_cases: GoldenCase[];
  unselected_cases: UnselectedCase[];
  provider: ProviderStatus;
}

export interface PlaygroundOutput {
  version: string;
  summary?: string;
  word_count?: number;
  checks?: CheckResult;
  judgment?: Judgment | null;
  semantic_pass?: boolean | null;
  combined_pass?: boolean | null;
  judge_error?: string | null;
  error?: string;
  error_detail?: string | null;
  latency_seconds: number;
  judge_latency_seconds?: number | null;
  usage?: Record<string, number> | null;
  cost_usd?: number | null;
  judge_cost_usd?: number | null;
  model?: string;
}

export interface PlaygroundResponse {
  case_id: string | null;
  conversation: string;
  use_mock: boolean;
  models: Record<string, { base_url: string; model: string }>;
  outputs: PlaygroundOutput[];
}

export interface VersionStats {
  planned: number;
  generated: number;
  judged: number;
  deterministic_passes: number;
  semantic_passes: number;
  combined_passes: number;
  combined_rate_over_planned: number | null;
  critical_outputs: number;
  deterministic_critical_outputs: number;
  mean_scores: {
    faithfulness: number | null;
    completeness: number | null;
    usefulness: number | null;
  };
}

export interface AgreementMetrics {
  n: number;
  confusion_matrix: {
    both_pass: number;
    both_fail: number;
    false_pass: number;
    false_fail: number;
  };
  exact_agreement: number | null;
  kappa: number | null;
  critical_errors_missed?: number;
  mean_absolute_error?: Record<string, number | null>;
}

export interface RunSummary {
  id: string;
  name: string;
  scope: string;
  baseline_version: string;
  candidate_version: string;
  status: string;
  use_mock: boolean;
  is_active: boolean;
  completed_steps: number;
  total_steps: number;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
  recommendation: string | null;
  cost_usd: number | null;
  versions: Record<string, VersionStats> | null;
  human_status: string | null;
  models: Record<string, { base_url: string; model: string }> | null;
}

export interface RunDetail extends RunSummary {
  metrics: {
    baseline_version: string;
    candidate_version: string;
    versions: Record<string, VersionStats>;
    paired_comparison: {
      paired_cases: number;
      mean_v2_minus_v1: number;
      ci95_low: number;
      ci95_high: number;
      method: string;
      iterations: number;
      seed: number;
    } | null;
    per_case: {
      case_id: string;
      tags: string[];
      rates: Record<string, number>;
      delta: number;
      variable_across_repeats: Record<string, boolean>;
    }[];
    risk_slices: Record<string, Record<string, { n: number; combined_passes: number }>>;
    human: {
      status: string;
      calibration: AgreementMetrics;
      validation: AgreementMetrics;
      disagreements: unknown[];
      completed_labels?: { calibration: number; validation: number };
    };
    operational_error_attempts: number;
    request_attempts: number;
    reported_usage_all_attempts: Record<string, number>;
    cost_usd: number | null;
    recommendation: string;
    decision_reasons: string[];
    same_model_and_endpoint: boolean;
  } | null;
  rows: {
    case_id: string;
    version: string;
    repeat: number;
    job_id: string;
    summary: string | null;
    checks: CheckResult | null;
    judgment: Judgment | null;
    semantic_pass: boolean | null;
    combined_pass: boolean | null;
  }[];
  report_md: string | null;
  has_review: boolean;
  recent_errors: {
    job_id: string;
    case_id: string;
    version: string;
    stage: string;
    attempt: number;
    error_code: string | null;
    error_detail: string | null;
    finished_at: string | null;
  }[];
}

export interface HumanLabel {
  human_attestation: boolean;
  reviewed_by: string;
  reviewed_at: string;
  faithfulness: number;
  completeness: number;
  usefulness: number;
  critical_errors: string[];
  notes: string;
}

export interface ReviewItem {
  review_id: string;
  review_phase: 'calibration' | 'validation';
  conversation: string;
  expectations: {
    must_include: string[];
    must_not_include: string[];
    ambiguities: string[];
    final_status: string | null;
    next_action: string | null;
    owner: string | null;
  };
  summary: string;
  label: HumanLabel | null;
}

export interface ReviewResponse {
  available: boolean;
  reason?: string;
  instructions?: string;
  rubric?: string;
  product_spec?: string;
  gap_policies?: string;
  progress?: {
    calibration_done: number;
    calibration_total: number;
    validation_done: number;
    validation_total: number;
  };
  human_metrics?: RunDetail['metrics'] extends infer M
    ? M extends { human: infer H }
      ? H
      : never
    : never;
  items: ReviewItem[];
}
