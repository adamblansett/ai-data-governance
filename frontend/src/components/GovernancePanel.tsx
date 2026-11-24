import { useCallback, useEffect, useState } from 'react';
import {
  CheckCircle2,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import {
  applyProposal,
  approveProposal,
  fetchAuditEvents,
  fetchProposals,
  rejectProposal,
  rollbackProposal,
  verifyAuditChain,
} from '../api/client';
import type {
  AuditChainVerification,
  AuditEvent,
  GovernanceProposal,
} from '../types/governance';

interface GovernancePanelProps {
  onDataChanged: () => void;
}

export default function GovernancePanel({ onDataChanged }: GovernancePanelProps) {
  const [proposals, setProposals] = useState<GovernanceProposal[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [verification, setVerification] = useState<AuditChainVerification | null>(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [reviewer, setReviewer] = useState('data-steward');
  const [notes, setNotes] = useState('Reviewed via governance dashboard');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadAll = useCallback(async () => {
    setError(null);
    setLoading(true);
    try {
      const [propList, eventsList, verifyRes] = await Promise.all([
        fetchProposals(statusFilter || undefined),
        fetchAuditEvents(50),
        verifyAuditChain(),
      ]);
      setProposals(Array.isArray(propList) ? propList : []);
      setAuditEvents(Array.isArray(eventsList) ? eventsList : []);
      setVerification(
        verifyRes && typeof verifyRes.valid === 'boolean' ? verifyRes : null,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load governance queue');
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  async function handleAction(fn: () => Promise<GovernanceProposal>) {
    setError(null);
    setLoading(true);
    try {
      await fn();
      await loadAll();
      onDataChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Governance action failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleVerifyChain() {
    setError(null);
    setLoading(true);
    try {
      const res = await verifyAuditChain();
      setVerification(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Audit chain verification failed');
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
              Human-in-the-Loop Approval Queue
            </h2>
            <p className="text-xs text-slate-600">
              All high-impact merges, bulk normalizations, and schema remediations require explicit
              approval before execution and retain full rollback snapshots.
            </p>
          </div>
          <button
            type="button"
            disabled={loading}
            onClick={() => void loadAll()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <div>
            <label htmlFor="gov-reviewer" className="block text-xs font-medium text-slate-700">
              Steward / Actor
            </label>
            <input
              id="gov-reviewer"
              type="text"
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
            />
          </div>
          <div>
            <label htmlFor="gov-notes" className="block text-xs font-medium text-slate-700">
              Review Notes / Rollback Reason
            </label>
            <input
              id="gov-notes"
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
            />
          </div>
          <div>
            <label htmlFor="gov-filter" className="block text-xs font-medium text-slate-700">
              Status Filter
            </label>
            <select
              id="gov-filter"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs"
            >
              <option value="">All Statuses</option>
              <option value="pending_review">Pending Review</option>
              <option value="approved">Approved</option>
              <option value="applied">Applied</option>
              <option value="rejected">Rejected</option>
              <option value="rolled_back">Rolled Back</option>
            </select>
          </div>
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {error}
          </div>
        )}

        <div className="mt-4 space-y-3">
          {proposals.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-200 p-6 text-center text-xs text-slate-500">
              No governance proposals found. Propose a merge, normalization, or schema remediation
              from one of the domain workspaces.
            </p>
          ) : (
            proposals.map((prop) => (
              <div
                key={prop.id}
                className="rounded-xl border border-slate-200 bg-slate-50/70 p-4"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded bg-slate-200 px-2 py-0.5 text-[11px] font-semibold uppercase text-slate-700">
                        {prop.domain}
                      </span>
                      <span
                        className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${
                          prop.status === 'pending_review'
                            ? 'bg-amber-100 text-amber-800'
                            : prop.status === 'approved'
                            ? 'bg-sky-100 text-sky-800'
                            : prop.status === 'applied'
                            ? 'bg-emerald-100 text-emerald-800'
                            : prop.status === 'rolled_back'
                            ? 'bg-purple-100 text-purple-800'
                            : 'bg-rose-100 text-rose-800'
                        }`}
                      >
                        {prop.status}
                      </span>
                      <span className="text-[11px] font-medium text-slate-500">
                        Risk: {prop.risk_level}
                      </span>
                    </div>
                    <h3 className="mt-1.5 text-sm font-semibold text-slate-900">{prop.title}</h3>
                    <p className="mt-0.5 text-xs text-slate-600">{prop.summary}</p>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setExpandedId(expandedId === prop.id ? null : prop.id)}
                      className="rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                    >
                      {expandedId === prop.id ? 'Hide Snapshots' : 'Inspect Snapshots'}
                    </button>

                    {prop.status === 'pending_review' && (
                      <>
                        <button
                          type="button"
                          disabled={loading}
                          onClick={() =>
                            void handleAction(() => approveProposal(prop.id, reviewer, notes))
                          }
                          className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-emerald-700"
                        >
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          Approve
                        </button>
                        <button
                          type="button"
                          disabled={loading}
                          onClick={() =>
                            void handleAction(() => rejectProposal(prop.id, reviewer, notes))
                          }
                          className="inline-flex items-center gap-1 rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-700"
                        >
                          <XCircle className="h-3.5 w-3.5" />
                          Reject
                        </button>
                      </>
                    )}

                    {prop.status === 'approved' && (
                      <button
                        type="button"
                        disabled={loading}
                        onClick={() => void handleAction(() => applyProposal(prop.id, reviewer))}
                        className="inline-flex items-center gap-1 rounded-lg bg-indigo-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-indigo-700"
                      >
                        <Play className="h-3.5 w-3.5" />
                        Apply Change
                      </button>
                    )}

                    {prop.status === 'applied' && (
                      <button
                        type="button"
                        disabled={loading}
                        onClick={() =>
                          void handleAction(() => rollbackProposal(prop.id, reviewer, notes))
                        }
                        className="inline-flex items-center gap-1 rounded-lg border border-purple-300 bg-purple-50 px-3 py-1.5 text-xs font-semibold text-purple-800 hover:bg-purple-100"
                      >
                        <RotateCcw className="h-3.5 w-3.5" />
                        Rollback
                      </button>
                    )}
                  </div>
                </div>

                {expandedId === prop.id && (
                  <div className="mt-3 grid gap-3 lg:grid-cols-2">
                    <div>
                      <p className="text-[11px] font-semibold uppercase text-slate-500">
                        Before Snapshot
                      </p>
                      <pre className="mt-1 max-h-48 overflow-auto rounded-lg border border-slate-200 bg-white p-2.5 font-mono text-[11px] text-slate-800">
                        {JSON.stringify(prop.before_snapshot, null, 2)}
                      </pre>
                    </div>
                    <div>
                      <p className="text-[11px] font-semibold uppercase text-slate-500">
                        {prop.status === 'applied' ? 'After Snapshot' : 'Staged Payload'}
                      </p>
                      <pre className="mt-1 max-h-48 overflow-auto rounded-lg border border-slate-200 bg-white p-2.5 font-mono text-[11px] text-slate-800">
                        {JSON.stringify(
                          prop.status === 'applied' ? prop.after_snapshot : prop.payload,
                          null,
                          2,
                        )}
                      </pre>
                    </div>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">
              Immutable Hash-Chained Audit Trail
            </h3>
            <p className="text-xs text-slate-600">
              Every scan, mask, detokenization, proposal, approval, execution, and rollback is
              linked via SHA-256 without storing raw PII.
            </p>
          </div>
          <button
            type="button"
            disabled={loading}
            onClick={() => void handleVerifyChain()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-slate-900 px-3.5 py-2 text-xs font-semibold text-white hover:bg-slate-800"
          >
            <ShieldCheck className="h-3.5 w-3.5" />
            Verify Hash Chain
          </button>
        </div>

        {verification && (
          <div
            className={`mt-3 flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium ${
              verification.valid
                ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                : 'border-rose-200 bg-rose-50 text-rose-800'
            }`}
          >
            {verification.valid ? (
              <ShieldCheck className="h-4 w-4 text-emerald-600" />
            ) : (
              <ShieldAlert className="h-4 w-4 text-rose-600" />
            )}
            <span>
              {verification.valid
                ? `Hash chain verified across ${verification.checked_count} event(s). Latest hash: ${verification.latest_hash?.slice(0, 16) ?? 'none'}`
                : `Chain integrity failure at sequence #${verification.broken_at_sequence ?? '?'}`}
            </span>
          </div>
        )}

        <div className="mt-4 max-h-72 overflow-auto">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-slate-200 text-slate-500">
              <tr>
                <th className="py-1.5 pr-3">Seq</th>
                <th className="py-1.5 pr-3">Domain</th>
                <th className="py-1.5 pr-3">Action</th>
                <th className="py-1.5 pr-3">Actor</th>
                <th className="py-1.5 pr-3">Hash</th>
                <th className="py-1.5">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {auditEvents.map((ev) => (
                <tr key={ev.id}>
                  <td className="py-1.5 pr-3 font-mono text-slate-600">#{ev.sequence_no}</td>
                  <td className="py-1.5 pr-3 font-semibold text-slate-800">{ev.domain}</td>
                  <td className="py-1.5 pr-3 font-mono text-slate-700">{ev.action}</td>
                  <td className="py-1.5 pr-3 text-slate-600">{ev.actor}</td>
                  <td className="py-1.5 pr-3 font-mono text-slate-500">
                    {ev.event_hash.slice(0, 12)}…
                  </td>
                  <td className="py-1.5 font-mono text-[11px] text-slate-600">
                    {JSON.stringify(ev.details)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
