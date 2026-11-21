import { useEffect, useState } from 'react';
import { api } from '../api';
import type { ReviewItem, ReviewResponse, RunSummary } from '../types';

interface Props {
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
}

const SCORE_OPTIONS = [1, 2, 3, 4, 5];

export function ReviewTab({ selectedRunId, onSelectRun }: Props) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [review, setReview] = useState<ReviewResponse | null>(null);
  const [phaseFilter, setPhaseFilter] = useState<'calibration' | 'validation'>('calibration');
  const [activeId, setActiveId] = useState<string | null>(null);
  const [reviewer, setReviewer] = useState<string>(localStorage.getItem('es_eval_reviewer') || '');
  const [faithfulness, setFaithfulness] = useState<number>(5);
  const [completeness, setCompleteness] = useState<number>(4);
  const [usefulness, setUsefulness] = useState<number>(4);
  const [criticalText, setCriticalText] = useState<string>('');
  const [notes, setNotes] = useState<string>('');
  const [attest, setAttest] = useState<boolean>(false);
  const [saving, setSaving] = useState<boolean>(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listRuns().then((res) => {
      setRuns(res.runs);
      if (!selectedRunId && res.runs.length > 0) {
        onSelectRun(res.runs[0].id);
      }
    }).catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  const loadReview = async (runId: string) => {
    setError(null);
    try {
      const res = await api.getReview(runId);
      setReview(res);
      if (res.available && res.items.length > 0) {
        const firstUnlabeled =
          res.items.find((i) => i.review_phase === 'calibration' && !i.label) ||
          res.items.find((i) => !i.label) ||
          res.items[0];
        setPhaseFilter(firstUnlabeled.review_phase);
        selectItem(firstUnlabeled);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    if (selectedRunId) loadReview(selectedRunId);
  }, [selectedRunId]);

  const selectItem = (item: ReviewItem) => {
    setActiveId(item.review_id);
    setMessage(null);
    setError(null);
    if (item.label) {
      setReviewer(item.label.reviewed_by);
      setFaithfulness(item.label.faithfulness);
      setCompleteness(item.label.completeness);
      setUsefulness(item.label.usefulness);
      setCriticalText(item.label.critical_errors.join('\n'));
      setNotes(item.label.notes);
      setAttest(item.label.human_attestation);
    } else {
      setFaithfulness(5);
      setCompleteness(4);
      setUsefulness(4);
      setCriticalText('');
      setNotes('');
      setAttest(false);
    }
  };

  const phaseItems = (review?.items || []).filter((i) => i.review_phase === phaseFilter);
  const activeItem = (review?.items || []).find((i) => i.review_id === activeId) || phaseItems[0] || null;

  const handleSave = async () => {
    if (!selectedRunId || !activeItem) return;
    if (!reviewer.trim()) {
      setError('Enter your name under Reviewed By.');
      return;
    }
    if (!attest) {
      setError('You must check the personal review attestation box.');
      return;
    }
    if (!notes.trim()) {
      setError('Add concise source-grounded assessment notes.');
      return;
    }
    setSaving(true);
    setError(null);
    setMessage(null);
    localStorage.setItem('es_eval_reviewer', reviewer.trim());
    try {
      const res = await api.submitReview(selectedRunId, activeItem.review_id, {
        reviewed_by: reviewer.trim(),
        human_attestation: attest,
        faithfulness,
        completeness,
        usefulness,
        critical_errors: criticalText.split('\n').map((s) => s.trim()).filter(Boolean),
        notes: notes.trim(),
      });
      setMessage(`Saved ${res.review_id}. Updated recommendation: ${res.recommendation}`);
      const updated = await api.getReview(selectedRunId);
      setReview(updated);
      const nextUnlabeled = updated.items.find((i) => i.review_phase === phaseFilter && !i.label);
      if (nextUnlabeled) selectItem(nextUnlabeled);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="card mb-18">
        <div className="space-between">
          <div>
            <h2 style={{ margin: 0 }}>Blinded Human Review (Judge Validation)</h2>
            <p className="muted" style={{ margin: '4px 0 0', fontSize: 13 }}>
              Prompt version IDs and LLM judge ratings are hidden here. Complete Calibration first, freeze the judge, then label Held-Out Validation.
            </p>
          </div>
          <select
            className="select"
            style={{ width: 280 }}
            value={selectedRunId || ''}
            onChange={(e) => onSelectRun(e.target.value)}
          >
            <option value="">Select a run...</option>
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name} ({r.status})
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <div className="alert fail">{error}</div>}
      {message && <div className="alert ok">{message}</div>}

      {review && !review.available && (
        <div className="alert warn">{review.reason || 'Review set not available yet.'}</div>
      )}

      {review?.available && (
        <>
          <div className="grid-3 mb-18">
            <div className="card">
              <div className="stat-label">Calibration Progress</div>
              <div className="stat-value">
                {review.progress?.calibration_done} / {review.progress?.calibration_total}
              </div>
              <div className="muted" style={{ fontSize: 12 }}>5 cases × 2 blinded versions</div>
            </div>
            <div className="card">
              <div className="stat-label">Held-Out Validation</div>
              <div className="stat-value">
                {review.progress?.validation_done} / {review.progress?.validation_total}
              </div>
              <div className="muted" style={{ fontSize: 12 }}>10 disjoint cases × 2 blinded versions</div>
            </div>
            <div className="card">
              <div className="stat-label">Validation Judge Agreement</div>
              <div className="stat-value">
                {review.human_metrics?.validation.exact_agreement !== null &&
                review.human_metrics?.validation.exact_agreement !== undefined
                  ? `${(review.human_metrics.validation.exact_agreement * 100).toFixed(0)}%`
                  : 'Pending'}
              </div>
              <div className="muted" style={{ fontSize: 12 }}>
                False passes: {review.human_metrics?.validation.confusion_matrix.false_pass ?? 0} ·
                False fails: {review.human_metrics?.validation.confusion_matrix.false_fail ?? 0} ·
                Kappa: {review.human_metrics?.validation.kappa !== null && review.human_metrics?.validation.kappa !== undefined
                  ? review.human_metrics.validation.kappa.toFixed(2)
                  : 'n/a'}
              </div>
            </div>
          </div>

          <div className="grid-2" style={{ gridTemplateColumns: '240px minmax(0, 1fr)' }}>
            <div className="card">
              <div className="row mb-12">
                <button
                  className={`btn ${phaseFilter === 'calibration' ? 'primary' : ''}`}
                  style={{ flex: 1, padding: '6px 8px' }}
                  onClick={() => setPhaseFilter('calibration')}
                >
                  Cal ({review.progress?.calibration_done}/{review.progress?.calibration_total})
                </button>
                <button
                  className={`btn ${phaseFilter === 'validation' ? 'primary' : ''}`}
                  style={{ flex: 1, padding: '6px 8px' }}
                  onClick={() => setPhaseFilter('validation')}
                >
                  Val ({review.progress?.validation_done}/{review.progress?.validation_total})
                </button>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 540, overflowY: 'auto' }}>
                {phaseItems.map((item) => (
                  <button
                    key={item.review_id}
                    className="btn"
                    onClick={() => selectItem(item)}
                    style={{
                      justifyContent: 'space-between',
                      borderColor: activeItem?.review_id === item.review_id ? 'var(--accent)' : undefined,
                      background: activeItem?.review_id === item.review_id ? 'rgba(99,102,241,0.18)' : undefined,
                    }}
                  >
                    <span>{item.review_id}</span>
                    <span className={`pill ${item.label ? 'ok' : ''}`} style={{ padding: '1px 7px', fontSize: 11 }}>
                      {item.label ? 'Labeled' : 'Pending'}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            {activeItem && (
              <div className="card">
                <div className="space-between mb-12">
                  <h3 style={{ margin: 0 }}>
                    {activeItem.review_id}{' '}
                    <span className="pill">{activeItem.review_phase.toUpperCase()}</span>
                  </h3>
                  <span className="muted" style={{ fontSize: 12 }}>Version &amp; judge scores hidden</span>
                </div>

                <div className="label">Source Conversation</div>
                <pre className="pre-box mb-12" style={{ maxHeight: 210 }}>{activeItem.conversation}</pre>

                <div className="grid-2 mb-12">
                  <div className="card-subtle">
                    <div className="label" style={{ color: 'var(--pass)' }}>Must Include</div>
                    <ul style={{ margin: '4px 0', paddingLeft: 16, fontSize: 12.5 }}>
                      {activeItem.expectations.must_include.map((m, i) => <li key={i}>{m}</li>)}
                    </ul>
                  </div>
                  <div className="card-subtle">
                    <div className="label" style={{ color: 'var(--fail)' }}>Must Not Include</div>
                    <ul style={{ margin: '4px 0', paddingLeft: 16, fontSize: 12.5 }}>
                      {activeItem.expectations.must_not_include.map((m, i) => <li key={i}>{m}</li>)}
                    </ul>
                  </div>
                </div>

                <div className="label">Blinded Candidate Summary</div>
                <pre className="pre-box mb-18" style={{ borderColor: 'var(--accent)', fontSize: 13 }}>
                  {activeItem.summary}
                </pre>

                <div className="grid-3 mb-12">
                  {[
                    ['Faithfulness (min 5)', faithfulness, setFaithfulness],
                    ['Completeness (min 4)', completeness, setCompleteness],
                    ['Usefulness (min 4)', usefulness, setUsefulness],
                  ].map(([title, val, setter]) => (
                    <div key={title as string} className="card-subtle">
                      <div className="label">{title as string}</div>
                      <div className="row">
                        {SCORE_OPTIONS.map((score) => (
                          <button
                            key={score}
                            type="button"
                            className={`btn ${(val as number) === score ? 'primary' : ''}`}
                            style={{ padding: '5px 10px' }}
                            onClick={() => (setter as (n: number) => void)(score)}
                          >
                            {score}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="grid-2 mb-12">
                  <div>
                    <label className="label">Critical Errors (one per line; leave empty if none)</label>
                    <textarea
                      className="textarea"
                      rows={3}
                      placeholder="e.g. Leaked customer phone number (+91 98765 43210)"
                      value={criticalText}
                      onChange={(e) => setCriticalText(e.target.value)}
                    />
                  </div>
                  <div>
                    <label className="label">Source-Grounded Assessment Notes (required)</label>
                    <textarea
                      className="textarea"
                      rows={3}
                      placeholder="Explain your scores based on the conversation..."
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                    />
                  </div>
                </div>

                <div className="space-between">
                  <div className="row">
                    <input
                      className="input"
                      style={{ width: 200 }}
                      placeholder="Your Name (reviewed_by)"
                      value={reviewer}
                      onChange={(e) => setReviewer(e.target.value)}
                    />
                    <label className="row" style={{ fontSize: 12.5, cursor: 'pointer' }}>
                      <input type="checkbox" checked={attest} onChange={(e) => setAttest(e.target.checked)} />
                      I personally reviewed this output (human attestation)
                    </label>
                  </div>
                  <button className="btn primary" onClick={handleSave} disabled={saving}>
                    {saving ? 'Saving...' : 'Save Human Label'}
                  </button>
                </div>
              </div>
            )}
          </div>

          {review.human_metrics && (
            <div className="card mt-18">
              <h2>Can We Trust the Judge? (Agreement &amp; Disagreements)</h2>
              <div className="grid-2 mb-18">
                {(['calibration', 'validation'] as const).map((split) => {
                  const m = review.human_metrics?.[split];
                  if (!m) return null;
                  return (
                    <div key={split} className="card-subtle">
                      <div className="space-between mb-12">
                        <strong style={{ textTransform: 'capitalize' }}>{split} Split (n={m.n})</strong>
                        <span className="pill">
                          Agreement: {m.exact_agreement !== null ? `${(m.exact_agreement * 100).toFixed(1)}%` : 'n/a'} ·
                          Kappa: {m.kappa !== null ? m.kappa.toFixed(2) : 'n/a'}
                        </span>
                      </div>
                      <div className="row" style={{ fontSize: 12 }}>
                        <span className="pill ok">Both Pass: {m.confusion_matrix.both_pass}</span>
                        <span className="pill">Both Fail: {m.confusion_matrix.both_fail}</span>
                        <span className="pill fail">False Pass: {m.confusion_matrix.false_pass}</span>
                        <span className="pill warn">False Fail: {m.confusion_matrix.false_fail}</span>
                      </div>
                      <div className="muted mt-12" style={{ fontSize: 12 }}>
                        Critical errors missed: <strong>{m.critical_errors_missed ?? 0}</strong> · MAE (F/C/U):{' '}
                        {m.mean_absolute_error
                          ? `${m.mean_absolute_error.faithfulness?.toFixed(2) ?? '—'} / ${m.mean_absolute_error.completeness?.toFixed(2) ?? '—'} / ${m.mean_absolute_error.usefulness?.toFixed(2) ?? '—'}`
                          : '—'}
                      </div>
                    </div>
                  );
                })}
              </div>

              {Array.isArray(review.human_metrics.disagreements) && review.human_metrics.disagreements.length > 0 && (
                <div>
                  <h3>Labeled Disagreements ({review.human_metrics.disagreements.length})</h3>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Review ID</th>
                          <th>Split</th>
                          <th>Human vs Judge</th>
                          <th>Scores (F/C/U)</th>
                          <th>Notes vs Judge Reasons</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(review.human_metrics.disagreements as Array<{
                          review_id: string;
                          split: string;
                          human_pass: boolean;
                          judge_pass: boolean;
                          human: { faithfulness: number; completeness: number; usefulness: number; notes: string };
                          judge: { faithfulness: number; completeness: number; usefulness: number; reasons: { faithfulness: string } };
                        }>).map((d) => (
                          <tr key={d.review_id}>
                            <td><strong>{d.review_id}</strong></td>
                            <td>{d.split}</td>
                            <td>
                              <span className={`pill ${d.human_pass ? 'ok' : 'fail'}`}>H: {d.human_pass ? 'Pass' : 'Fail'}</span>{' '}
                              <span className={`pill ${d.judge_pass ? 'ok' : 'fail'}`}>J: {d.judge_pass ? 'Pass' : 'Fail'}</span>
                            </td>
                            <td style={{ fontSize: 12 }}>
                              H: {d.human.faithfulness}/{d.human.completeness}/{d.human.usefulness}<br />
                              J: {d.judge.faithfulness}/{d.judge.completeness}/{d.judge.usefulness}
                            </td>
                            <td style={{ fontSize: 12 }}>
                              <div><strong>You:</strong> {d.human.notes}</div>
                              <div className="muted"><strong>Judge:</strong> {d.judge.reasons.faithfulness}</div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
