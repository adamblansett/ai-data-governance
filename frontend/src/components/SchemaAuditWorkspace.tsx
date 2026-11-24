import { useState } from 'react';
import { AlertTriangle, Check, Database, Sparkles } from 'lucide-react';
import { analyzeSchemaAudit, proposeSchemaRemediation } from '../api/client';
import { SAMPLE_SCHEMA_CATALOG, SAMPLE_SCHEMA_DDL } from '../data/samples';
import type { SchemaAuditResponse } from '../types/governance';

interface SchemaAuditWorkspaceProps {
  onProposalCreated: (message: string) => void;
}

export default function SchemaAuditWorkspace({ onProposalCreated }: SchemaAuditWorkspaceProps) {
  const [ddlSql, setDdlSql] = useState(SAMPLE_SCHEMA_DDL);
  const [catalogJson, setCatalogJson] = useState(
    JSON.stringify(SAMPLE_SCHEMA_CATALOG, null, 2),
  );
  const [retentionDays, setRetentionDays] = useState(365);
  const [auditResult, setAuditResult] = useState<SchemaAuditResponse | null>(null);
  const [queuedProposalId, setQueuedProposalId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleRunAudit() {
    setError(null);
    setLoading(true);
    try {
      let tables: Record<string, unknown>[] = [];
      if (catalogJson.trim()) {
        const parsed: unknown = JSON.parse(catalogJson);
        if (!Array.isArray(parsed)) {
          throw new Error('Catalog telemetry JSON must be an array of table objects.');
        }
        tables = parsed as Record<string, unknown>[];
      }
      const res = await analyzeSchemaAudit({
        ddl_sql: ddlSql.trim() ? ddlSql : undefined,
        tables,
        default_retention_days: retentionDays,
      });
      setAuditResult(res);
      setQueuedProposalId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Schema audit failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleProposeRemediation() {
    if (!auditResult || auditResult.findings.length === 0) return;
    setError(null);
    setLoading(true);
    try {
      const proposal = await proposeSchemaRemediation({
        findings: auditResult.findings,
        title: `Schema hygiene remediation (${auditResult.findings_count} findings)`,
      });
      setQueuedProposalId(proposal.id);
      onProposalCreated('Queued PostgreSQL schema remediation plan for HITL approval');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to propose schema remediation');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-slate-900">
              PostgreSQL Schema Hygiene & Retention Auditor
            </h2>
            <p className="text-xs text-slate-600">
              Detect orphaned foreign keys, unindexed FKs, sequential-scan hotspots, missing PKs,
              untagged PII columns, unused indexes, and retention SLA violations.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setDdlSql(SAMPLE_SCHEMA_DDL);
              setCatalogJson(JSON.stringify(SAMPLE_SCHEMA_CATALOG, null, 2));
            }}
            className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            Load Sample
          </button>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div>
            <label htmlFor="schema-ddl" className="block text-xs font-medium text-slate-700">
              PostgreSQL DDL SQL
            </label>
            <textarea
              id="schema-ddl"
              rows={9}
              value={ddlSql}
              onChange={(e) => setDdlSql(e.target.value)}
              className="mt-1.5 w-full rounded-lg border border-slate-300 bg-slate-50 p-3 font-mono text-xs text-slate-900 focus:border-indigo-500 focus:bg-white focus:outline-none"
            />
          </div>
          <div>
            <label htmlFor="schema-catalog" className="block text-xs font-medium text-slate-700">
              Catalog Telemetry JSON (Optional)
            </label>
            <textarea
              id="schema-catalog"
              rows={9}
              value={catalogJson}
              onChange={(e) => setCatalogJson(e.target.value)}
              className="mt-1.5 w-full rounded-lg border border-slate-300 bg-slate-50 p-3 font-mono text-xs text-slate-900 focus:border-indigo-500 focus:bg-white focus:outline-none"
            />
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-4">
          <div>
            <label htmlFor="retention-days" className="block text-xs font-medium text-slate-700">
              Default Retention SLA (days)
            </label>
            <input
              id="retention-days"
              type="number"
              min={1}
              max={36500}
              value={retentionDays}
              onChange={(e) => setRetentionDays(Number(e.target.value) || 365)}
              className="mt-1 w-32 rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-900"
            />
          </div>

          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              disabled={loading}
              onClick={() => void handleRunAudit()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              <Database className="h-3.5 w-3.5" />
              Run Schema Audit
            </button>
            {auditResult && auditResult.findings.length > 0 && (
              <button
                type="button"
                disabled={loading || Boolean(queuedProposalId)}
                onClick={() => void handleProposeRemediation()}
                className={`inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-xs font-semibold ${
                  queuedProposalId
                    ? 'border border-emerald-200 bg-emerald-50 text-emerald-700'
                    : 'bg-emerald-600 text-white hover:bg-emerald-700'
                } disabled:opacity-70`}
              >
                {queuedProposalId ? (
                  <>
                    <Check className="h-3.5 w-3.5" /> Queued ({queuedProposalId.slice(0, 8)})
                  </>
                ) : (
                  'Propose Remediation Plan (HITL)'
                )}
              </button>
            )}
          </div>
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {error}
          </div>
        )}
      </div>

      {auditResult && (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <p className="text-xs text-slate-500">Schema Health Score</p>
              <p
                className={`mt-1 text-2xl font-bold ${
                  auditResult.health_score >= 80
                    ? 'text-emerald-600'
                    : auditResult.health_score >= 50
                    ? 'text-amber-600'
                    : 'text-rose-600'
                }`}
              >
                {auditResult.health_score} / 100
              </p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <p className="text-xs text-slate-500">Tables Analyzed</p>
              <p className="mt-1 text-2xl font-bold text-slate-900">
                {auditResult.tables_analyzed}
              </p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <p className="text-xs text-slate-500">Hygiene Findings</p>
              <p className="mt-1 text-2xl font-bold text-slate-900">{auditResult.findings_count}</p>
            </div>
          </div>

          <div className="flex items-center gap-2 rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-3 text-xs text-indigo-900">
            <Sparkles className="h-4 w-4 shrink-0 text-indigo-600" />
            <span>{auditResult.ai_summary}</span>
          </div>

          <div className="space-y-3">
            {auditResult.findings.map((finding) => (
              <div
                key={finding.finding_id}
                className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <AlertTriangle
                      className={`h-4 w-4 ${
                        finding.severity === 'critical' || finding.severity === 'high'
                          ? 'text-rose-600'
                          : 'text-amber-600'
                      }`}
                    />
                    <h3 className="text-sm font-semibold text-slate-900">{finding.title}</h3>
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-slate-700">
                      {finding.table}
                      {finding.column ? `.${finding.column}` : ''}
                    </span>
                    <span
                      className={`rounded-full px-2.5 py-0.5 font-semibold uppercase ${
                        finding.severity === 'critical'
                          ? 'bg-rose-100 text-rose-800'
                          : finding.severity === 'high'
                          ? 'bg-orange-100 text-orange-800'
                          : finding.severity === 'medium'
                          ? 'bg-amber-100 text-amber-800'
                          : 'bg-slate-100 text-slate-700'
                      }`}
                    >
                      {finding.severity}
                    </span>
                  </div>
                </div>
                <p className="mt-1.5 text-xs text-slate-600">{finding.description}</p>
                <p className="mt-1 text-xs font-medium text-slate-800">
                  Recommendation: {finding.recommendation}
                </p>
                {finding.remediation_sql && (
                  <pre className="mt-2 overflow-x-auto rounded-lg border border-slate-200 bg-slate-900 p-3 font-mono text-xs text-slate-100">
                    {finding.remediation_sql}
                  </pre>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
