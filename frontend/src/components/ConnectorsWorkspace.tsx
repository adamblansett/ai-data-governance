import { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  Database,
  Play,
  Plus,
  RefreshCw,
  ScanSearch,
  Table2,
  Trash2,
} from 'lucide-react';
import {
  auditConnector,
  createConnector,
  deleteConnector,
  fetchConnectors,
  fetchJobs,
  introspectConnectorTables,
  sampleConnectorTable,
  scanConnectorTablePii,
  submitJob,
  testConnector,
} from '../api/client';
import type {
  BackgroundJob,
  ConnectorSampleResponse,
  ConnectorTableMeta,
  ConnectorTestResponse,
  ConnectorType,
  DataConnector,
  JobMode,
  JobType,
  PiiScanResponse,
  SchemaAuditResponse,
} from '../types/governance';

export default function ConnectorsWorkspace() {
  const [connectors, setConnectors] = useState<DataConnector[]>([]);
  const [jobs, setJobs] = useState<BackgroundJob[]>([]);
  const [name, setName] = useState('local-warehouse');
  const [connectorType, setConnectorType] = useState<ConnectorType>('sqlite');
  const [dsn, setDsn] = useState('sqlite:///./warehouse_sample.db');
  const [readOnly, setReadOnly] = useState(true);
  const [description, setDescription] = useState('Target database connector');

  const [selectedConnectorId, setSelectedConnectorId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<ConnectorTestResponse | null>(null);
  const [tables, setTables] = useState<ConnectorTableMeta[]>([]);
  const [sample, setSample] = useState<ConnectorSampleResponse | null>(null);
  const [liveAudit, setLiveAudit] = useState<SchemaAuditResponse | null>(null);
  const [livePiiScan, setLivePiiScan] = useState<PiiScanResponse | null>(null);

  const [jobType, setJobType] = useState<JobType>('pii_scan');
  const [jobMode, setJobMode] = useState<JobMode>('inline');
  const [jobParamsJson, setJobParamsJson] = useState(
    JSON.stringify({ text: 'Contact alice@acme.com or SSN 123-45-6789' }, null, 2),
  );

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setError(null);
    try {
      const [connList, jobList] = await Promise.all([fetchConnectors(), fetchJobs()]);
      setConnectors(Array.isArray(connList) ? connList : []);
      setJobs(Array.isArray(jobList) ? jobList : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load connectors and jobs');
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  async function handleCreateConnector() {
    setError(null);
    setLoading(true);
    try {
      const created = await createConnector({
        name,
        connector_type: connectorType,
        dsn,
        read_only: readOnly,
        description,
      });
      setSelectedConnectorId(created.id);
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to register connector');
    } finally {
      setLoading(false);
    }
  }

  async function handleTest(id: string) {
    setError(null);
    setLoading(true);
    try {
      setSelectedConnectorId(id);
      setTestResult(await testConnector(id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Connection test failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleIntrospect(id: string) {
    setError(null);
    setLoading(true);
    try {
      setSelectedConnectorId(id);
      setTables(await introspectConnectorTables(id));
      setSample(null);
      setLivePiiScan(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Introspection failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleLiveAudit(id: string) {
    setError(null);
    setLoading(true);
    try {
      setSelectedConnectorId(id);
      setLiveAudit(await auditConnector(id));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Live schema audit failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleSampleAndScan(id: string, tableName: string) {
    setError(null);
    setLoading(true);
    try {
      const [sampleRes, piiRes] = await Promise.all([
        sampleConnectorTable(id, tableName, 25),
        scanConnectorTablePii(id, tableName),
      ]);
      setSample(sampleRes);
      setLivePiiScan(piiRes);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Table sampling failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete(id: string) {
    setError(null);
    setLoading(true);
    try {
      await deleteConnector(id);
      if (selectedConnectorId === id) {
        setSelectedConnectorId(null);
        setTables([]);
        setSample(null);
      }
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete connector');
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmitJob() {
    setError(null);
    setLoading(true);
    try {
      const parsed: unknown = JSON.parse(jobParamsJson);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('Job params must be a JSON object.');
      }
      await submitJob({
        job_type: jobType,
        execution_mode: jobMode,
        params: parsed as Record<string, unknown>,
      });
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to submit job');
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
              Live Database Connectors (Encrypted DSN Vault)
            </h2>
            <p className="text-xs text-slate-600">
              Register PostgreSQL or SQLite targets, run live schema introspection & orphan-FK
              checks, sample tables for PII, and execute approved HITL proposals transactionally.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void loadAll()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label htmlFor="conn-name" className="block text-xs font-medium text-slate-700">
              Connector Name
            </label>
            <input
              id="conn-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
            />
          </div>
          <div>
            <label htmlFor="conn-type" className="block text-xs font-medium text-slate-700">
              Dialect
            </label>
            <select
              id="conn-type"
              value={connectorType}
              onChange={(e) => setConnectorType(e.target.value as ConnectorType)}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs"
            >
              <option value="sqlite">SQLite</option>
              <option value="postgresql">PostgreSQL</option>
            </select>
          </div>
          <div className="sm:col-span-2">
            <label htmlFor="conn-dsn" className="block text-xs font-medium text-slate-700">
              Database DSN (Encrypted at Rest)
            </label>
            <input
              id="conn-dsn"
              type="text"
              value={dsn}
              onChange={(e) => setDsn(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 font-mono text-xs"
            />
          </div>
          <div className="sm:col-span-2">
            <label htmlFor="conn-desc" className="block text-xs font-medium text-slate-700">
              Description
            </label>
            <input
              id="conn-desc"
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
            />
          </div>
          <label className="flex items-center gap-2 pt-4 text-xs text-slate-700">
            <input
              type="checkbox"
              checked={readOnly}
              onChange={(e) => setReadOnly(e.target.checked)}
              className="rounded border-slate-300 text-indigo-600"
            />
            Read-Only Guardrail
          </label>
          <div className="flex items-end justify-end">
            <button
              type="button"
              disabled={loading}
              onClick={() => void handleCreateConnector()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              <Plus className="h-3.5 w-3.5" /> Register Connector
            </button>
          </div>
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {error}
          </div>
        )}

        <div className="mt-4 space-y-2">
          {connectors.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-200 p-4 text-center text-xs text-slate-500">
              No connectors registered yet. Admin role required to register or delete connectors.
            </p>
          ) : (
            connectors.map((c) => (
              <div
                key={c.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50/70 p-3.5"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <Database className="h-4 w-4 text-indigo-600" />
                    <span className="text-sm font-semibold text-slate-900">{c.name}</span>
                    <span className="rounded bg-slate-200 px-2 py-0.5 text-[11px] font-medium text-slate-700">
                      {c.connector_type}
                    </span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                        c.read_only
                          ? 'bg-amber-100 text-amber-800'
                          : 'bg-emerald-100 text-emerald-800'
                      }`}
                    >
                      {c.read_only ? 'read-only' : 'writable'}
                    </span>
                  </div>
                  <p className="mt-1 font-mono text-[11px] text-slate-500">{c.dsn_masked}</p>
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => void handleTest(c.id)}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                  >
                    <Activity className="h-3.5 w-3.5" /> Test
                  </button>
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => void handleIntrospect(c.id)}
                    className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                  >
                    <Table2 className="h-3.5 w-3.5" /> Introspect
                  </button>
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => void handleLiveAudit(c.id)}
                    className="inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700"
                  >
                    Run Live Audit
                  </button>
                  <button
                    type="button"
                    disabled={loading}
                    onClick={() => void handleDelete(c.id)}
                    aria-label={`Delete ${c.name}`}
                    className="rounded-lg border border-rose-200 bg-rose-50 p-1.5 text-rose-700 hover:bg-rose-100"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        {testResult && (
          <div
            className={`mt-3 rounded-lg border px-3 py-2 text-xs ${
              testResult.ok
                ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                : 'border-rose-200 bg-rose-50 text-rose-800'
            }`}
          >
            {testResult.ok
              ? `Connected to ${testResult.name} (${testResult.dialect}) in ${testResult.latency_ms}ms — ${testResult.table_count} table(s).`
              : `Connection failed: ${testResult.error ?? 'Unknown error'}`}
          </div>
        )}
      </div>

      {tables.length > 0 && selectedConnectorId && (
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-900">
            Introspected Tables ({tables.length})
          </h3>
          <div className="mt-3 space-y-2">
            {tables.map((t) => (
              <div
                key={t.name}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs"
              >
                <div>
                  <span className="font-mono font-semibold text-slate-900">{t.name}</span>
                  <span className="ml-2 text-slate-500">
                    {t.row_count} rows · {t.columns.length} cols · {t.foreign_keys.length} FKs
                  </span>
                </div>
                <button
                  type="button"
                  disabled={loading}
                  onClick={() => void handleSampleAndScan(selectedConnectorId, t.name)}
                  className="inline-flex items-center gap-1 rounded-lg border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700 hover:bg-indigo-100"
                >
                  <ScanSearch className="h-3.5 w-3.5" /> Sample & Scan PII
                </button>
              </div>
            ))}
          </div>
          {sample && (
            <div className="mt-3 grid gap-3 lg:grid-cols-2">
              <pre className="max-h-48 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-[11px]">
                {JSON.stringify(sample.rows, null, 2)}
              </pre>
              {livePiiScan && (
                <pre className="max-h-48 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-[11px]">
                  {JSON.stringify(livePiiScan, null, 2)}
                </pre>
              )}
            </div>
          )}
        </div>
      )}

      {liveAudit && (
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-900">
            Live Schema Audit — Health Score {liveAudit.health_score}/100 ({liveAudit.findings_count}{' '}
            findings)
          </h3>
          <p className="mt-1 text-xs text-slate-600">{liveAudit.ai_summary}</p>
        </div>
      )}

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-900">
          Governance Jobs Runner (Inline & Async Background)
        </h3>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <div>
            <label htmlFor="job-type" className="block text-xs font-medium text-slate-700">
              Job Type
            </label>
            <select
              id="job-type"
              value={jobType}
              onChange={(e) => setJobType(e.target.value as JobType)}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs"
            >
              <option value="pii_scan">PII Scan</option>
              <option value="schema_audit">Schema Audit</option>
              <option value="dedup_analyze">Dedup Analyze</option>
              <option value="normalizer_preview">Normalizer Preview</option>
            </select>
          </div>
          <div>
            <label htmlFor="job-mode" className="block text-xs font-medium text-slate-700">
              Execution Mode
            </label>
            <select
              id="job-mode"
              value={jobMode}
              onChange={(e) => setJobMode(e.target.value as JobMode)}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs"
            >
              <option value="inline">Inline (Immediate)</option>
              <option value="background">Background (Async Task)</option>
            </select>
          </div>
          <div className="flex items-end justify-end">
            <button
              type="button"
              disabled={loading}
              onClick={() => void handleSubmitJob()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3.5 py-2 text-xs font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
            >
              <Play className="h-3.5 w-3.5" /> Submit Job
            </button>
          </div>
        </div>
        <textarea
          aria-label="Job Parameters JSON"
          rows={3}
          value={jobParamsJson}
          onChange={(e) => setJobParamsJson(e.target.value)}
          className="mt-3 w-full rounded-lg border border-slate-300 bg-slate-50 p-2.5 font-mono text-xs"
        />

        {jobs.length > 0 && (
          <div className="mt-3 max-h-56 overflow-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-slate-200 text-slate-500">
                <tr>
                  <th className="py-1.5 pr-3">Job Type</th>
                  <th className="py-1.5 pr-3">Mode</th>
                  <th className="py-1.5 pr-3">Status</th>
                  <th className="py-1.5 pr-3">Actor</th>
                  <th className="py-1.5">Result Summary</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {jobs.map((job) => (
                  <tr key={job.id}>
                    <td className="py-1.5 pr-3 font-mono font-semibold text-slate-800">
                      {job.job_type}
                    </td>
                    <td className="py-1.5 pr-3 text-slate-600">{job.execution_mode}</td>
                    <td className="py-1.5 pr-3">
                      <span
                        className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                          job.status === 'completed'
                            ? 'bg-emerald-100 text-emerald-800'
                            : job.status === 'failed'
                            ? 'bg-rose-100 text-rose-800'
                            : 'bg-amber-100 text-amber-800'
                        }`}
                      >
                        {job.status}
                      </span>
                    </td>
                    <td className="py-1.5 pr-3 text-slate-600">{job.created_by}</td>
                    <td className="py-1.5 font-mono text-[11px] text-slate-600">
                      {job.error_message
                        ? job.error_message
                        : job.result
                        ? JSON.stringify(job.result).slice(0, 90)
                        : 'Pending...'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
