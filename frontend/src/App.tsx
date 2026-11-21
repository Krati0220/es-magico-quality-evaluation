import { useEffect, useState } from 'react';
import { api, getStoredToken, setStoredToken } from './api';
import { OverviewTab } from './components/OverviewTab';
import { PlaygroundTab } from './components/PlaygroundTab';
import { ReviewTab } from './components/ReviewTab';
import { RunsTab } from './components/RunsTab';
import type { HealthResponse, OverviewResponse } from './types';

type Tab = 'overview' | 'playground' | 'runs' | 'review';

export function App() {
  const [tab, setTab] = useState<Tab>('overview');
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [tokenInput, setTokenInput] = useState<string>(getStoredToken());
  const [needsAuth, setNeedsAuth] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [playgroundCaseId, setPlaygroundCaseId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const bootstrap = async () => {
    setError(null);
    try {
      const h = await api.health();
      setHealth(h);
      try {
        const ov = await api.overview();
        setOverview(ov);
        setNeedsAuth(false);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        if (msg.toLowerCase().includes('token') || msg.includes('401')) {
          setNeedsAuth(true);
        } else {
          setError(msg);
        }
      }
    } catch (err) {
      setError(
        `Cannot reach backend API (${err instanceof Error ? err.message : String(err)}). ` +
          'Start FastAPI locally (`uvicorn backend.app:app --reload`) or check VITE_API_URL.',
      );
    }
  };

  useEffect(() => {
    bootstrap();
  }, []);

  const handleUnlock = (e: React.FormEvent) => {
    e.preventDefault();
    setStoredToken(tokenInput);
    bootstrap();
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-badge">EM</div>
          <div>
            <h1>Es Magico — AI Quality Studio</h1>
            <p>Support Handoff Prompt Regression &amp; Judge Validation</p>
          </div>
        </div>

        <nav className="nav-tabs">
          {([
            ['overview', 'Spec & Golden Set'],
            ['playground', 'Live Playground'],
            ['runs', 'Eval Runs & Report'],
            ['review', 'Blinded Human Review'],
          ] as [Tab, string][]).map(([id, label]) => (
            <button
              key={id}
              className={`nav-tab ${tab === id ? 'active' : ''}`}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </nav>

        <div className="status-pills">
          {health && (
            <>
              <span className={`pill ${health.provider.configured ? 'ok' : 'warn'}`}>
                {health.provider.configured
                  ? `LLM: ${health.provider.generate.model}`
                  : 'LLM: Unconfigured (Mock Ready)'}
              </span>
              <span className="pill">DB: {health.database}</span>
            </>
          )}
        </div>
      </header>

      <main className="main">
        {needsAuth ? (
          <div className="card" style={{ maxWidth: 460, margin: '48px auto' }}>
            <h2>Private Workspace Access</h2>
            <p className="muted" style={{ fontSize: 13 }}>
              This evaluation studio contains confidential assignment data and live LLM credentials. Enter your{' '}
              <code>APP_ACCESS_TOKEN</code> to unlock.
            </p>
            <form onSubmit={handleUnlock}>
              <label className="label">Access Token</label>
              <input
                className="input mb-12"
                type="password"
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                placeholder="Paste APP_ACCESS_TOKEN"
              />
              <button type="submit" className="btn primary" style={{ width: '100%' }}>
                Unlock Studio
              </button>
            </form>
          </div>
        ) : error ? (
          <div className="alert fail">
            <strong>Connection issue:</strong> {error}
            <div className="mt-12">
              <button className="btn" onClick={bootstrap}>Retry</button>
            </div>
          </div>
        ) : !overview ? (
          <div className="card">Loading Es Magico Quality Studio...</div>
        ) : (
          <>
            {tab === 'overview' && (
              <OverviewTab
                overview={overview}
                onInspectInPlayground={(id) => {
                  setPlaygroundCaseId(id);
                  setTab('playground');
                }}
              />
            )}
            {tab === 'playground' && (
              <PlaygroundTab overview={overview} initialCaseId={playgroundCaseId} />
            )}
            {tab === 'runs' && (
              <RunsTab
                overview={overview}
                selectedRunId={selectedRunId}
                onSelectRun={setSelectedRunId}
                onOpenReview={(id) => {
                  setSelectedRunId(id);
                  setTab('review');
                }}
              />
            )}
            {tab === 'review' && (
              <ReviewTab selectedRunId={selectedRunId} onSelectRun={setSelectedRunId} />
            )}
          </>
        )}
      </main>
    </div>
  );
}
