import { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  Database,
  GitMerge,
  KeyRound,
  LayoutDashboard,
  PlugZap,
  ShieldCheck,
  Sparkles,
  UserCheck,
} from 'lucide-react';
import {
  fetchHealth,
  fetchProposals,
  fetchVaultStats,
  issueAuthToken,
  setAuthToken,
  verifyAuditChain,
} from './api/client';
import ConnectorsWorkspace from './components/ConnectorsWorkspace';
import DedupWorkspace from './components/DedupWorkspace';
import GovernancePanel from './components/GovernancePanel';
import NormalizerWorkspace from './components/NormalizerWorkspace';
import OverviewPanel from './components/OverviewPanel';
import PiiWorkspace from './components/PiiWorkspace';
import SchemaAuditWorkspace from './components/SchemaAuditWorkspace';
import type {
  AuditChainVerification,
  GovernanceProposal,
  HealthStatus,
  PiiVaultStatsResponse,
  Role,
  WorkspaceTab,
} from './types/governance';

const NAV_TABS: { id: WorkspaceTab; label: string; icon: typeof LayoutDashboard }[] = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'pii', label: 'PII & Vault', icon: KeyRound },
  { id: 'dedup', label: 'Duplicate Merge', icon: GitMerge },
  { id: 'normalizers', label: 'Normalizers', icon: Sparkles },
  { id: 'schema_audit', label: 'Schema Audit', icon: Database },
  { id: 'connectors', label: 'Connectors & Jobs', icon: PlugZap },
  { id: 'governance', label: 'Approvals & Audit', icon: ShieldCheck },
];

export default function App() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>('overview');
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [offline, setOffline] = useState(false);
  const [sessionRole, setSessionRole] = useState<'default' | Role>('default');
  const [vaultStats, setVaultStats] = useState<PiiVaultStatsResponse | null>(null);
  const [proposals, setProposals] = useState<GovernanceProposal[]>([]);
  const [auditVerification, setAuditVerification] =
    useState<AuditChainVerification | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const refreshSummary = useCallback(async () => {
    try {
      const [statsRes, proposalsRes, verifyRes] = await Promise.allSettled([
        fetchVaultStats(),
        fetchProposals(),
        verifyAuditChain(),
      ]);
      if (
        statsRes.status === 'fulfilled' &&
        typeof statsRes.value?.total_tokens === 'number'
      ) {
        setVaultStats(statsRes.value);
      }
      if (proposalsRes.status === 'fulfilled' && Array.isArray(proposalsRes.value)) {
        setProposals(proposalsRes.value);
      }
      if (
        verifyRes.status === 'fulfilled' &&
        typeof verifyRes.value?.valid === 'boolean'
      ) {
        setAuditVerification(verifyRes.value);
      }
    } catch {
      // Optional summary metrics degrade silently if endpoints are unavailable.
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function checkHealth() {
      try {
        const payload = await fetchHealth();
        if (!cancelled) {
          setHealth(payload);
          setOffline(false);
          if (payload.status === 'ok') {
            void refreshSummary();
          }
        }
      } catch {
        if (!cancelled) setOffline(true);
      }
    }
    void checkHealth();
    return () => {
      cancelled = true;
    };
  }, [refreshSummary]);

  async function handleRoleChange(nextRole: 'default' | Role) {
    setSessionRole(nextRole);
    if (nextRole === 'default') {
      setAuthToken(null);
      return;
    }
    try {
      const issued = await issueAuthToken({
        username: `ui-${nextRole}`,
        role: nextRole,
      });
      setAuthToken(issued.access_token);
      setToast(`Switched JWT session to ${issued.sub} (${issued.role})`);
      void refreshSummary();
    } catch (err) {
      setToast(err instanceof Error ? err.message : 'Unable to switch role token');
    }
  }

  function handleProposalCreated(message: string) {
    setToast(message);
    void refreshSummary();
  }

  const pendingCount = proposals.filter((p) => p.status === 'pending_review').length;

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-6 py-5">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600">
              Phase 2 — Autonomous Data Governance & Cleanup Platform
            </p>
            <h1 className="mt-1 text-2xl font-bold tracking-tight text-slate-900">
              AI Data Governance & Cleanup Agent
            </h1>
            <p className="mt-1 text-sm text-slate-600">
              Open-source, self-hosted AI data governance and cleanup platform for automated PII
              masking, duplicate record merging, database normalization, and schema hygiene.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2.5">
            <label className="flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-700">
              <UserCheck className="h-3.5 w-3.5 text-indigo-600" />
              <span className="sr-only">Session Role</span>
              <select
                aria-label="Session Role"
                value={sessionRole}
                onChange={(e) => void handleRoleChange(e.target.value as 'default' | Role)}
                className="bg-transparent text-xs font-semibold text-slate-800 focus:outline-none"
              >
                <option value="default">Role: Dev Default</option>
                <option value="viewer">Role: Viewer (JWT)</option>
                <option value="analyst">Role: Analyst (JWT)</option>
                <option value="steward">Role: Steward (JWT)</option>
                <option value="admin">Role: Admin (JWT)</option>
              </select>
            </label>

            <div className="flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3.5 py-1.5 text-xs font-medium">
              <Activity
                className={`h-3.5 w-3.5 ${
                  health?.status === 'ok'
                    ? 'text-emerald-600'
                    : offline
                    ? 'text-amber-600'
                    : 'text-slate-400'
                }`}
              />
              <span>
                {health?.status === 'ok'
                  ? `API Healthy (${health.llm_provider})`
                  : offline
                  ? 'Offline Starter Preview'
                  : 'Checking API...'}
              </span>
            </div>
          </div>
        </div>

        <nav
          aria-label="Workspaces"
          className="mx-auto flex max-w-6xl flex-wrap items-center gap-1 px-6 pb-3"
        >
          {NAV_TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${
                  isActive
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'
                }`}
              >
                <Icon className="h-3.5 w-3.5" />
                <span>{tab.label}</span>
                {tab.id === 'governance' && pendingCount > 0 && (
                  <span
                    className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold ${
                      isActive
                        ? 'bg-white text-indigo-700'
                        : 'bg-amber-100 text-amber-800'
                    }`}
                  >
                    {pendingCount}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </header>

      <main className="mx-auto max-w-6xl space-y-6 px-6 py-8">
        {toast && (
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-xs text-emerald-900">
            <span>{toast}</span>
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => {
                  setActiveTab('governance');
                  setToast(null);
                }}
                className="font-semibold text-emerald-700 underline"
              >
                Open Approvals Queue
              </button>
              <button
                type="button"
                onClick={() => setToast(null)}
                className="text-slate-500 hover:text-slate-700"
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        {activeTab === 'overview' && (
          <OverviewPanel
            onSelectTab={setActiveTab}
            vaultStats={vaultStats}
            proposals={proposals}
            auditVerification={auditVerification}
          />
        )}

        {activeTab === 'pii' && <PiiWorkspace onVaultChanged={() => void refreshSummary()} />}

        {activeTab === 'dedup' && (
          <DedupWorkspace onProposalCreated={handleProposalCreated} />
        )}

        {activeTab === 'normalizers' && (
          <NormalizerWorkspace onProposalCreated={handleProposalCreated} />
        )}

        {activeTab === 'schema_audit' && (
          <SchemaAuditWorkspace onProposalCreated={handleProposalCreated} />
        )}

        {activeTab === 'connectors' && <ConnectorsWorkspace />}

        {activeTab === 'governance' && (
          <GovernancePanel onDataChanged={() => void refreshSummary()} />
        )}
      </main>
    </div>
  );
}
