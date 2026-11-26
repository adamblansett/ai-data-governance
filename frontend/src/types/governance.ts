export type WorkspaceTab =
  | 'overview'
  | 'pii'
  | 'dedup'
  | 'normalizers'
  | 'schema_audit'
  | 'connectors'
  | 'governance';

export type Role = 'viewer' | 'analyst' | 'steward' | 'admin';

export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
  sub: string;
  role: Role;
  expires_at: string;
}

export interface WhoAmIResponse {
  sub: string;
  role: Role;
  auth_method: string;
  auth_required: boolean;
  permissions: string[];
}

export interface HealthStatus {
  status: string;
  service: string;
  app_name: string;
  version: string;
  environment: string;
  llm_provider: string;
}

export type MaskStrategy = 'mask' | 'redact' | 'hash' | 'tokenize';

export interface PiiEntityMatch {
  entity_type: string;
  start: number;
  end: number;
  confidence: number;
  source: 'regex' | 'heuristic_ner';
  field_path: string | null;
  masked_preview: string;
}

export interface PiiScanResponse {
  findings: PiiEntityMatch[];
  total_findings: number;
  entity_counts: Record<string, number>;
  risk_score: number;
  risk_level: 'low' | 'medium' | 'high';
}

export interface PiiMaskResponse {
  strategy: MaskStrategy;
  masked_text: string | null;
  masked_records: Record<string, unknown>[] | null;
  findings: PiiEntityMatch[];
  applied_count: number;
  tokens_created: string[];
  risk_score: number;
  risk_level: 'low' | 'medium' | 'high';
}

export interface PiiDetokenizeResponse {
  resolved: Record<string, string>;
  missing_tokens: string[];
}

export interface PiiVaultStatsResponse {
  total_tokens: number;
  by_entity_type: Record<string, number>;
}

export type SurvivorshipRule =
  | 'most_complete'
  | 'most_recent'
  | 'longest'
  | 'prefer_first'
  | 'prefer_non_null';

export interface PairMatch {
  record_a_id: string;
  record_b_id: string;
  similarity: number;
  blocking_keys: string[];
  field_scores: Record<string, number>;
}

export interface DuplicateCluster {
  cluster_id: string;
  record_ids: string[];
  records: Record<string, unknown>[];
  pair_matches: PairMatch[];
  average_similarity: number;
  golden_record: Record<string, unknown>;
  field_provenance: Record<string, string>;
}

export interface DedupAnalyzeResponse {
  total_records: number;
  cluster_count: number;
  duplicate_record_count: number;
  clusters: DuplicateCluster[];
  ai_summary: string;
  llm_provider: string;
}

export type NormalizerKind =
  | 'email'
  | 'phone'
  | 'address'
  | 'taxonomy'
  | 'nulls'
  | 'whitespace'
  | 'date_iso';

export interface FieldRule {
  field: string;
  kind: NormalizerKind;
  default_country_code?: string;
  taxonomy_map?: Record<string, string> | null;
}

export interface CellChange {
  record_index: number;
  record_id: string;
  field: string;
  kind: NormalizerKind;
  original: unknown;
  normalized: unknown;
  valid: boolean;
  issue: string | null;
}

export interface NormalizerPreviewResponse {
  total_records: number;
  changed_cells: number;
  invalid_cells: number;
  changes: CellChange[];
  normalized_records: Record<string, unknown>[];
}

export type FindingSeverity = 'low' | 'medium' | 'high' | 'critical';

export interface SchemaFinding {
  finding_id: string;
  category: string;
  severity: FindingSeverity;
  table: string;
  column: string | null;
  title: string;
  description: string;
  recommendation: string;
  remediation_sql: string;
}

export interface SchemaAuditResponse {
  tables_analyzed: number;
  health_score: number;
  findings_count: number;
  findings_by_severity: Record<string, number>;
  findings: SchemaFinding[];
  ai_summary: string;
  llm_provider: string;
}

export interface GovernanceProposal {
  id: string;
  domain: string;
  action_type: string;
  title: string;
  summary: string;
  status: 'pending_review' | 'approved' | 'rejected' | 'applied' | 'rolled_back' | string;
  risk_level: 'low' | 'medium' | 'high' | string;
  payload: Record<string, unknown>;
  before_snapshot: unknown;
  after_snapshot: unknown;
  created_by: string;
  reviewed_by: string | null;
  review_notes: string | null;
  created_at: string;
  reviewed_at: string | null;
  applied_at: string | null;
  rolled_back_at: string | null;
}

export interface AuditEvent {
  id: string;
  sequence_no: number;
  domain: string;
  action: string;
  actor: string;
  resource_id: string | null;
  details: Record<string, unknown>;
  prev_hash: string;
  event_hash: string;
  created_at: string;
}

export interface AuditChainVerification {
  valid: boolean;
  checked_count: number;
  broken_at_sequence: number | null;
  latest_hash: string | null;
}

export type ConnectorType = 'sqlite' | 'postgresql';

export interface DataConnector {
  id: string;
  name: string;
  connector_type: string;
  dsn_masked: string;
  read_only: boolean;
  description: string;
  created_by: string;
  created_at: string;
}

export interface ConnectorTestResponse {
  connector_id: string;
  name: string;
  connector_type: string;
  ok: boolean;
  dialect: string;
  latency_ms: number;
  table_count: number;
  error: string | null;
}

export interface ConnectorTableMeta {
  name: string;
  row_count: number;
  columns: { name: string; data_type: string; is_primary_key: boolean }[];
  foreign_keys: { column: string; ref_table: string; ref_column: string; orphan_count: number }[];
  indexes: { name: string; columns: string[]; unique: boolean }[];
}

export interface ConnectorSampleResponse {
  connector_id: string;
  table_name: string;
  row_count_sampled: number;
  columns: string[];
  rows: Record<string, unknown>[];
}

export interface FileIngestResponse {
  filename: string;
  format: 'csv' | 'json';
  row_count: number;
  columns: string[];
  records: Record<string, unknown>[];
}

export type JobType = 'pii_scan' | 'schema_audit' | 'dedup_analyze' | 'normalizer_preview';
export type JobMode = 'inline' | 'background';

export interface BackgroundJob {
  id: string;
  job_type: string;
  status: string;
  execution_mode: string;
  created_by: string;
  params: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface ComplianceReport {
  generated_at: string;
  vault_total_tokens: number;
  vault_by_entity_type: Record<string, number>;
  proposals_total: number;
  proposals_by_status: Record<string, number>;
  proposals_by_domain: Record<string, number>;
  connectors_total: number;
  jobs_total: number;
  jobs_by_status: Record<string, number>;
  audit_chain: AuditChainVerification;
  recent_audit_events: AuditEvent[];
}
