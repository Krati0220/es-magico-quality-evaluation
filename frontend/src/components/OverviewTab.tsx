import { useMemo, useState } from 'react';
import type { GoldenCase, OverviewResponse } from '../types';

interface Props {
  overview: OverviewResponse;
  onInspectInPlayground: (caseId: string) => void;
}

export function OverviewTab({ overview, onInspectInPlayground }: Props) {
  const [tagFilter, setTagFilter] = useState<string>('all');
  const [search, setSearch] = useState<string>('');
  const [selectedCase, setSelectedCase] = useState<GoldenCase | null>(overview.golden_cases[0] || null);

  const allTags = useMemo(() => {
    const counts = overview.coverage?.tag_counts || {};
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [overview.coverage]);

  const filteredCases = useMemo(() => {
    const q = search.trim().toLowerCase();
    return overview.golden_cases.filter((c) => {
      if (tagFilter !== 'all' && !c.tags.includes(tagFilter)) return false;
      if (!q) return true;
      return (
        c.id.toLowerCase().includes(q) ||
        c.selection_reason.toLowerCase().includes(q) ||
        c.tags.some((t) => t.toLowerCase().includes(q)) ||
        c.conversation.toLowerCase().includes(q)
      );
    });
  }, [overview.golden_cases, tagFilter, search]);

  return (
    <div>
      <div className="grid-4 mb-18">
        <div className="card">
          <div className="stat-label">Golden Set</div>
          <div className="stat-value">{overview.golden_cases.length}</div>
          <div className="muted" style={{ fontSize: 12 }}>
            {overview.coverage?.channels
              ? `${overview.coverage.channels.chat || 0} chat · ${overview.coverage.channels.email || 0} email · ${overview.coverage.channels.voice || 0} voice`
              : 'Selected threads'}
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Planned Full Eval</div>
          <div className="stat-value">
            {overview.config.case_count * 2 * overview.config.repeats * 2} calls
          </div>
          <div className="muted" style={{ fontSize: 12 }}>
            {overview.config.repeats} repeats × 2 versions × gen + judge
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Semantic Gate</div>
          <div className="stat-value">
            {overview.config.rubric.faithfulness_min}/{overview.config.rubric.completeness_min}/{overview.config.rubric.usefulness_min}
          </div>
          <div className="muted" style={{ fontSize: 12 }}>
            Faithfulness / Completeness / Usefulness min
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Ship Threshold</div>
          <div className="stat-value">
            {Math.round((overview.config.release.minimum_combined_pass_rate || 0.95) * 100)}%
          </div>
          <div className="muted" style={{ fontSize: 12 }}>
            0 critical errors · ≥20 human labels · NI margin -5pp
          </div>
        </div>
      </div>

      <div className="grid-2 mb-18">
        <div className="card">
          <h2>Product Spec (Verbatim)</h2>
          <pre className="pre-box">{overview.spec}</pre>
          <h3 className="mt-12">Declared Gap Policies</h3>
          <p className="muted" style={{ fontSize: 13, margin: 0 }}>{overview.config.judge_policy}</p>
        </div>

        <div className="card">
          <h2>Prompt Versions (v1 vs v2 vs v3)</h2>
          {(['v1', 'v2', 'v3'] as const).map((ver) =>
            overview.prompts[ver] ? (
              <div key={ver} className="mb-12">
                <div className="space-between" style={{ marginBottom: 4 }}>
                  <strong>
                    {ver === 'v1'
                      ? 'v1 — Production Baseline'
                      : ver === 'v2'
                        ? 'v2 — Proposed (Spec Conflict)'
                        : 'v3 — Spec-Compliant Candidate'}
                  </strong>
                  <span className={`pill ${ver === 'v2' ? 'fail' : ver === 'v3' ? 'ok' : ''}`}>
                    {ver === 'v2' ? 'Violates 1-paragraph rule' : ver === 'v3' ? 'Addresses spec gaps' : 'Current prod'}
                  </span>
                </div>
                <pre className="pre-box" style={{ maxHeight: 110 }}>{overview.prompts[ver]}</pre>
              </div>
            ) : null,
          )}
        </div>
      </div>

      <div className="card">
        <div className="space-between mb-12">
          <h2 style={{ margin: 0 }}>30-Case Golden Set Explorer</h2>
          <div className="row">
            <input
              className="input"
              style={{ width: 220 }}
              placeholder="Search ID, tag, or text..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <select className="select" style={{ width: 200 }} value={tagFilter} onChange={(e) => setTagFilter(e.target.value)}>
              <option value="all">All risk tags ({overview.golden_cases.length})</option>
              {allTags.map(([tag, count]) => (
                <option key={tag} value={tag}>
                  {tag} ({count})
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="grid-2">
          <div style={{ maxHeight: 460, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
            {filteredCases.map((c) => {
              const active = selectedCase?.id === c.id;
              return (
                <div
                  key={c.id}
                  onClick={() => setSelectedCase(c)}
                  className="card-subtle"
                  style={{
                    cursor: 'pointer',
                    borderColor: active ? 'var(--accent)' : undefined,
                    background: active ? 'rgba(99, 102, 241, 0.14)' : undefined,
                  }}
                >
                  <div className="space-between">
                    <strong>
                      {c.id} <span className="muted" style={{ fontWeight: 400 }}>({c.channel})</span>
                    </strong>
                    <div className="row" style={{ gap: 4 }}>
                      {c.tags.slice(0, 4).map((t) => (
                        <span key={t} className="tag">{t}</span>
                      ))}
                    </div>
                  </div>
                  <div className="muted" style={{ fontSize: 12.5, marginTop: 4 }}>{c.selection_reason}</div>
                </div>
              );
            })}
          </div>

          {selectedCase && (
            <div className="card-subtle">
              <div className="space-between mb-12">
                <div>
                  <strong style={{ fontSize: 15 }}>{selectedCase.id}</strong>{' '}
                  <span className="tag">{selectedCase.channel}</span>
                </div>
                <button className="btn primary" onClick={() => onInspectInPlayground(selectedCase.id)}>
                  Test in Playground →
                </button>
              </div>
              <div className="label">Conversation</div>
              <pre className="pre-box mb-12" style={{ maxHeight: 180 }}>{selectedCase.conversation}</pre>
              <div className="grid-2">
                <div>
                  <div className="label" style={{ color: 'var(--pass)' }}>Must Include</div>
                  <ul style={{ margin: '4px 0', paddingLeft: 18, fontSize: 12.5 }}>
                    {selectedCase.must_include.map((m, i) => <li key={i}>{m}</li>)}
                  </ul>
                </div>
                <div>
                  <div className="label" style={{ color: 'var(--fail)' }}>Must Not Include</div>
                  <ul style={{ margin: '4px 0', paddingLeft: 18, fontSize: 12.5 }}>
                    {selectedCase.must_not_include.map((m, i) => <li key={i}>{m}</li>)}
                  </ul>
                </div>
              </div>
              {selectedCase.sensitive_spans && selectedCase.sensitive_spans.length > 0 && (
                <div className="mt-12">
                  <div className="label">Tracked Sensitive Spans</div>
                  <div className="row">
                    {selectedCase.sensitive_spans.map((s, i) => (
                      <span key={i} className="pill fail">{s.type}: {s.value}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
