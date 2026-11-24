import { useState } from 'react';
import { KeyRound, Lock, ScanSearch, Unlock } from 'lucide-react';
import { detokenizePii, maskPii, scanPii } from '../api/client';
import { SAMPLE_PII_RECORDS, SAMPLE_PII_TEXT } from '../data/samples';
import type {
  MaskStrategy,
  PiiDetokenizeResponse,
  PiiEntityMatch,
  PiiMaskResponse,
  PiiScanResponse,
} from '../types/governance';

interface PiiWorkspaceProps {
  onVaultChanged: () => void;
}

export default function PiiWorkspace({ onVaultChanged }: PiiWorkspaceProps) {
  const [mode, setMode] = useState<'text' | 'records'>('text');
  const [textInput, setTextInput] = useState(SAMPLE_PII_TEXT);
  const [recordsInput, setRecordsInput] = useState(
    JSON.stringify(SAMPLE_PII_RECORDS, null, 2),
  );
  const [strategy, setStrategy] = useState<MaskStrategy>('tokenize');
  const [policyName, setPolicyName] = useState('default');
  const [includeNer, setIncludeNer] = useState(true);

  const [scanResult, setScanResult] = useState<PiiScanResponse | null>(null);
  const [maskResult, setMaskResult] = useState<PiiMaskResponse | null>(null);
  const [tokensInput, setTokensInput] = useState('');
  const [detokenizeActor, setDetokenizeActor] = useState('privacy-officer');
  const [detokenizeReason, setDetokenizeReason] = useState('Authorized DSAR review');
  const [detokenizeResult, setDetokenizeResult] = useState<PiiDetokenizeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function buildTargetPayload(): { text?: string; records?: Record<string, unknown>[] } {
    if (mode === 'text') {
      return { text: textInput };
    }
    const parsed: unknown = JSON.parse(recordsInput);
    if (!Array.isArray(parsed)) {
      throw new Error('Structured JSON input must be an array of record objects.');
    }
    return { records: parsed as Record<string, unknown>[] };
  }

  async function handleScan() {
    setError(null);
    setLoading(true);
    try {
      const target = buildTargetPayload();
      const result = await scanPii({
        ...target,
        policy_name: policyName,
        include_ner: includeNer,
      });
      setScanResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Scan failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleMask() {
    setError(null);
    setLoading(true);
    try {
      const target = buildTargetPayload();
      const result = await maskPii({
        ...target,
        strategy,
        policy_name: policyName,
        include_ner: includeNer,
      });
      setMaskResult(result);
      if (result.tokens_created.length > 0) {
        setTokensInput(result.tokens_created.join(', '));
      }
      onVaultChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Masking failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleDetokenize() {
    setError(null);
    setLoading(true);
    try {
      const tokens = tokensInput
        .split(/[\s,]+/)
        .map((t) => t.trim())
        .filter(Boolean);
      if (tokens.length === 0) {
        throw new Error('Enter at least one vault token to detokenize.');
      }
      const res = await detokenizePii({
        tokens,
        actor: detokenizeActor,
        reason: detokenizeReason,
      });
      setDetokenizeResult(res);
      onVaultChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Detokenize failed');
    } finally {
      setLoading(false);
    }
  }

  const findings: PiiEntityMatch[] = maskResult?.findings ?? scanResult?.findings ?? [];
  const riskScore = maskResult?.risk_score ?? scanResult?.risk_score;
  const riskLevel = maskResult?.risk_level ?? scanResult?.risk_level;

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-slate-900">
              PII Detection, Masking & Encrypted Vault
            </h2>
            <p className="text-xs text-slate-600">
              Scan text or JSON records using regex + checksum validators (Luhn, Mod-97 IBAN) and
              heuristic NER, then redact, partial-mask, hash, or vault-tokenize.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setMode('text')}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium ${
                mode === 'text'
                  ? 'bg-indigo-600 text-white'
                  : 'border border-slate-200 bg-slate-50 text-slate-700'
              }`}
            >
              Freeform Text
            </button>
            <button
              type="button"
              onClick={() => setMode('records')}
              className={`rounded-lg px-3 py-1.5 text-xs font-medium ${
                mode === 'records'
                  ? 'bg-indigo-600 text-white'
                  : 'border border-slate-200 bg-slate-50 text-slate-700'
              }`}
            >
              Structured JSON
            </button>
            <button
              type="button"
              onClick={() => {
                setTextInput(SAMPLE_PII_TEXT);
                setRecordsInput(JSON.stringify(SAMPLE_PII_RECORDS, null, 2));
              }}
              className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              Load Sample
            </button>
          </div>
        </div>

        <div className="mt-4">
          <label htmlFor="pii-input" className="block text-xs font-medium text-slate-700">
            {mode === 'text' ? 'Input Text' : 'Structured Records (JSON Array)'}
          </label>
          <textarea
            id="pii-input"
            rows={mode === 'text' ? 4 : 8}
            value={mode === 'text' ? textInput : recordsInput}
            onChange={(e) =>
              mode === 'text' ? setTextInput(e.target.value) : setRecordsInput(e.target.value)
            }
            className="mt-1.5 w-full rounded-lg border border-slate-300 bg-slate-50 p-3 font-mono text-xs text-slate-900 focus:border-indigo-500 focus:bg-white focus:outline-none"
          />
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-4">
          <div>
            <label htmlFor="pii-strategy" className="block text-xs font-medium text-slate-700">
              Masking Strategy
            </label>
            <select
              id="pii-strategy"
              value={strategy}
              onChange={(e) => setStrategy(e.target.value as MaskStrategy)}
              className="mt-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs text-slate-900"
            >
              <option value="tokenize">Tokenize (Reversible Vault)</option>
              <option value="mask">Partial Mask</option>
              <option value="redact">Redact ([REDACTED_TYPE])</option>
              <option value="hash">Deterministic HMAC Hash</option>
            </select>
          </div>

          <div>
            <label htmlFor="pii-policy" className="block text-xs font-medium text-slate-700">
              Policy Name
            </label>
            <input
              id="pii-policy"
              type="text"
              value={policyName}
              onChange={(e) => setPolicyName(e.target.value)}
              className="mt-1 w-36 rounded-lg border border-slate-300 px-3 py-1.5 text-xs text-slate-900"
            />
          </div>

          <label className="flex items-center gap-2 pb-1.5 text-xs text-slate-700">
            <input
              type="checkbox"
              checked={includeNer}
              onChange={(e) => setIncludeNer(e.target.checked)}
              className="rounded border-slate-300 text-indigo-600"
            />
            Include Heuristic NER
          </label>

          <div className="ml-auto flex items-center gap-2">
            <button
              type="button"
              disabled={loading}
              onClick={() => void handleScan()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3.5 py-2 text-xs font-semibold text-slate-800 hover:bg-slate-50 disabled:opacity-50"
            >
              <ScanSearch className="h-3.5 w-3.5" />
              Scan PII
            </button>
            <button
              type="button"
              disabled={loading}
              onClick={() => void handleMask()}
              className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3.5 py-2 text-xs font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              <Lock className="h-3.5 w-3.5" />
              Apply Strategy
            </button>
          </div>
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {error}
          </div>
        )}
      </div>

      {(scanResult || maskResult) && (
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold text-slate-900">
                Detected Entities ({findings.length})
              </h3>
              {riskScore !== undefined && (
                <span
                  className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                    riskLevel === 'high'
                      ? 'bg-rose-100 text-rose-700'
                      : riskLevel === 'medium'
                      ? 'bg-amber-100 text-amber-700'
                      : 'bg-emerald-100 text-emerald-700'
                  }`}
                >
                  Risk {riskScore} ({riskLevel})
                </span>
              )}
            </div>

            <div className="mt-3 max-h-64 overflow-auto">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-slate-200 text-slate-500">
                  <tr>
                    <th className="py-1.5 pr-2">Entity</th>
                    <th className="py-1.5 pr-2">Preview</th>
                    <th className="py-1.5 pr-2">Source</th>
                    <th className="py-1.5">Location</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {findings.map((f, idx) => (
                    <tr key={`${f.entity_type}-${f.start}-${idx}`}>
                      <td className="py-1.5 pr-2 font-semibold text-slate-800">
                        {f.entity_type}
                      </td>
                      <td className="py-1.5 pr-2 font-mono text-slate-700">{f.masked_preview}</td>
                      <td className="py-1.5 pr-2 text-slate-500">{f.source}</td>
                      <td className="py-1.5 font-mono text-slate-500">
                        {f.field_path ?? `${f.start}:${f.end}`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <h3 className="text-sm font-semibold text-slate-900">Masked Output</h3>
            {maskResult ? (
              <div className="mt-3 space-y-3">
                <pre className="max-h-56 overflow-auto rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-xs text-slate-800 whitespace-pre-wrap">
                  {maskResult.masked_text ??
                    JSON.stringify(maskResult.masked_records, null, 2)}
                </pre>
                {maskResult.tokens_created.length > 0 && (
                  <p className="text-xs text-slate-600">
                    <span className="font-medium text-slate-800">Vault Tokens:</span>{' '}
                    <span className="font-mono">{maskResult.tokens_created.join(', ')}</span>
                  </p>
                )}
              </div>
            ) : (
              <p className="mt-3 text-xs text-slate-500">
                Run <strong>Apply Strategy</strong> to generate redacted, masked, hashed, or
                vault-tokenized output.
              </p>
            )}
          </div>
        </div>
      )}

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-indigo-600" />
          <h3 className="text-sm font-semibold text-slate-900">
            Audited Vault Detokenization
          </h3>
        </div>
        <p className="mt-1 text-xs text-slate-600">
          Resolve reversible vault tokens with mandatory actor and compliance justification logged
          to the SHA-256 audit chain.
        </p>

        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <div className="sm:col-span-3">
            <label htmlFor="detok-tokens" className="block text-xs font-medium text-slate-700">
              Vault Tokens (comma or space separated)
            </label>
            <input
              id="detok-tokens"
              type="text"
              value={tokensInput}
              onChange={(e) => setTokensInput(e.target.value)}
              placeholder="TOK_EMAIL_..., TOK_SSN_..."
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 font-mono text-xs"
            />
          </div>
          <div>
            <label htmlFor="detok-actor" className="block text-xs font-medium text-slate-700">
              Actor
            </label>
            <input
              id="detok-actor"
              type="text"
              value={detokenizeActor}
              onChange={(e) => setDetokenizeActor(e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
            />
          </div>
          <div className="sm:col-span-2 flex items-end gap-2">
            <div className="flex-1">
              <label htmlFor="detok-reason" className="block text-xs font-medium text-slate-700">
                Audit Reason
              </label>
              <input
                id="detok-reason"
                type="text"
                value={detokenizeReason}
                onChange={(e) => setDetokenizeReason(e.target.value)}
                className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-xs"
              />
            </div>
            <button
              type="button"
              disabled={loading}
              onClick={() => void handleDetokenize()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-indigo-200 bg-indigo-50 px-3.5 py-2 text-xs font-semibold text-indigo-700 hover:bg-indigo-100 disabled:opacity-50"
            >
              <Unlock className="h-3.5 w-3.5" />
              Detokenize
            </button>
          </div>
        </div>

        {detokenizeResult && (
          <pre className="mt-3 rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-xs text-slate-800">
            {JSON.stringify(detokenizeResult, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
