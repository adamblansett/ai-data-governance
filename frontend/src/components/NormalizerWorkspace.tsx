import { useState } from 'react';
import { Check, Eye, Sparkles, Upload } from 'lucide-react';
import { previewNormalizers, proposeNormalizers, uploadIngestFile } from '../api/client';
import { SAMPLE_NORMALIZER_RECORDS, SAMPLE_NORMALIZER_RULES } from '../data/samples';
import type { FieldRule, NormalizerPreviewResponse } from '../types/governance';

interface NormalizerWorkspaceProps {
  onProposalCreated: (message: string) => void;
}

export default function NormalizerWorkspace({ onProposalCreated }: NormalizerWorkspaceProps) {
  const [recordsJson, setRecordsJson] = useState(
    JSON.stringify(SAMPLE_NORMALIZER_RECORDS, null, 2),
  );
  const [rulesJson, setRulesJson] = useState(
    JSON.stringify(SAMPLE_NORMALIZER_RULES, null, 2),
  );
  const [preview, setPreview] = useState<NormalizerPreviewResponse | null>(null);
  const [queuedProposalId, setQueuedProposalId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function parseInputs(): { records: Record<string, unknown>[]; rules: FieldRule[] } {
    const records: unknown = JSON.parse(recordsJson);
    const rules: unknown = JSON.parse(rulesJson);
    if (!Array.isArray(records) || records.length === 0) {
      throw new Error('Provide a non-empty JSON array of records.');
    }
    if (!Array.isArray(rules) || rules.length === 0) {
      throw new Error('Provide a non-empty JSON array of normalization rules.');
    }
    return {
      records: records as Record<string, unknown>[],
      rules: rules as FieldRule[],
    };
  }

  async function handlePreview() {
    setError(null);
    setLoading(true);
    try {
      const payload = parseInputs();
      const res = await previewNormalizers(payload);
      setPreview(res);
      setQueuedProposalId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Normalization preview failed');
    } finally {
      setLoading(false);
    }
  }

  async function handlePropose() {
    setError(null);
    setLoading(true);
    try {
      const payload = parseInputs();
      const proposal = await proposeNormalizers({
        ...payload,
        title: `Bulk normalization across ${payload.records.length} records`,
      });
      setQueuedProposalId(proposal.id);
      onProposalCreated('Queued bulk normalization proposal for HITL review');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to queue normalization proposal');
    } finally {
      setLoading(false);
    }
  }

  async function handleFileUpload(file: File | undefined) {
    if (!file) return;
    setError(null);
    setLoading(true);
    try {
      const ingested = await uploadIngestFile(file);
      setRecordsJson(JSON.stringify(ingested.records, null, 2));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'File upload failed');
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
              Database Normalization & Transform Preview
            </h2>
            <p className="text-xs text-slate-600">
              Standardize emails, E.164 phones, USPS addresses, taxonomies, null sentinels,
              whitespace, and ISO dates non-destructively before staging for approval.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setRecordsJson(JSON.stringify(SAMPLE_NORMALIZER_RECORDS, null, 2));
                setRulesJson(JSON.stringify(SAMPLE_NORMALIZER_RULES, null, 2));
              }}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              Load Sample
            </button>
            <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50">
              <Upload className="h-3.5 w-3.5" />
              Upload CSV/JSON
              <input
                type="file"
                accept=".csv,.json"
                className="hidden"
                onChange={(e) => void handleFileUpload(e.target.files?.[0])}
              />
            </label>
          </div>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div>
            <label htmlFor="norm-records" className="block text-xs font-medium text-slate-700">
              Input Records (JSON Array)
            </label>
            <textarea
              id="norm-records"
              rows={9}
              value={recordsJson}
              onChange={(e) => setRecordsJson(e.target.value)}
              className="mt-1.5 w-full rounded-lg border border-slate-300 bg-slate-50 p-3 font-mono text-xs text-slate-900 focus:border-indigo-500 focus:bg-white focus:outline-none"
            />
          </div>
          <div>
            <label htmlFor="norm-rules" className="block text-xs font-medium text-slate-700">
              Field Rules (JSON Array)
            </label>
            <textarea
              id="norm-rules"
              rows={9}
              value={rulesJson}
              onChange={(e) => setRulesJson(e.target.value)}
              className="mt-1.5 w-full rounded-lg border border-slate-300 bg-slate-50 p-3 font-mono text-xs text-slate-900 focus:border-indigo-500 focus:bg-white focus:outline-none"
            />
          </div>
        </div>

        <div className="mt-4 flex flex-wrap justify-end gap-2">
          <button
            type="button"
            disabled={loading}
            onClick={() => void handlePreview()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            <Eye className="h-3.5 w-3.5" />
            Preview Transforms
          </button>
          <button
            type="button"
            disabled={loading || Boolean(queuedProposalId)}
            onClick={() => void handlePropose()}
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
              <>
                <Sparkles className="h-3.5 w-3.5" /> Propose Normalization (HITL)
              </>
            )}
          </button>
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {error}
          </div>
        )}
      </div>

      {preview && (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <p className="text-xs text-slate-500">Total Records</p>
              <p className="mt-1 text-xl font-bold text-slate-900">{preview.total_records}</p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <p className="text-xs text-slate-500">Changed Cells</p>
              <p className="mt-1 text-xl font-bold text-indigo-600">{preview.changed_cells}</p>
            </div>
            <div className="rounded-xl border border-slate-200 bg-white p-4">
              <p className="text-xs text-slate-500">Validation Warnings</p>
              <p
                className={`mt-1 text-xl font-bold ${
                  preview.invalid_cells > 0 ? 'text-rose-600' : 'text-emerald-600'
                }`}
              >
                {preview.invalid_cells}
              </p>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="text-sm font-semibold text-slate-900">Cell Transformation Diffs</h3>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-slate-200 text-slate-500">
                  <tr>
                    <th className="py-2 pr-3">Record</th>
                    <th className="py-2 pr-3">Field</th>
                    <th className="py-2 pr-3">Rule</th>
                    <th className="py-2 pr-3">Original</th>
                    <th className="py-2 pr-3">Normalized</th>
                    <th className="py-2">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {preview.changes.map((c, idx) => (
                    <tr key={`${c.record_id}-${c.field}-${idx}`}>
                      <td className="py-2 pr-3 font-mono text-slate-600">{c.record_id}</td>
                      <td className="py-2 pr-3 font-medium text-slate-900">{c.field}</td>
                      <td className="py-2 pr-3 text-slate-500">{c.kind}</td>
                      <td className="py-2 pr-3 font-mono text-slate-600">
                        {c.original === null ? 'null' : String(c.original)}
                      </td>
                      <td className="py-2 pr-3 font-mono text-slate-900">
                        {c.normalized === null ? 'null' : String(c.normalized)}
                      </td>
                      <td className="py-2">
                        {c.valid ? (
                          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-medium text-emerald-700">
                            Valid
                          </span>
                        ) : (
                          <span className="rounded-full bg-rose-100 px-2 py-0.5 text-[11px] font-medium text-rose-700">
                            {c.issue ?? 'Invalid'}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
