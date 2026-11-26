import type {
  AuditChainVerification,
  AuditEvent,
  AuthTokenResponse,
  BackgroundJob,
  ComplianceReport,
  ConnectorSampleResponse,
  ConnectorTableMeta,
  ConnectorTestResponse,
  ConnectorType,
  DataConnector,
  DedupAnalyzeResponse,
  FieldRule,
  FileIngestResponse,
  GovernanceProposal,
  HealthStatus,
  JobMode,
  JobType,
  MaskStrategy,
  NormalizerPreviewResponse,
  PiiDetokenizeResponse,
  PiiMaskResponse,
  PiiScanResponse,
  PiiVaultStatsResponse,
  Role,
  SchemaAuditResponse,
  SchemaFinding,
  SurvivorshipRule,
  WhoAmIResponse,
} from '../types/governance';

let activeAuthToken: string | null = null;

export function setAuthToken(token: string | null): void {
  activeAuthToken = token;
}

export function getAuthToken(): string | null {
  return activeAuthToken;
}

function authHeaders(): Record<string, string> {
  return activeAuthToken ? { Authorization: `Bearer ${activeAuthToken}` } : {};
}

async function parseErrorMessage(response: Response): Promise<string> {
  let message = `Request failed (${response.status})`;
  try {
    const errBody = (await response.json()) as { detail?: unknown };
    if (typeof errBody.detail === 'string') {
      message = errBody.detail;
    } else if (Array.isArray(errBody.detail) && errBody.detail.length > 0) {
      message = JSON.stringify(errBody.detail);
    }
  } catch {
    // Ignore parse failures on non-JSON error responses.
  }
  return message;
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new Error(await parseErrorMessage(response));
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function fetchHealth(): Promise<HealthStatus> {
  const response = await fetch('/api/v1/health');
  if (!response.ok) {
    throw new Error(`Health check failed (${response.status})`);
  }
  return (await response.json()) as HealthStatus;
}

export function issueAuthToken(payload: {
  username: string;
  role: Role;
  api_key?: string;
}): Promise<AuthTokenResponse> {
  return requestJson<AuthTokenResponse>('/api/v1/auth/token', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function fetchWhoAmI(): Promise<WhoAmIResponse> {
  return requestJson<WhoAmIResponse>('/api/v1/auth/me');
}

export function scanPii(payload: {
  text?: string;
  records?: Record<string, unknown>[];
  policy_name?: string;
  include_ner?: boolean;
}): Promise<PiiScanResponse> {
  return requestJson<PiiScanResponse>('/api/v1/pii/scan', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function maskPii(payload: {
  text?: string;
  records?: Record<string, unknown>[];
  strategy: MaskStrategy;
  policy_name?: string;
  include_ner?: boolean;
}): Promise<PiiMaskResponse> {
  return requestJson<PiiMaskResponse>('/api/v1/pii/mask', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function detokenizePii(payload: {
  tokens: string[];
  actor: string;
  reason: string;
}): Promise<PiiDetokenizeResponse> {
  return requestJson<PiiDetokenizeResponse>('/api/v1/pii/detokenize', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function fetchVaultStats(): Promise<PiiVaultStatsResponse> {
  return requestJson<PiiVaultStatsResponse>('/api/v1/pii/vault/stats');
}

export function analyzeDedup(payload: {
  records: Record<string, unknown>[];
  threshold: number;
  survivorship: SurvivorshipRule;
}): Promise<DedupAnalyzeResponse> {
  return requestJson<DedupAnalyzeResponse>('/api/v1/dedup/analyze', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function proposeDedupMerge(payload: {
  cluster_id: string;
  source_records: Record<string, unknown>[];
  golden_record: Record<string, unknown>;
  rationale: string;
}): Promise<GovernanceProposal> {
  return requestJson<GovernanceProposal>('/api/v1/dedup/propose-merge', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function previewNormalizers(payload: {
  records: Record<string, unknown>[];
  rules: FieldRule[];
}): Promise<NormalizerPreviewResponse> {
  return requestJson<NormalizerPreviewResponse>('/api/v1/normalizers/preview', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function proposeNormalizers(payload: {
  records: Record<string, unknown>[];
  rules: FieldRule[];
  title: string;
}): Promise<GovernanceProposal> {
  return requestJson<GovernanceProposal>('/api/v1/normalizers/propose', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function analyzeSchemaAudit(payload: {
  ddl_sql?: string;
  tables?: Record<string, unknown>[];
  default_retention_days?: number;
}): Promise<SchemaAuditResponse> {
  return requestJson<SchemaAuditResponse>('/api/v1/schema-audit/analyze', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function proposeSchemaRemediation(payload: {
  findings: SchemaFinding[];
  title: string;
}): Promise<GovernanceProposal> {
  return requestJson<GovernanceProposal>('/api/v1/schema-audit/propose-remediation', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function fetchProposals(status?: string): Promise<GovernanceProposal[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : '';
  return requestJson<GovernanceProposal[]>(`/api/v1/governance/proposals${qs}`);
}

export function approveProposal(
  proposalId: string,
  reviewer: string,
  notes: string,
): Promise<GovernanceProposal> {
  return requestJson<GovernanceProposal>(`/api/v1/governance/proposals/${proposalId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ reviewer, notes }),
  });
}

export function rejectProposal(
  proposalId: string,
  reviewer: string,
  notes: string,
): Promise<GovernanceProposal> {
  return requestJson<GovernanceProposal>(`/api/v1/governance/proposals/${proposalId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reviewer, notes }),
  });
}

export function applyProposal(proposalId: string, actor: string): Promise<GovernanceProposal> {
  return requestJson<GovernanceProposal>(`/api/v1/governance/proposals/${proposalId}/apply`, {
    method: 'POST',
    body: JSON.stringify({ actor }),
  });
}

export function rollbackProposal(
  proposalId: string,
  actor: string,
  reason: string,
): Promise<GovernanceProposal> {
  return requestJson<GovernanceProposal>(`/api/v1/governance/proposals/${proposalId}/rollback`, {
    method: 'POST',
    body: JSON.stringify({ actor, reason }),
  });
}

export function fetchAuditEvents(limit = 50): Promise<AuditEvent[]> {
  return requestJson<AuditEvent[]>(`/api/v1/governance/audit?limit=${limit}`);
}

export function verifyAuditChain(): Promise<AuditChainVerification> {
  return requestJson<AuditChainVerification>('/api/v1/governance/audit/verify');
}

export function fetchConnectors(): Promise<DataConnector[]> {
  return requestJson<DataConnector[]>('/api/v1/connectors');
}

export function createConnector(payload: {
  name: string;
  connector_type: ConnectorType;
  dsn: string;
  read_only: boolean;
  description: string;
}): Promise<DataConnector> {
  return requestJson<DataConnector>('/api/v1/connectors', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function deleteConnector(connectorId: string): Promise<void> {
  return requestJson<void>(`/api/v1/connectors/${connectorId}`, {
    method: 'DELETE',
  });
}

export function testConnector(connectorId: string): Promise<ConnectorTestResponse> {
  return requestJson<ConnectorTestResponse>(`/api/v1/connectors/${connectorId}/test`, {
    method: 'POST',
  });
}

export function introspectConnectorTables(connectorId: string): Promise<ConnectorTableMeta[]> {
  return requestJson<ConnectorTableMeta[]>(`/api/v1/connectors/${connectorId}/tables`);
}

export function sampleConnectorTable(
  connectorId: string,
  tableName: string,
  limit = 25,
): Promise<ConnectorSampleResponse> {
  return requestJson<ConnectorSampleResponse>(
    `/api/v1/connectors/${connectorId}/tables/${encodeURIComponent(tableName)}/sample?limit=${limit}`,
  );
}

export function auditConnector(connectorId: string): Promise<SchemaAuditResponse> {
  return requestJson<SchemaAuditResponse>(`/api/v1/connectors/${connectorId}/audit`, {
    method: 'POST',
    body: JSON.stringify({ default_retention_days: 365 }),
  });
}

export function scanConnectorTablePii(
  connectorId: string,
  tableName: string,
): Promise<PiiScanResponse> {
  return requestJson<PiiScanResponse>(
    `/api/v1/connectors/${connectorId}/tables/${encodeURIComponent(tableName)}/pii-scan`,
    {
      method: 'POST',
      body: JSON.stringify({ limit: 100, include_ner: true }),
    },
  );
}

export async function uploadIngestFile(file: File): Promise<FileIngestResponse> {
  const form = new FormData();
  form.append('file', file);
  const response = await fetch('/api/v1/connectors/ingest/file', {
    method: 'POST',
    headers: {
      ...authHeaders(),
    },
    body: form,
  });
  if (!response.ok) {
    throw new Error(await parseErrorMessage(response));
  }
  return (await response.json()) as FileIngestResponse;
}

export function submitJob(payload: {
  job_type: JobType;
  execution_mode: JobMode;
  params: Record<string, unknown>;
}): Promise<BackgroundJob> {
  return requestJson<BackgroundJob>('/api/v1/jobs/submit', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function fetchJobs(): Promise<BackgroundJob[]> {
  return requestJson<BackgroundJob[]>('/api/v1/jobs');
}

export function fetchComplianceReport(): Promise<ComplianceReport> {
  return requestJson<ComplianceReport>('/api/v1/reports/compliance?format=json');
}

export async function downloadComplianceReport(format: 'markdown' | 'csv'): Promise<string> {
  const response = await fetch(`/api/v1/reports/compliance?format=${format}`, {
    headers: {
      ...authHeaders(),
    },
  });
  if (!response.ok) {
    throw new Error(await parseErrorMessage(response));
  }
  return await response.text();
}
