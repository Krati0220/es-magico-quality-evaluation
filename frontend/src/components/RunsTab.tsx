import { useEffect, useState } from 'react';
import { api } from '../api';
import type { OverviewResponse, RunDetail, RunSummary } from '../types';

interface Props {
  overview: OverviewResponse;
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
  onOpenReview: (runId: string) => void;
}

export function RunsTab({ overview, selectedRunId, onSelectRun, onOpenReview }: Props) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [scope, setScope] = useState<'smoke' | 'full'>('smoke');
  const [candidate, setCandidate] = useState<'v2' | 'v3'>('v2');
  const [useMock, setUseMock] = useState<boolean>(!overview.provider.configured);
  const [delay, setDelay] = useState<number>(overview.provider.default_rate_limit_delay || 0);
  const [name, setName] = useState<string>('');
  const [creating, setCreating] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [showReport, setShowReport] = useState<boolean>(false);
  const [notice, setNotice] = useState<string | null>(null);

  const loadRuns = async () => {
    try {
      const res = await api.listRuns();
      setRuns(res.runs);
      if (!selectedRunId && res.runs.length > 0) {
        onSelectRun(res.runs[0].id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const loadDetail = async (id: string) => {
    try {
      const res = await api.getRun(id);
      setDetail(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    loadRuns();
  }, []);

  useEffect(() => {
    if (selectedRunId) {
      loadDetail(selectedRunId);
    }
  }, [selectedRunId]);

  useEffect(() => {
    const anyActive = runs.some((r) => r.is_active || r.status === 'running' || r.status === 'queued')
      || detail?.is_active || detail?.status === 'running' || detail?.status === 'queued';
    if (!anyActive) return;
    const timer = setInterval(() => {
      loadRuns();
      if (selectedRunId) loadDetail(selectedRunId);
    }, 2500);
    return () => clearInterval(timer);
  }, [runs, detail, selectedRunId]);

  const handleStart = async () => {
    setCreating(true);
    setError(null);
    try {
      const res = await api.createRun({
        name: name.trim() || undefined,
        scope,
        candidate_version: candidate,
        use_mock: useMock,
        rate_limit_delay: delay,
      });
      setName('');
      await loadRuns();
      onSelectRun(res.run_id);
      await loadDetail(res.run_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setCreating(false);
    }
  };

  const handleResume = async (id: string) => {
    setError(null);
    try {
      await api.resumeRun(id);
      await loadRuns();
      await loadDetail(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleCancel = async (id: string) => {
    try {
      await api.cancelRun(id);
      await loadDetail(id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleExport = async (id: string) => {
    try {
      const bundle = await api.exportRun(id);
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${id}-deliverable-bundle.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const handleDownloadReport = () => {
    if (!detail?.report_md) return;
    const blob = new Blob([detail.report_md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `REPORT-${detail.id}.md`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleSaveDeliverables = async (id: string) => {
    setError(null);
    setNotice(null);
    try {
      const res = await api.saveDeliverables(id);
      setNotice(`Saved ${res.files_written.length} deliverable files to ${res.directory}/`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const pct = detail && detail.total_steps > 0 ? Math.round((detail.completed_steps / detail.total_steps) * 100) : 0;

  return (
    <div>
      <div className="card mb-18">
        <h2>Launch Evaluation Run</h2>
        <div className="grid-4">
          <div>
            <label className="label">Run Scope</label>
            <select className="select" value={scope} onChange={(e) => setScope(e.target.value as 'smoke' | 'full')}>
              <option value="smoke">Smoke (T23 &amp; T03 · 12+12 calls)</option>
              <option value="full">Full Golden Set (30 cases · 180+180 calls)</option>
            </select>
          </div>
          <div>
            <label className="label">Comparison Pair</label>
            <select className="select" value={candidate} onChange={(e) => setCandidate(e.target.value as 'v2' | 'v3')}>
              <option value="v2">v1 (prod) vs v2 (assignment proposal)</option>
              <option value="v3">v1 (prod) vs v3 (spec-compliant candidate)</option>
            </select>
          </div>
          <div>
            <label className="label">Rate-Limit Delay (sec/call)</label>
            <input
              className="input"
              type="number"
              min={0}
              max={30}
              step={0.5}
              value={delay}
              onChange={(e) => setDelay(Number(e.target.value))}
            />
          </div>
          <div>
            <label className="label">Run Label (optional)</label>
            <input
              className="input"
              placeholder="e.g. Groq GPT-OSS 20B/120B"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
        </div>
        <div className="space-between mt-12">
          <label className="row" style={{ fontSize: 13, cursor: 'pointer' }}>
            <input type="checkbox" checked={useMock} onChange={(e) => setUseMock(e.target.checked)} />
            Mock Mode (offline plumbing test — never real assignment evidence)
          </label>
          <button className="btn primary" onClick={handleStart} disabled={creating}>
            {creating ? 'Starting...' : `Start ${scope === 'smoke' ? 'Smoke' : 'Full'} Run`}
          </button>
        </div>
        {error && <div className="alert fail mt-12">{error}</div>}
      </div>

      <div className="grid-2" style={{ gridTemplateColumns: '320px minmax(0, 1fr)' }}>
        <div className="card">
          <div className="space-between mb-12">
            <h3 style={{ margin: 0 }}>Saved Runs ({runs.length})</h3>
            <button className="btn" style={{ padding: '4px 10px' }} onClick={loadRuns}>Refresh</button>
          </div>
          {runs.length === 0 ? (
            <div className="muted" style={{ fontSize: 13 }}>No runs yet. Start a smoke or full run above.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {runs.map((r) => (
                <div
                  key={r.id}
                  className="card-subtle"
                  onClick={() => onSelectRun(r.id)}
                  style={{
                    cursor: 'pointer',
                    borderColor: selectedRunId === r.id ? 'var(--accent)' : undefined,
                    background: selectedRunId === r.id ? 'rgba(99, 102, 241, 0.14)' : undefined,
                  }}
                >
                  <div className="space-between">
                    <strong style={{ fontSize: 13 }}>{r.name}</strong>
                    <span className={`pill ${r.status === 'completed' ? 'ok' : r.status === 'failed' ? 'fail' : 'warn'}`}>
                      {r.status}
                    </span>
                  </div>
                  <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>
                    {r.baseline_version} vs {r.candidate_version} · {r.completed_steps}/{r.total_steps} steps
                    {r.use_mock ? ' · MOCK' : ''}
                  </div>
                  {r.recommendation && (
                    <div style={{ marginTop: 6 }}>
                      <span className={`pill ${r.recommendation === 'CONDITIONAL SHIP' ? 'ok' : 'fail'}`}>
                        {r.recommendation}
                      </span>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          {!detail ? (
            <div className="muted">Select a run to inspect metrics, risk slices, and generated report.</div>
          ) : (
            <div>
              <div className="space-between mb-12">
                <div>
                  <h2 style={{ margin: 0 }}>{detail.name}</h2>
                  <div className="muted" style={{ fontSize: 12 }}>
                    {detail.id} · {detail.scope.toUpperCase()} · {detail.baseline_version} vs {detail.candidate_version}
                    {detail.use_mock ? ' · MOCK MODE' : ''}
                  </div>
                </div>
                <div className="row">
                  {(detail.is_active || detail.status === 'running') && (
                    <button className="btn danger" onClick={() => handleCancel(detail.id)}>Cancel</button>
                  )}
                  {(detail.status === 'partial' || detail.status === 'cancelled' || detail.status === 'failed') && !detail.is_active && (
                    <button className="btn primary" onClick={() => handleResume(detail.id)}>Resume</button>
                  )}
                  {detail.has_review && (
                    <button className="btn primary" onClick={() => onOpenReview(detail.id)}>
                      Open Blinded Review →
                    </button>
                  )}
                  <button className="btn" onClick={() => handleExport(detail.id)}>Export JSON</button>
                  {!detail.use_mock && (
                    <button className="btn" onClick={() => handleSaveDeliverables(detail.id)}>Save to Repo</button>
                  )}
                  {detail.report_md && (
                    <button className="btn" onClick={handleDownloadReport}>Download REPORT.md</button>
                  )}
                </div>
              </div>
              {notice && <div className="alert ok mb-12">{notice}</div>}

              <div className="mb-18">
                <div className="space-between" style={{ fontSize: 12, marginBottom: 4 }}>
                  <span>Progress: {detail.completed_steps} / {detail.total_steps} operations</span>
                  <span>{pct}%</span>
                </div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${pct}%` }} />
                </div>
              </div>

              {detail.error_message && (
                <div className="alert fail">{detail.error_message}</div>
              )}

              {detail.metrics && (
                <>
                  <div className={`alert ${detail.metrics.recommendation === 'CONDITIONAL SHIP' ? 'ok' : 'fail'}`}>
                    <strong>Recommendation: {detail.metrics.recommendation}</strong>
                    {detail.metrics.decision_reasons.length > 0 && (
                      <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                        {detail.metrics.decision_reasons.map((reason, i) => <li key={i}>{reason}</li>)}
                      </ul>
                    )}
                  </div>

                  {detail.metrics.same_model_and_endpoint && (
                    <div className="alert warn">
                      <strong>Correlated-bias notice:</strong> Summariser and Judge use the same model &amp; endpoint. Use a distinct judge model for stronger empirical evidence.
                    </div>
                  )}

                  <div className="table-wrap mb-18">
                    <table>
                      <thead>
                        <tr>
                          <th>Version</th>
                          <th>Generated</th>
                          <th>Judged</th>
                          <th>Deterministic</th>
                          <th>Semantic</th>
                          <th>Combined</th>
                          <th>Critical</th>
                          <th>Mean F/C/U</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(detail.metrics.versions).map(([ver, v]) => (
                          <tr key={ver}>
                            <td><strong>{ver}</strong></td>
                            <td>{v.generated}/{v.planned}</td>
                            <td>{v.judged}/{v.planned}</td>
                            <td>{v.deterministic_passes}/{v.generated}</td>
                            <td>{v.semantic_passes}/{v.judged}</td>
                            <td>
                              <strong>
                                {v.combined_passes}/{v.planned} (
                                {v.combined_rate_over_planned !== null
                                  ? `${(v.combined_rate_over_planned * 100).toFixed(1)}%`
                                  : '—'})
                              </strong>
                            </td>
                            <td>{v.critical_outputs + v.deterministic_critical_outputs}</td>
                            <td>
                              {v.mean_scores.faithfulness !== null
                                ? `${v.mean_scores.faithfulness.toFixed(2)} / ${v.mean_scores.completeness?.toFixed(2)} / ${v.mean_scores.usefulness?.toFixed(2)}`
                                : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="grid-3 mb-18">
                    <div className="card-subtle">
                      <div className="stat-label">Paired Bootstrap 95% CI</div>
                      {detail.metrics.paired_comparison ? (
                        <>
                          <div style={{ fontSize: 18, fontWeight: 700, marginTop: 4 }}>
                            {detail.metrics.paired_comparison.mean_v2_minus_v1 >= 0 ? '+' : ''}
                            {(detail.metrics.paired_comparison.mean_v2_minus_v1 * 100).toFixed(1)} pp
                          </div>
                          <div className="muted" style={{ fontSize: 12 }}>
                            95% CI: [{(detail.metrics.paired_comparison.ci95_low * 100).toFixed(1)},{' '}
                            {(detail.metrics.paired_comparison.ci95_high * 100).toFixed(1)}] pp ({detail.metrics.paired_comparison.paired_cases} paired cases)
                          </div>
                        </>
                      ) : (
                        <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>Pending complete paired cases</div>
                      )}
                    </div>

                    <div className="card-subtle">
                      <div className="stat-label">Judge Validation</div>
                      <div style={{ fontSize: 18, fontWeight: 700, marginTop: 4 }}>
                        {detail.metrics.human.validation.n} / 20 held-out
                      </div>
                      <div className="muted" style={{ fontSize: 12 }}>
                        Status: {detail.metrics.human.status} · Kappa:{' '}
                        {detail.metrics.human.validation.kappa !== null
                          ? detail.metrics.human.validation.kappa.toFixed(2)
                          : 'n/a'}
                      </div>
                    </div>

                    <div className="card-subtle">
                      <div className="stat-label">Ops &amp; Cost</div>
                      <div style={{ fontSize: 18, fontWeight: 700, marginTop: 4 }}>
                        {detail.metrics.cost_usd !== null ? `$${detail.metrics.cost_usd.toFixed(4)}` : 'Unknown'}
                      </div>
                      <div className="muted" style={{ fontSize: 12 }}>
                        {detail.metrics.request_attempts} attempts · {detail.metrics.operational_error_attempts} errors
                      </div>
                    </div>
                  </div>

                  {detail.metrics.per_case.length > 0 && (
                    <div className="mb-18">
                      <h3>Per-Case Comparison</h3>
                      <div className="table-wrap" style={{ maxHeight: 260, overflowY: 'auto' }}>
                        <table>
                          <thead>
                            <tr>
                              <th>Case</th>
                              <th>Tags</th>
                              <th>{detail.baseline_version}</th>
                              <th>{detail.candidate_version}</th>
                              <th>Delta</th>
                              <th>Repeat Variability</th>
                            </tr>
                          </thead>
                          <tbody>
                            {detail.metrics.per_case.map((c) => (
                              <tr key={c.case_id}>
                                <td><strong>{c.case_id}</strong></td>
                                <td>{c.tags.slice(0, 3).join(', ')}</td>
                                <td>{(c.rates[detail.baseline_version] * 100).toFixed(0)}%</td>
                                <td>{(c.rates[detail.candidate_version] * 100).toFixed(0)}%</td>
                                <td style={{ color: c.delta > 0 ? 'var(--pass)' : c.delta < 0 ? 'var(--fail)' : undefined }}>
                                  {c.delta > 0 ? '+' : ''}{(c.delta * 100).toFixed(0)} pp
                                </td>
                                <td className="muted" style={{ fontSize: 12 }}>
                                  {c.variable_across_repeats[detail.baseline_version] ? `${detail.baseline_version} varied ` : ''}
                                  {c.variable_across_repeats[detail.candidate_version] ? `${detail.candidate_version} varied` : ''}
                                  {!c.variable_across_repeats[detail.baseline_version] && !c.variable_across_repeats[detail.candidate_version] ? 'stable' : ''}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {detail.recent_errors.length > 0 && (
                    <div className="mb-18">
                      <h3>Recent Operational Errors</h3>
                      <div className="table-wrap" style={{ maxHeight: 160, overflowY: 'auto' }}>
                        <table>
                          <thead>
                            <tr>
                              <th>Case</th>
                              <th>Ver</th>
                              <th>Stage</th>
                              <th>Attempt</th>
                              <th>Code</th>
                            </tr>
                          </thead>
                          <tbody>
                            {detail.recent_errors.map((e, i) => (
                              <tr key={i}>
                                <td>{e.case_id}</td>
                                <td>{e.version}</td>
                                <td>{e.stage}</td>
                                <td>{e.attempt}</td>
                                <td>{e.error_code} {e.error_detail ? `(${e.error_detail})` : ''}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {detail.report_md && (
                    <div>
                      <button className="btn mb-12" onClick={() => setShowReport((s) => !s)}>
                        {showReport ? 'Hide Generated REPORT.md' : 'Preview Generated REPORT.md'}
                      </button>
                      {showReport && <pre className="pre-box">{detail.report_md}</pre>}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
