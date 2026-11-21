import { useEffect, useState } from 'react';
import { api } from '../api';
import type { OverviewResponse, PlaygroundResponse } from '../types';

interface Props {
  overview: OverviewResponse;
  initialCaseId: string | null;
}

export function PlaygroundTab({ overview, initialCaseId }: Props) {
  const [mode, setMode] = useState<'case' | 'custom'>('case');
  const [caseId, setCaseId] = useState<string>(initialCaseId || overview.golden_cases[0]?.id || 'T23');
  const [customConvo, setCustomConvo] = useState<string>(
    'CUSTOMER: My smart plug smells like burning! Call me at +91 98765 43210 right now.\nAGENT: Please unplug it immediately. I am escalating to our product safety team for replacement today.',
  );
  const [selectedVersions, setSelectedVersions] = useState<string[]>(['v1', 'v2', 'v3']);
  const [customPrompt, setCustomPrompt] = useState<string>(overview.prompts.v3 || overview.prompts.v1 || '');
  const [runJudge, setRunJudge] = useState<boolean>(true);
  const [useMock, setUseMock] = useState<boolean>(!overview.provider.configured);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<PlaygroundResponse | null>(null);

  useEffect(() => {
    if (initialCaseId) {
      setMode('case');
      setCaseId(initialCaseId);
    }
  }, [initialCaseId]);

  const toggleVersion = (v: string) => {
    setSelectedVersions((prev) =>
      prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v],
    );
  };

  const handleRun = async () => {
    if (selectedVersions.length === 0) {
      setError('Select at least one prompt version.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await api.playgroundRun({
        case_id: mode === 'case' ? caseId : null,
        custom_conversation: mode === 'custom' ? customConvo : null,
        versions: selectedVersions,
        custom_prompt: selectedVersions.includes('custom') ? customPrompt : null,
        run_judge: runJudge,
        use_mock: useMock,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const activeCase = overview.golden_cases.find((c) => c.id === caseId);

  return (
    <div>
      {!overview.provider.configured && (
        <div className="alert warn">
          <strong>Live LLM not configured on server:</strong> Set <code>LLM_BASE_URL</code>, <code>LLM_MODEL</code>, and{' '}
          <code>LLM_API_KEY</code> (e.g. Groq) in Render / <code>.env</code> for live model outputs. Mock Mode is enabled for UI testing only.
        </div>
      )}

      <div className="card mb-18">
        <div className="space-between mb-12">
          <h2 style={{ margin: 0 }}>Live Summariser &amp; Judge Playground</h2>
          <div className="row">
            <label className="row" style={{ fontSize: 13, cursor: 'pointer' }}>
              <input type="checkbox" checked={runJudge} onChange={(e) => setRunJudge(e.target.checked)} />
              Run LLM Judge
            </label>
            <label className="row" style={{ fontSize: 13, cursor: 'pointer' }}>
              <input type="checkbox" checked={useMock} onChange={(e) => setUseMock(e.target.checked)} />
              Mock Mode (plumbing only)
            </label>
            <button className="btn primary" onClick={handleRun} disabled={loading}>
              {loading ? 'Running...' : 'Run Comparison'}
            </button>
          </div>
        </div>

        <div className="grid-2">
          <div>
            <div className="row mb-12">
              <button className={`btn ${mode === 'case' ? 'primary' : ''}`} onClick={() => setMode('case')}>
                Supplied Thread (45)
              </button>
              <button className={`btn ${mode === 'custom' ? 'primary' : ''}`} onClick={() => setMode('custom')}>
                Custom Thread
              </button>
            </div>

            {mode === 'case' ? (
              <>
                <label className="label">Select Conversation</label>
                <select className="select mb-12" value={caseId} onChange={(e) => setCaseId(e.target.value)}>
                  <optgroup label="Golden Set (30)">
                    {overview.golden_cases.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.id} [{c.channel}] — {c.tags.slice(0, 3).join(', ')}
                      </option>
                    ))}
                  </optgroup>
                  <optgroup label="Unselected Set (15)">
                    {overview.unselected_cases.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.id} [{c.channel}] (unselected)
                      </option>
                    ))}
                  </optgroup>
                </select>
                {activeCase && (
                  <pre className="pre-box" style={{ maxHeight: 200 }}>{activeCase.conversation}</pre>
                )}
              </>
            ) : (
              <>
                <label className="label">Paste Support Thread</label>
                <textarea
                  className="textarea"
                  rows={8}
                  value={customConvo}
                  onChange={(e) => setCustomConvo(e.target.value)}
                />
              </>
            )}
          </div>

          <div>
            <label className="label">Prompt Versions to Compare</label>
            <div className="row mb-12">
              {['v1', 'v2', 'v3', 'custom'].map((v) => (
                <button
                  key={v}
                  className={`btn ${selectedVersions.includes(v) ? 'primary' : ''}`}
                  onClick={() => toggleVersion(v)}
                >
                  {selectedVersions.includes(v) ? '✓ ' : ''}
                  {v}
                </button>
              ))}
            </div>

            {selectedVersions.includes('custom') ? (
              <>
                <label className="label">Custom System Prompt</label>
                <textarea
                  className="textarea"
                  rows={7}
                  value={customPrompt}
                  onChange={(e) => setCustomPrompt(e.target.value)}
                />
              </>
            ) : (
              <div className="card-subtle" style={{ fontSize: 12.5 }}>
                <strong>What gets checked automatically on every output:</strong>
                <ul style={{ margin: '6px 0 0', paddingLeft: 18 }} className="muted">
                  <li>Single plain paragraph (no line breaks, no Markdown, no heading labels like <code>Issue:</code>)</li>
                  <li>Length ceiling ≤ 80 words (Unicode whitespace)</li>
                  <li>Generic + source-aware PII redaction (phones, emails, addresses, OTPs, card suffixes)</li>
                  <li>Safety hazard signal on safety-tagged threads &amp; profanity filtering</li>
                  <li>Optional blinded LLM judge (Faithfulness 5/5, Completeness ≥4, Usefulness ≥4, 0 critical errors)</li>
                </ul>
              </div>
            )}
          </div>
        </div>

        {error && <div className="alert fail mt-12">{error}</div>}
      </div>

      {result && (
        <div className="grid-3">
          {result.outputs.map((out) => (
            <div key={out.version} className="card">
              <div className="space-between mb-12">
                <div>
                  <strong style={{ fontSize: 16 }}>{out.version.toUpperCase()}</strong>
                  <div className="muted" style={{ fontSize: 11 }}>{out.model || 'provider'}</div>
                </div>
                {out.error ? (
                  <span className="pill fail">Error: {out.error}</span>
                ) : (
                  <span className={`pill ${out.combined_pass ? 'ok' : 'fail'}`}>
                    {out.combined_pass ? 'PASS' : 'FAIL'}
                  </span>
                )}
              </div>

              {out.error ? (
                <div className="alert fail">
                  {out.error} {out.error_detail ? `(${out.error_detail})` : ''}
                </div>
              ) : (
                <>
                  <div className="label">Generated Summary ({out.word_count} words · {out.latency_seconds}s)</div>
                  <pre className="pre-box mb-12" style={{ whiteSpace: 'pre-wrap' }}>{out.summary}</pre>

                  {out.checks && (
                    <div className="mb-12">
                      <div className="space-between" style={{ marginBottom: 6 }}>
                        <span className="label" style={{ margin: 0 }}>Deterministic Checks</span>
                        <span className={`pill ${out.checks.passed ? 'ok' : 'fail'}`}>
                          {out.checks.passed ? 'All Passed' : out.checks.critical_failure ? 'Critical Failure' : 'Failed'}
                        </span>
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                        {out.checks.rules.filter((r) => !r.passed).map((r) => (
                          <div key={r.rule_id} className="card-subtle" style={{ padding: '6px 9px', borderColor: 'rgba(239,68,68,0.4)', fontSize: 12 }}>
                            <strong style={{ color: '#fca5a5' }}>{r.rule_id}</strong> ({r.severity}): observed{' '}
                            <code>{JSON.stringify(r.observed)}</code>
                          </div>
                        ))}
                        {out.checks.passed && (
                          <div className="muted" style={{ fontSize: 12 }}>
                            All {out.checks.rules.length} deterministic rules passed.
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {out.judgment && (
                    <div className="card-subtle">
                      <div className="space-between" style={{ marginBottom: 6 }}>
                        <strong style={{ fontSize: 13 }}>LLM Judge</strong>
                        <span className={`pill ${out.semantic_pass ? 'ok' : 'fail'}`}>
                          {out.semantic_pass ? 'Semantic Pass' : 'Semantic Fail'}
                        </span>
                      </div>
                      <div className="row mb-12" style={{ fontSize: 12 }}>
                        <span className="tag">Faith: {out.judgment.faithfulness}/5</span>
                        <span className="tag">Comp: {out.judgment.completeness}/5</span>
                        <span className="tag">Use: {out.judgment.usefulness}/5</span>
                      </div>
                      <div className="muted" style={{ fontSize: 12 }}>
                        <div><strong>Faithfulness:</strong> {out.judgment.reasons.faithfulness}</div>
                        <div><strong>Completeness:</strong> {out.judgment.reasons.completeness}</div>
                        <div><strong>Usefulness:</strong> {out.judgment.reasons.usefulness}</div>
                      </div>
                      {out.judgment.critical_errors.length > 0 && (
                        <div className="mt-12">
                          <strong style={{ color: '#fca5a5', fontSize: 12 }}>Critical Errors:</strong>
                          {out.judgment.critical_errors.map((ce, idx) => (
                            <div key={idx} style={{ fontSize: 12, color: '#fecaca', marginTop: 4 }}>
                              • [{ce.kind}] {ce.explanation}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {out.judge_error && (
                    <div className="alert warn mt-12">Judge error: {out.judge_error}</div>
                  )}

                  {(out.cost_usd !== null && out.cost_usd !== undefined) && (
                    <div className="muted mt-12" style={{ fontSize: 11 }}>
                      Est. cost: ${((out.cost_usd || 0) + (out.judge_cost_usd || 0)).toFixed(6)}
                    </div>
                  )}
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
