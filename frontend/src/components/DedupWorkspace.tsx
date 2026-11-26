import { useState } from 'react';
import { Check, GitMerge, Sparkles, Upload } from 'lucide-react';
import { analyzeDedup, proposeDedupMerge, uploadIngestFile } from '../api/client';
import { SAMPLE_DEDUP_RECORDS } from '../data/samples';
import type {
  DedupAnalyzeResponse,
  DuplicateCluster,
  SurvivorshipRule,
} from '../types/governance';

interface DedupWorkspaceProps {
  onProposalCreated: (message: string) => void;
}

export default function DedupWorkspace({ onProposalCreated }: DedupWorkspaceProps) {
  const [recordsJson, setRecordsJson] = useState(
    JSON.stringify(SAMPLE_DEDUP_RECORDS, null, 2),
  );
  const [threshold, setThreshold] = useState(0.78);
  const [survivorship, setSurvivorship] = useState<SurvivorshipRule>('most_complete');
  const [result, setResult] = useState<DedupAnalyzeResponse | null>(null);
  const [queuedClusters, setQueuedClusters] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAnalyze() {
    setError(null);
    setLoading(true);
    try {
      const parsed: unknown = JSON.parse(recordsJson);
      if (!Array.isArray(parsed) || parsed.length < 2) {
        throw new Error('Provide a JSON array of at least 2 records.');
      }
      const res = await analyzeDedup({
        records: parsed as Record<string, unknown>[],
        threshold,
        survivorship,
      });
      setResult(res);
      setQueuedClusters({});
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Duplicate analysis failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleProposeMerge(cluster: DuplicateCluster) {
    setError(null);
    setLoading(true);
    try {
      const proposal = await proposeDedupMerge({
        cluster_id: cluster.cluster_id,
        source_records: cluster.records,
        golden_record: cluster.golden_record,
        rationale: `Fuzzy entity match (${Math.round(cluster.average_similarity * 100)}% avg similarity)`,
      });
      setQueuedClusters((prev) => ({ ...prev, [cluster.cluster_id]: proposal.id }));
      onProposalCreated(`Queued merge proposal for ${cluster.cluster_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to queue merge proposal');
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
              Fuzzy Entity Resolution & Survivorship Merging
            </h2>
            <p className="text-xs text-slate-600">
              Detect fuzzy duplicates via blocking keys, Jaro-Winkler, and token-set scoring,
              preview golden records with field provenance, and queue human-reviewed merges.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setRecordsJson(JSON.stringify(SAMPLE_DEDUP_RECORDS, null, 2))}
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

        <div className="mt-4">
          <label htmlFor="dedup-records" className="block text-xs font-medium text-slate-700">
            Candidate Records (JSON Array)
          </label>
          <textarea
            id="dedup-records"
            rows={8}
            value={recordsJson}
            onChange={(e) => setRecordsJson(e.target.value)}
            className="mt-1.5 w-full rounded-lg border border-slate-300 bg-slate-50 p-3 font-mono text-xs text-slate-900 focus:border-indigo-500 focus:bg-white focus:outline-none"
          />
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-5">
          <div>
            <label htmlFor="dedup-threshold" className="block text-xs font-medium text-slate-700">
              Similarity Threshold: {threshold.toFixed(2)}
            </label>
            <input
              id="dedup-threshold"
              type="range"
              min="0.5"
              max="0.98"
              step="0.02"
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              className="mt-1.5 w-44"
            />
          </div>

          <div>
            <label htmlFor="dedup-survivorship" className="block text-xs font-medium text-slate-700">
              Survivorship Rule
            </label>
            <select
              id="dedup-survivorship"
              value={survivorship}
              onChange={(e) => setSurvivorship(e.target.value as SurvivorshipRule)}
              className="mt-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-900"
            >
              <option value="most_complete">Most Complete Record</option>
              <option value="most_recent">Most Recent (updated_at)</option>
              <option value="longest">Longest Value</option>
              <option value="prefer_first">Prefer First</option>
              <option value="prefer_non_null">Prefer Non-Null</option>
            </select>
          </div>

          <button
            type="button"
            disabled={loading}
            onClick={() => void handleAnalyze()}
            className="ml-auto inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            <GitMerge className="h-3.5 w-3.5" />
            Analyze Duplicates
          </button>
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {error}
          </div>
        )}
      </div>

      {result && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-3 text-xs text-indigo-900">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 shrink-0 text-indigo-600" />
              <span>{result.ai_summary}</span>
            </div>
            <span className="font-semibold">
              {result.cluster_count} cluster(s) · {result.duplicate_record_count} /{' '}
              {result.total_records} records
            </span>
          </div>

          {result.clusters.map((cluster) => {
            const queuedId = queuedClusters[cluster.cluster_id];
            return (
              <div
                key={cluster.cluster_id}
                className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-900">
                      {cluster.cluster_id} · Records: {cluster.record_ids.join(', ')}
                    </h3>
                    <p className="text-xs text-slate-500">
                      Average similarity {(cluster.average_similarity * 100).toFixed(1)}%
                    </p>
                  </div>
                  <button
                    type="button"
                    disabled={loading || Boolean(queuedId)}
                    onClick={() => void handleProposeMerge(cluster)}
                    className={`inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-xs font-semibold ${
                      queuedId
                        ? 'border border-emerald-200 bg-emerald-50 text-emerald-700'
                        : 'bg-emerald-600 text-white hover:bg-emerald-700'
                    } disabled:opacity-70`}
                  >
                    {queuedId ? (
                      <>
                        <Check className="h-3.5 w-3.5" /> Queued ({queuedId.slice(0, 8)})
                      </>
                    ) : (
                      'Propose Merge (HITL)'
                    )}
                  </button>
                </div>

                <div className="mt-4 grid gap-4 lg:grid-cols-2">
                  <div>
                    <p className="text-xs font-semibold text-slate-700">
                      Golden Record & Field Provenance
                    </p>
                    <div className="mt-2 divide-y divide-slate-100 rounded-lg border border-slate-200">
                      {Object.entries(cluster.golden_record).map(([field, value]) => (
                        <div
                          key={field}
                          className="flex items-center justify-between gap-3 px-3 py-1.5 text-xs"
                        >
                          <span className="font-medium text-slate-700">{field}</span>
                          <span className="font-mono text-slate-900">
                            {value === null ? 'null' : String(value)}
                          </span>
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">
                            from {cluster.field_provenance[field]}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div>
                    <p className="text-xs font-semibold text-slate-700">Pairwise Similarity</p>
                    <div className="mt-2 space-y-2">
                      {cluster.pair_matches.map((pair) => (
                        <div
                          key={`${pair.record_a_id}-${pair.record_b_id}`}
                          className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs"
                        >
                          <div className="flex items-center justify-between font-semibold text-slate-800">
                            <span>
                              {pair.record_a_id} ↔ {pair.record_b_id}
                            </span>
                            <span>{(pair.similarity * 100).toFixed(1)}%</span>
                          </div>
                          <p className="mt-1 font-mono text-[11px] text-slate-600">
                            {Object.entries(pair.field_scores)
                              .map(([k, v]) => `${k}: ${v}`)
                              .join(' · ')}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
