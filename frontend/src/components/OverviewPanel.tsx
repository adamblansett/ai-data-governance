import {
  ArrowRight,
  CheckCircle2,
  Cpu,
  Database,
  FileSearch,
  GitMerge,
  KeyRound,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import type {
  AuditChainVerification,
  GovernanceProposal,
  PiiVaultStatsResponse,
  WorkspaceTab,
} from '../types/governance';

interface OverviewPanelProps {
  onSelectTab: (tab: WorkspaceTab) => void;
  vaultStats: PiiVaultStatsResponse | null;
  proposals: GovernanceProposal[];
  auditVerification: AuditChainVerification | null;
}

const CAPABILITIES: {
  tab: WorkspaceTab;
  title: string;
  summary: string;
  icon: typeof KeyRound;
  accent: string;
}[] = [
  {
    tab: 'pii',
    title: 'PII Detection & Masking',
    summary:
      'Deterministic regex + NER scanning with reversible vault tokenization or redaction.',
    icon: KeyRound,
    accent: 'text-indigo-600 bg-indigo-50',
  },
  {
    tab: 'dedup',
    title: 'Duplicate Record Merging',
    summary: 'Fuzzy entity resolution with survivorship rules and undoable merge logs.',
    icon: GitMerge,
    accent: 'text-emerald-600 bg-emerald-50',
  },
  {
    tab: 'normalizers',
    title: 'Database Normalization',
    summary: 'Format standardization for emails, phones, addresses, taxonomies, and nulls.',
    icon: Sparkles,
    accent: 'text-amber-600 bg-amber-50',
  },
  {
    tab: 'schema_audit',
    title: 'Schema Hygiene Audits',
    summary: 'Orphaned FK detection, unindexed query hotspots, and retention policy enforcement.',
    icon: Database,
    accent: 'text-sky-600 bg-sky-50',
  },
];

export default function OverviewPanel({
  onSelectTab,
  vaultStats,
  proposals,
  auditVerification,
}: OverviewPanelProps) {
  const pendingCount = proposals.filter((p) => p.status === 'pending_review').length;

  return (
    <div className="space-y-6">
      <section className="grid gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <p className="text-xs font-medium text-slate-500">Encrypted Vault Tokens</p>
          <p className="mt-1 text-2xl font-bold text-slate-900">
            {vaultStats ? vaultStats.total_tokens : 0}
          </p>
          <p className="mt-1 text-xs text-slate-500">HKDF + Fernet reversible tokens</p>
        </div>

        <button
          type="button"
          onClick={() => onSelectTab('governance')}
          className="rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:border-indigo-300"
        >
          <p className="text-xs font-medium text-slate-500">Pending HITL Approvals</p>
          <p className="mt-1 text-2xl font-bold text-slate-900">{pendingCount}</p>
          <p className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-indigo-600">
            Review approval queue <ArrowRight className="h-3 w-3" />
          </p>
        </button>

        <button
          type="button"
          onClick={() => onSelectTab('governance')}
          className="rounded-xl border border-slate-200 bg-white p-4 text-left shadow-sm transition hover:border-emerald-300"
        >
          <p className="text-xs font-medium text-slate-500">Audit Hash Chain</p>
          <div className="mt-1 flex items-center gap-2">
            <CheckCircle2
              className={`h-5 w-5 ${
                auditVerification === null
                  ? 'text-slate-400'
                  : auditVerification.valid
                  ? 'text-emerald-600'
                  : 'text-rose-600'
              }`}
            />
            <span className="text-lg font-bold text-slate-900">
              {auditVerification === null
                ? 'Ready'
                : auditVerification.valid
                ? `Valid (${auditVerification.checked_count})`
                : `Tamper @ #${auditVerification.broken_at_sequence ?? '?'}`}
            </span>
          </div>
          <p className="mt-1 inline-flex items-center gap-1 text-xs text-slate-500">
            <FileSearch className="h-3 w-3" /> SHA-256 tamper-evident log
          </p>
        </button>
      </section>

      <section className="grid gap-4 sm:grid-cols-2">
        {CAPABILITIES.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.title}
              type="button"
              onClick={() => onSelectTab(item.tab)}
              className="group rounded-xl border border-slate-200 bg-white p-5 text-left shadow-sm transition hover:border-indigo-300 hover:shadow"
            >
              <div className="flex items-start justify-between gap-3">
                <div className={`rounded-lg p-2 ${item.accent}`}>
                  <Icon className="h-4 w-4" />
                </div>
                <span className="inline-flex items-center gap-1 text-xs font-medium text-indigo-600 opacity-80 group-hover:opacity-100">
                  Open workspace <ArrowRight className="h-3.5 w-3.5" />
                </span>
              </div>
              <h2 className="mt-3 text-sm font-semibold text-slate-900">{item.title}</h2>
              <p className="mt-1.5 text-xs leading-relaxed text-slate-600">{item.summary}</p>
            </button>
          );
        })}
      </section>

      <section className="grid gap-4 sm:grid-cols-2">
        <div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-5">
          <Cpu className="mt-0.5 h-5 w-5 shrink-0 text-indigo-600" />
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Local-First LLM Routing</h3>
            <p className="mt-1 text-xs text-slate-600">
              Supports offline deterministic mock execution, local Ollama inference, and guarded
              cloud fallback with automatic outbound PII scrubbing.
            </p>
          </div>
        </div>
        <div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white p-5">
          <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Production Security Baseline</h3>
            <p className="mt-1 text-xs text-slate-600">
              Ships with fail-fast production secret validation, ASGI security headers, and
              human-in-the-loop review boundaries with rollback snapshots.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
