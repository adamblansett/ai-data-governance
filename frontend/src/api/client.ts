import type {
  AuditChainVerification,
  AuditEvent,
  DedupAnalyzeResponse,
  FieldRule,
  GovernanceProposal,
  HealthStatus,
  MaskStrategy,
  NormalizerPreviewResponse,
  PiiDetokenizeResponse,
  PiiMaskResponse,
  PiiScanResponse,
  PiiVaultStatsResponse,
  SchemaAuditResponse,
  SchemaFinding,
  SurvivorshipRule,
} from '../types/governance';

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
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
    throw new Error(message);
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
