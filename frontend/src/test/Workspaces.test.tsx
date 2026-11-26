import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import type { GovernanceProposal } from '../types/governance';

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  };
}

function textResponse(body: string) {
  return {
    ok: true,
    status: 200,
    text: async () => body,
    json: async () => ({}),
  };
}

describe('Governance interactive workspaces', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('supports JWT role switching, CSV ingest, connectors/jobs, compliance export, and HITL approvals', async () => {
    const user = userEvent.setup();
    const proposalsStore: GovernanceProposal[] = [
      {
        id: 'prop-1',
        domain: 'dedup',
        action_type: 'record_merge',
        title: 'Merge 2 duplicate records (cluster-1)',
        summary: 'Verified match',
        status: 'pending_review',
        risk_level: 'high',
        payload: {
          cluster_id: 'cluster-1',
          record_ids: ['crm-101', 'crm-102'],
          golden_record: { id: 'crm-102' },
        },
        before_snapshot: [{ id: 'crm-101' }, { id: 'crm-102' }],
        after_snapshot: {},
        created_by: 'dedup-agent',
        reviewed_by: null,
        review_notes: null,
        created_at: '2026-11-24T12:00:00Z',
        reviewed_at: null,
        applied_at: null,
        rolled_back_at: null,
      },
    ];

    const jobsStore = [
      {
        id: 'job-1',
        job_type: 'pii_scan',
        status: 'completed',
        execution_mode: 'inline',
        created_by: 'ui-steward',
        params: { text: 'alice@acme.com' },
        result: { total_findings: 1 },
        error_message: null,
        created_at: '2026-11-26T07:00:00Z',
        started_at: '2026-11-26T07:00:00Z',
        completed_at: '2026-11-26T07:00:01Z',
      },
    ];

    const mockFetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input.toString();
      if (url === '/api/v1/health') {
        return jsonResponse({
          status: 'ok',
          service: 'ai-data-governance',
          app_name: 'AI Data Governance & Cleanup Agent',
          version: '0.1.0',
          environment: 'test',
          llm_provider: 'mock',
        });
      }
      if (url === '/api/v1/auth/token') {
        return jsonResponse({
          access_token: 'jwt-steward-token',
          token_type: 'bearer',
          sub: 'ui-steward',
          role: 'steward',
          expires_at: '2026-11-26T20:00:00Z',
        });
      }
      if (url === '/api/v1/pii/vault/stats') {
        return jsonResponse({ total_tokens: 3, by_entity_type: { EMAIL: 2, SSN: 1 } });
      }
      if (url === '/api/v1/pii/scan') {
        return jsonResponse({
          findings: [
            {
              entity_type: 'EMAIL',
              start: 0,
              end: 20,
              confidence: 0.98,
              source: 'regex',
              field_path: null,
              masked_preview: 'el***@northwind.io',
            },
          ],
          total_findings: 1,
          entity_counts: { EMAIL: 1 },
          risk_score: 12.0,
          risk_level: 'low',
        });
      }
      if (url === '/api/v1/pii/mask') {
        return jsonResponse({
          strategy: 'tokenize',
          masked_text: 'Tokenized: TOK_EMAIL_ABC123',
          masked_records: null,
          findings: [
            {
              entity_type: 'EMAIL',
              start: 0,
              end: 20,
              confidence: 0.98,
              source: 'regex',
              field_path: null,
              masked_preview: 'el***@northwind.io',
            },
          ],
          applied_count: 1,
          tokens_created: ['TOK_EMAIL_ABC123'],
          risk_score: 12.0,
          risk_level: 'low',
        });
      }
      if (url === '/api/v1/connectors/ingest/file') {
        return jsonResponse({
          filename: 'sample.csv',
          format: 'csv',
          row_count: 1,
          columns: ['id', 'email'],
          records: [{ id: '99', email: 'csv@acme.com' }],
        });
      }
      if (url === '/api/v1/dedup/analyze') {
        return jsonResponse({
          total_records: 4,
          cluster_count: 1,
          duplicate_record_count: 2,
          ai_summary: 'Deterministic dedup summary ready.',
          llm_provider: 'mock',
          clusters: [
            {
              cluster_id: 'cluster-1',
              record_ids: ['crm-101', 'crm-102'],
              records: [{ id: 'crm-101' }, { id: 'crm-102' }],
              pair_matches: [
                {
                  record_a_id: 'crm-101',
                  record_b_id: 'crm-102',
                  similarity: 0.94,
                  blocking_keys: ['email_domain:acme.com'],
                  field_scores: { email: 1.0, name: 0.9 },
                },
              ],
              average_similarity: 0.94,
              golden_record: { id: 'crm-102', name: 'Doe, Jane', email: 'jane.doe@acme.com' },
              field_provenance: { id: 'crm-102', name: 'crm-102', email: 'crm-101' },
            },
          ],
        });
      }
      if (url === '/api/v1/dedup/propose-merge') {
        return jsonResponse(proposalsStore[0]);
      }
      if (url === '/api/v1/normalizers/preview') {
        return jsonResponse({
          total_records: 3,
          changed_cells: 5,
          invalid_cells: 1,
          changes: [
            {
              record_index: 0,
              record_id: 'row-1',
              field: 'email',
              kind: 'email',
              original: '  ALICE@Acme.COM ',
              normalized: 'alice@acme.com',
              valid: true,
              issue: null,
            },
          ],
          normalized_records: [{ id: 'row-1', email: 'alice@acme.com' }],
        });
      }
      if (url === '/api/v1/schema-audit/analyze') {
        return jsonResponse({
          tables_analyzed: 3,
          health_score: 48.0,
          findings_count: 1,
          findings_by_severity: { high: 1 },
          ai_summary: 'Prioritize missing PK and unindexed FKs.',
          llm_provider: 'mock',
          findings: [
            {
              finding_id: 'finding-1',
              category: 'missing_pk',
              severity: 'high',
              table: 'raw_events_staging',
              column: null,
              title: "Missing primary key on 'raw_events_staging'",
              description: 'No primary key found.',
              recommendation: 'Add identity PK.',
              remediation_sql: 'ALTER TABLE raw_events_staging ADD COLUMN id BIGINT PRIMARY KEY;',
            },
          ],
        });
      }
      if (url === '/api/v1/connectors' && (!init?.method || init.method === 'GET')) {
        return jsonResponse([
          {
            id: 'conn-1',
            name: 'local-warehouse',
            connector_type: 'sqlite',
            dsn_masked: 'sqlite:///./warehouse.db',
            read_only: true,
            description: 'Warehouse DB',
            created_by: 'admin',
            created_at: '2026-11-26T07:00:00Z',
          },
        ]);
      }
      if (url === '/api/v1/connectors/conn-1/audit') {
        return jsonResponse({
          tables_analyzed: 2,
          health_score: 82.0,
          findings_count: 1,
          findings_by_severity: { medium: 1 },
          findings: [],
          ai_summary: 'Live audit complete.',
          llm_provider: 'mock',
        });
      }
      if (url === '/api/v1/jobs' && (!init?.method || init.method === 'GET')) {
        return jsonResponse(jobsStore);
      }
      if (url === '/api/v1/jobs/submit') {
        return jsonResponse(jobsStore[0]);
      }
      if (url.startsWith('/api/v1/reports/compliance?format=markdown')) {
        return textResponse('# AI Data Governance Compliance Report\n- Audit Chain Integrity: VALID');
      }
      if (url.startsWith('/api/v1/governance/proposals') && (!init?.method || init.method === 'GET')) {
        return jsonResponse(proposalsStore);
      }
      if (url === '/api/v1/governance/proposals/prop-1/approve') {
        proposalsStore[0] = {
          ...proposalsStore[0],
          status: 'approved',
          reviewed_by: 'ui-steward',
        };
        return jsonResponse(proposalsStore[0]);
      }
      if (url === '/api/v1/governance/proposals/prop-1/apply') {
        proposalsStore[0] = { ...proposalsStore[0], status: 'applied' };
        return jsonResponse(proposalsStore[0]);
      }
      if (url === '/api/v1/governance/proposals/prop-1/rollback') {
        proposalsStore[0] = { ...proposalsStore[0], status: 'rolled_back' };
        return jsonResponse(proposalsStore[0]);
      }
      if (url.startsWith('/api/v1/governance/audit/verify')) {
        return jsonResponse({
          valid: true,
          checked_count: 4,
          broken_at_sequence: null,
          latest_hash: 'abcdef1234567890',
        });
      }
      if (url.startsWith('/api/v1/governance/audit')) {
        return jsonResponse([
          {
            id: 'ev-1',
            sequence_no: 1,
            domain: 'dedup',
            action: 'proposal.created',
            actor: 'dedup-agent',
            resource_id: 'prop-1',
            details: { title: 'Merge 2 duplicate records' },
            prev_hash: '0'.repeat(64),
            event_hash: 'abcdef1234567890',
            created_at: '2026-11-24T12:00:00Z',
          },
        ]);
      }
      return jsonResponse({});
    });
    vi.stubGlobal('fetch', mockFetch);

    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/API Healthy \(mock\)/i)).toBeInTheDocument();
    });

    // Switch JWT Session Role
    await user.selectOptions(screen.getByLabelText(/Session Role/i), 'steward');
    expect(await screen.findByText(/Switched JWT session to ui-steward/i)).toBeInTheDocument();

    // 1. PII Workspace + CSV upload
    await user.click(screen.getByRole('button', { name: /PII & Vault/i }));
    const fileInput = screen.getByLabelText(/Upload CSV\/JSON/i) as HTMLInputElement;
    const csvFile = new File(['id,email\n99,csv@acme.com\n'], 'sample.csv', { type: 'text/csv' });
    await user.upload(fileInput, csvFile);
    await waitFor(() => {
      expect((screen.getByLabelText(/Structured Records/i) as HTMLTextAreaElement).value).toContain(
        'csv@acme.com',
      );
    });
    await user.click(screen.getByRole('button', { name: /Scan PII/i }));
    expect(await screen.findByText('el***@northwind.io')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Apply Strategy/i }));
    expect(await screen.findByText(/Tokenized: TOK_EMAIL_ABC123/i)).toBeInTheDocument();

    // 2. Dedup Workspace
    await user.click(screen.getByRole('button', { name: /Duplicate Merge/i }));
    await user.click(screen.getByRole('button', { name: /Analyze Duplicates/i }));
    expect(await screen.findByText(/Deterministic dedup summary ready\./i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Propose Merge \(HITL\)/i }));
    expect(await screen.findByText(/Queued merge proposal/i)).toBeInTheDocument();

    // 3. Normalizer Workspace
    await user.click(screen.getByRole('button', { name: /Normalizers/i }));
    await user.click(screen.getByRole('button', { name: /Preview Transforms/i }));
    expect(await screen.findByText('alice@acme.com')).toBeInTheDocument();

    // 4. Schema Audit Workspace
    await user.click(screen.getByRole('button', { name: /Schema Audit/i }));
    await user.click(screen.getByRole('button', { name: /Run Schema Audit/i }));
    expect(await screen.findByText(/48 \/ 100/i)).toBeInTheDocument();

    // 5. Connectors & Jobs Workspace
    await user.click(screen.getByRole('button', { name: /Connectors & Jobs/i }));
    expect(await screen.findByText('local-warehouse')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Run Live Audit/i }));
    expect(await screen.findByText(/Live Schema Audit — Health Score 82\/100/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Submit Job/i }));
    expect(await screen.findByText('ui-steward')).toBeInTheDocument();

    // 6. Governance Approvals, Compliance Export & Audit Chain
    await user.click(screen.getByRole('button', { name: /Approvals & Audit/i }));
    expect(await screen.findByText('Merge 2 duplicate records (cluster-1)')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /^Approve$/i }));
    await user.click(await screen.findByRole('button', { name: /Apply Change/i }));
    await user.click(await screen.findByRole('button', { name: /Rollback/i }));
    expect(await screen.findByText('rolled_back')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Export Markdown/i }));
    expect(await screen.findByText(/# AI Data Governance Compliance Report/i)).toBeInTheDocument();
    expect(screen.getByText(/Hash chain verified across 4 event\(s\)/i)).toBeInTheDocument();
  });
});
