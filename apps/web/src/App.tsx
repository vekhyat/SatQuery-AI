import { useEffect, useRef, useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';
import { ArrowRight, ArrowUpRight, BookOpen, Check, ChevronDown, CircleHelp, CirclePlus, FlaskConical, GitBranch, Info, Layers2, Menu, Plus, Trash2, UploadCloud, X, AlertTriangle } from 'lucide-react';
import { BorderBeam } from 'border-beam';
import { ThinkingOrb } from 'thinking-orbs';
import { FindingLeader } from './components/FindingLeader';
import { Receipt } from './components/Receipt';
import { SceneViewer } from './components/SceneViewer';
import { Tool2ChangeView, isTool2ChangeResult } from './components/Tool2ChangeView';
import { Tool3Maps, tool3LayerUrls } from './components/Tool3Maps';
import { checkHealth, queryScenes, uploadScene } from './lib/api';
import { createDemoResult, createDemoScenes } from './lib/demo';
import {
  demoInvestigation,
  MODE_NAMES,
  MODES,
  QUESTIONS,
  TITLES,
  questionSuggestions,
  sceneRoleLabel,
  type Investigation,
  type Pending,
} from './lib/notebook';
import type { Mode, ResultEnvelope } from './lib/types';

export default function App() {
  const [investigations, setInvestigations] = useState<Investigation[]>(() => [demoInvestigation()]);
  const [activeId, setActiveId] = useState('demo');
  const [busy, setBusy] = useState(false);
  const [activity, setActivity] = useState('');
  const [error, setError] = useState('');
  const [health, setHealth] = useState<boolean | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [pending, setPending] = useState<Pending[]>([]);
  const [showOverlay, setShowOverlay] = useState(true);
  const [helpOpen, setHelpOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [queryFocused, setQueryFocused] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const inputRef = useRef<HTMLInputElement>(null);
  const queryRef = useRef<HTMLInputElement>(null);
  const current = investigations.find(item => item.id === activeId)!;
  const isDemo = current.source === 'demo';
  const slots = isDemo ? current.mode === 'single_image' ? 1 : 2 : 2;
  const actualCount = current.scenes.length;
  const result = current.result;
  const viewMode: Mode = isDemo ? current.mode : result && result.task !== 'reject' ? result.task : actualCount < 2 ? 'single_image' : 'change';
  const rejected = result?.receipt.rejected ?? false;
  const hasStub = result?.receipt.trace.some(s => s.status === 'stub') ?? false;
  const isTool3Specialist = !isDemo && result?.task === 'optical_sar' && !result.receipt.rejected && result.tools.includes('optical_sar_v1');
  const isTool2Specialist = !isDemo && isTool2ChangeResult(result);
  const tool3Maps = isTool3Specialist ? tool3LayerUrls(result) : null;
  const dirtyQuestion = !!result && current.question !== current.submittedQuestion;
  const showCallout = isDemo && !rejected && showOverlay && !!result && current.mode === 'change';
  const routedLabel = result && result.task !== 'reject' ? MODE_NAMES[result.task] : null;

  useEffect(() => { void checkHealth().then(setHealth).catch(() => setHealth(false)); const query = window.matchMedia('(prefers-reduced-motion: reduce)'); const handler = () => setReducedMotion(query.matches); query.addEventListener('change', handler); return () => query.removeEventListener('change', handler); }, []);
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== 'Escape' || busy) return;
      setHelpOpen(false);
      setUploadOpen(false);
      setSidebarOpen(false);
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [busy]);

  function update(patch: Partial<Investigation>) { setInvestigations(items => items.map(item => item.id === activeId ? { ...item, ...patch } : item)); }
  function newInvestigation(openUploads = false) {
    if (busy) return;
    const id = crypto.randomUUID(); const number = investigations.filter(i => i.source === 'local').length + 1;
    setInvestigations(items => [...items, { id, title: `Investigation ${number}`, source: 'local', mode: 'single_image', question: '', scenes: [], result: null }]);
    setActiveId(id); setError(''); setPending([]); setUploadOpen(true); setSidebarOpen(false); setShowOverlay(false);
  }
  function selectInvestigation(id: string) { if (busy) return; setActiveId(id); setError(''); setPending([]); setUploadOpen(false); setSidebarOpen(false); setShowOverlay(id === 'demo'); }
  function selectMode(mode: Mode) {
    if (busy || mode === current.mode) return;
    update({
      mode,
      question: QUESTIONS[mode],
      scenes: isDemo ? createDemoScenes(mode) : current.scenes,
      result: isDemo ? createDemoResult(mode) : null,
      submittedQuestion: isDemo ? QUESTIONS[mode] : undefined,
    });
    setPending([]); setError(''); setShowOverlay(isDemo && mode === 'change');
  }
  function addScenes() { if (isDemo) newInvestigation(true); else { setUploadOpen(true); setSidebarOpen(true); } }
  function queueFiles(files: FileList | File[] | null) {
    if (!files || busy) return;
    const chosen = Array.from(files);
    if (chosen.some(f => !/\.tiff?$/i.test(f.name))) { setError('Choose GeoTIFF files (.tif or .tiff). Images such as JPG and PNG do not contain the required geospatial metadata.'); return; }
    if (chosen.some(f => f.size > 100 * 1024 * 1024)) { setError('Each GeoTIFF must be 100 MiB or smaller. Choose a smaller scene and try again.'); return; }
    if (chosen.length + pending.length + actualCount > slots) { setError('An investigation supports up to two scenes. Remove an attached or queued scene before adding more.'); return; }
    setError(''); setPending(items => [...items, ...chosen.map(file => ({ id: crypto.randomUUID(), file, modality: 'auto' as Pending['modality'], date: '' }))]);
  }
  async function attachScenes() {
    if (!pending.length || busy) return;
    setBusy(true); setError(''); let attached = [...current.scenes];
    try {
      for (const item of pending) {
        setActivity(`Validating ${item.file.name}…`);
        const asset = await uploadScene(item.file, item.modality, item.date || undefined);
        let preview: string | null = null;
        try { setActivity(`Preparing ${item.file.name} preview…`); const response = await fetch(`/api/preview/${encodeURIComponent(asset.asset_id)}`, { signal: AbortSignal.timeout(15000) }); if (response.ok) preview = URL.createObjectURL(await response.blob()); } catch { /* Validated assets can be queried without a preview. */ }
        attached = [...attached, { id: asset.asset_id, name: asset.original_name, date: asset.metadata.acquisition_date ?? '', modality: asset.metadata.modality, preview, asset, previewNote: preview ? 'Display stretch; original pixels are used by the API.' : 'Preview unavailable; validated file can still be queried.' }];
        if (attached.length === 2 && attached.every(scene => scene.modality === 'optical' && scene.date)) attached.sort((a, b) => a.date.localeCompare(b.date));
        if (attached.length === 2 && attached.some(scene => scene.modality === 'sar') && attached.some(scene => scene.modality === 'optical')) attached.sort((a, b) => Number(a.modality === 'sar') - Number(b.modality === 'sar'));
        update({ scenes: attached, result: null }); setPending(items => items.filter(p => p.id !== item.id)); setHealth(true);
      }
      setUploadOpen(false);
    } catch (err) { setError(err instanceof Error ? err.message : 'The upload failed. Check the API connection and try again.'); void checkHealth().then(setHealth).catch(() => setHealth(false)); }
    finally { setBusy(false); setActivity(''); }
  }
  async function runQuery(event?: FormEvent) {
    event?.preventDefault(); if (busy) return;
    const question = current.question.trim();
    if (!question) { setError('Write a question about your scenes first.'); queryRef.current?.focus(); return; }
    if (!actualCount || actualCount > 2) { setError('Attach one or two GeoTIFF scenes before asking. The router will select the analysis from your files and question.'); setUploadOpen(true); setSidebarOpen(true); return; }
    setError(''); setBusy(true); setActivity(isDemo ? 'Loading the prepared demonstration…' : 'Waiting for validation, routing, and the tool response…');
    update({ result: null });
    try {
      let next: ResultEnvelope;
      if (isDemo) {
        await new Promise(resolve => setTimeout(resolve, 750));
        next = createDemoResult(current.mode);
        if (question.toLowerCase().replace(/[?.]/g, '') !== QUESTIONS[current.mode].toLowerCase().replace(/[?.]/g, '')) {
          next = createDemoResult(current.mode, true);
          next.answer_text = 'This demo only answers the suggested question. Use your own GeoTIFFs to submit another question to the API.';
          next.receipt.reason = next.answer_text;
        }
      } else {
        next = await queryScenes(current.scenes.map(scene => scene.asset!.asset_id), question); setHealth(true);
      }
      update({ result: next, submittedQuestion: current.question, ...(next.task !== 'reject' && !isDemo ? { mode: next.task } : {}) }); setShowOverlay(isDemo && !next.receipt.rejected && current.mode === 'change');
    } catch (err) { setError(err instanceof Error ? err.message : 'The query failed. Check the API and try again.'); void checkHealth().then(setHealth).catch(() => setHealth(false)); }
    finally { setBusy(false); setActivity(''); }
  }
  function demoReject() { update({ result: createDemoResult(current.mode, true), submittedQuestion: current.question }); setShowOverlay(false); }

  const emptyLive = !isDemo && actualCount === 0;
  const uploadPanel = uploadOpen ? (
    <section className={'upload-panel' + (emptyLive ? ' in-workspace' : '')} aria-label="Attach GeoTIFF scenes">
      <div className="upload-panel-heading">
        <div>
          <h2>Attach scenes</h2>
          <p>One or two GeoTIFFs. Dated optical pairs must share a CRS and pixel grid.</p>
        </div>
        <button className="icon-button" type="button" disabled={busy} aria-label="Close upload panel" onClick={() => setUploadOpen(false)}><X size={19} /></button>
      </div>
      <input ref={inputRef} className="sr-only" type="file" accept=".tif,.tiff" multiple aria-label="Choose GeoTIFF files" disabled={busy} onChange={(e: ChangeEvent<HTMLInputElement>) => { queueFiles(e.target.files); e.target.value = ''; }} />
      <button className="dropzone" type="button" disabled={busy || actualCount + pending.length >= slots} onClick={() => inputRef.current?.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!busy && actualCount + pending.length < slots) queueFiles(e.dataTransfer.files); }}>
        <UploadCloud size={emptyLive ? 32 : 22} strokeWidth={1.5} /><span><strong>{emptyLive ? 'Add scenes' : 'Drop GeoTIFFs, or browse'}</strong><small>{emptyLive ? 'Drop GeoTIFFs here, or browse · one or two files · 100 MiB each' : `${Math.max(0, slots - actualCount - pending.length)} slots · 100 MiB each`}</small></span>
      </button>
      {pending.map(item => <div className="pending-file" key={item.id}><span title={item.file.name}>{item.file.name}<small>{(item.file.size / 1024 / 1024).toFixed(1)} MiB</small></span><label>Modality<select aria-label="Modality" value={item.modality} disabled={busy} onChange={e => setPending(ps => ps.map(p => p.id === item.id ? { ...p, modality: e.target.value as Pending['modality'] } : p))}><option value="auto">Auto-detect</option><option value="optical">Optical</option><option value="sar">SAR</option></select></label><label>Acquisition date<input type="date" value={item.date} disabled={busy} onChange={e => setPending(ps => ps.map(p => p.id === item.id ? { ...p, date: e.target.value } : p))} /></label><button className="icon-button" type="button" disabled={busy} aria-label={`Remove queued ${item.file.name}`} onClick={() => setPending(ps => ps.filter(p => p.id !== item.id))}><Trash2 size={16} /></button></div>)}
      {error && <p className="upload-error" role="alert">{error}</p>}
      <div className="upload-actions"><button className="button primary" type="button" disabled={!pending.length || busy} onClick={attachScenes}>{busy ? 'Validating…' : 'Validate and attach'}<ArrowRight size={16} /></button></div>
    </section>
  ) : null;

  return <div className="app-shell">
    <a className="skip-link" href="#workspace">Skip to investigation</a>
    <header className="app-header">
      <div className="brand">
        <button className="icon-button mobile-menu" type="button" aria-label="Investigations" aria-expanded={sidebarOpen} aria-controls="investigations-panel" onClick={() => setSidebarOpen(!sidebarOpen)}><Menu size={21} /><span className="mobile-menu-label">Investigations</span></button>
        <img src="/satquery.svg" width="48" height="44" alt="" /><span>SatQuery <b>AI</b></span>
        <span className="brand-divider" /><span className="product-label">Investigation notebook</span>
      </div>
      <div className="header-actions">
        <span className={'connection ' + (health ? 'online' : '')} title={health ? 'Local API connected' : 'Start the local SatQuery server to query your own scenes'}><i />{health === null ? 'Checking API' : health ? 'API connected' : 'API offline'}</span>
        {isDemo && <span className="demo-mark"><FlaskConical size={14} />Illustrative data</span>}
        <button className={'icon-button ' + (helpOpen ? 'active' : '')} type="button" aria-label="How SatQuery works" aria-expanded={helpOpen} onClick={() => setHelpOpen(!helpOpen)}><CircleHelp size={20} /></button>
      </div>
    </header>
    <div className="app-body">
      <aside id="investigations-panel" className={'sidebar ' + (sidebarOpen ? 'is-open' : '')} aria-label="Investigations and attached scenes">
        <div className="sidebar-title">Investigations <span>{investigations.length.toString().padStart(2, '0')}</span></div>
        <nav className="investigation-list">{investigations.map(item => <button key={item.id} className={'investigation ' + (activeId === item.id ? 'selected' : '')} type="button" aria-current={activeId === item.id ? 'true' : undefined} disabled={busy} onClick={() => selectInvestigation(item.id)}><BookOpen size={19} strokeWidth={1.6} /><span>{item.title}</span>{item.source === 'demo' && <small>DEMO</small>}</button>)}</nav>
        <button className="new-investigation" type="button" onClick={() => newInvestigation()} disabled={busy}><CirclePlus size={21} strokeWidth={1.5} />New investigation</button>
        <div className="sidebar-rule" />
        <div className="sidebar-title">Attached scenes <span>{actualCount} / {slots}</span></div>
        <div className="scene-list">{current.scenes.map((scene, index) => <article className="scene-item" key={scene.id}>
          {scene.preview ? <div className="scene-thumbnail" role="img" aria-label={`${scene.demo ? 'Illustrative ' : ''}${scene.modality} scene ${index + 1}`} style={{ backgroundImage: `url("${scene.preview}")`, backgroundPosition: scene.previewPosition ?? 'center', backgroundSize: scene.previewPosition ? '200% 100%' : 'cover' }} /> : <div className="scene-thumbnail no-preview"><Layers2 size={30} /><span>GeoTIFF</span></div>}
          <div className="scene-caption"><strong>{sceneRoleLabel(scene, index, viewMode)}</strong><span>{scene.date ? new Date(scene.date + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : 'Date unknown'}</span>{!isDemo && <button className="icon-button remove-scene" type="button" disabled={busy} aria-label={`Remove ${scene.name}`} onClick={() => { if (scene.preview?.startsWith('blob:')) URL.revokeObjectURL(scene.preview); update({ scenes: current.scenes.filter(s => s.id !== scene.id), result: null }); }}><X size={14} /></button>}</div>
          <details className="scene-metadata"><summary><span>{scene.asset?.original_name || 'Scene metadata'}</span><ChevronDown size={12} /></summary><dl><dt>Source</dt><dd>{isDemo ? 'Generated demo imagery' : 'Uploaded GeoTIFF'}</dd><dt>Modality</dt><dd>{scene.modality}</dd>{scene.asset && <><dt>CRS</dt><dd>{scene.asset.metadata.crs}</dd><dt>Dimensions</dt><dd>{scene.asset.metadata.width} × {scene.asset.metadata.height}</dd><dt>Bands</dt><dd>{scene.asset.metadata.band_count}</dd><dt>Resolution</dt><dd>{scene.asset.metadata.resolution.join(' × ')} CRS units</dd><dt>Bounds</dt><dd>{Object.entries(scene.asset.metadata.bounds).map(([key, value]) => `${key}: ${value}`).join(', ')}</dd><dt>Expires</dt><dd>{new Date(scene.asset.expires_at).toLocaleString()}</dd></>}</dl>{scene.asset?.warnings.map((w, i) => <p key={i}>{w}</p>)}<p>{scene.previewNote}</p></details>
        </article>)}</div>
        {!actualCount && !emptyLive && !uploadOpen && <div className="empty-scenes"><Layers2 size={28} strokeWidth={1.4} /><p>Attach a GeoTIFF to begin.</p><span>One scene, a dated pair, or optical + SAR.</span></div>}
        {!emptyLive && uploadPanel}
        <div className="sidebar-bottom">{isDemo && <label className="demo-picker">Demo example<select aria-label="Load demo example" value={current.mode} onChange={e => selectMode(e.target.value as Mode)} disabled={busy}><option value="change">River change · two dates</option><option value="single_image">Land cover · one scene</option><option value="optical_sar">Sensor comparison · two scenes</option></select></label>}<button className="button upload-button" type="button" disabled={busy} onClick={addScenes}><UploadCloud size={21} strokeWidth={1.5} />Add scenes <Plus size={15} /></button><p>GeoTIFF · up to 100 MiB per file</p></div>
      </aside>
      <main id="workspace" className="workspace">
        <div className="workspace-heading"><h1>{isDemo ? TITLES[current.mode] : current.submittedQuestion || 'What do you want to explore?'}</h1>{isDemo && <button className="text-button use-scenes" type="button" onClick={addScenes} disabled={busy}>Use my scenes <ArrowUpRight size={15} /></button>}</div>
        {helpOpen && <section className="help-panel"><div><p className="help-title">From question to evidence.</p><p>Attach one or two GeoTIFFs and ask a question. The router selects the analysis from your files. Open the receipt to inspect each step.</p><p><strong>Illustrative data</strong> is a prepared example. Your own scenes call the local API. Optical + SAR produces threshold-based candidate maps from named multispectral bands and calibrated radar. Single-image and change tools are still stubs.</p></div><button className="icon-button" type="button" aria-label="Close help" onClick={() => setHelpOpen(false)}><X size={18} /></button></section>}
        <form className="query-form" onSubmit={runQuery}>
          <BorderBeam className="query-beam" size="line" theme="light" colorVariant="sunset" strength={reducedMotion ? 0 : busy ? 0.65 : queryFocused ? 0.25 : 0} active={!reducedMotion && (queryFocused || busy)}>
            <div className="query-input-wrap"><label className="sr-only" htmlFor="question">Question about your satellite scenes</label><input id="question" ref={queryRef} value={current.question} maxLength={500} disabled={busy} onFocus={() => setQueryFocused(true)} onBlur={() => setQueryFocused(false)} onChange={e => update({ question: e.target.value })} placeholder="Ask a question about your scenes…" /><button className="ask-button" type="submit" disabled={busy || !current.question.trim() || !actualCount}>{busy ? <><ThinkingOrb state="connecting" size={20} paused={reducedMotion} />Working…</> : <>Ask SatQuery<ArrowRight size={23} strokeWidth={1.5} /></>}</button></div>
          </BorderBeam>
        </form>
        {emptyLive && (uploadOpen ? uploadPanel : (
          <button className="attach-prompt" type="button" disabled={busy} onClick={() => setUploadOpen(true)} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); setUploadOpen(true); queueFiles(e.dataTransfer.files); }}>
            <UploadCloud size={32} strokeWidth={1.5} />
            <span className="attach-prompt-copy"><strong>Add scenes</strong><small>Drop GeoTIFFs here, or browse · one or two files · 100 MiB each</small></span>
            <Plus size={22} />
          </button>
        ))}
        {!isDemo && actualCount > 0 && <div className="question-suggestions"><span>Try asking</span>{questionSuggestions(current.scenes).map(mode => <button className="text-button" type="button" disabled={busy} key={mode} onClick={() => { update({ question: QUESTIONS[mode] }); queryRef.current?.focus(); }}>{mode === 'single_image' ? 'Describe land cover' : mode === 'change' ? 'What changed?' : 'Compare optical + SAR'}<ArrowUpRight size={12} /></button>)}</div>}
        {!emptyLive && <div className={'mode-bar' + (result ? ' has-result' : '')}>
          {rejected ? <p className="route-status">These inputs could not be analysed</p> : routedLabel ? <p className="route-status"><GitBranch size={13} />Routed to {routedLabel}</p> : <p className="route-status idle">The router chooses after you ask</p>}
          <div className="route-indicators" aria-label="Router-selected analysis mode">{MODES.map(mode => <span key={mode} className={result?.task === mode ? 'selected' : ''}>{MODE_NAMES[mode]}{result?.task === mode && <Check size={13} />}</span>)}</div>
        </div>}
        <div id="analysis-panel">
          {error && !uploadOpen && <div className="error-banner" role="alert"><AlertTriangle size={19} /><div><strong>We couldn’t complete that step.</strong><p>{error}</p>{health === false && !isDemo && <button className="text-button" type="button" onClick={() => { void checkHealth().then(setHealth); }}>Recheck API connection</button>}</div><button className="icon-button" type="button" aria-label="Dismiss error" onClick={() => setError('')}><X size={16} /></button></div>}
          {busy && <div className="activity" role="status"><ThinkingOrb state="connecting" size={20} paused={reducedMotion} /><span>{activity}</span></div>}
          {!emptyLive && <div className={'evidence-stack' + (showCallout ? ' has-callout' : '')}>
            <FindingLeader active={showCallout} />
            {tool3Maps && result ? <Tool3Maps key={tool3Maps.fused} result={result} urls={tool3Maps} busy={busy} />
              : isTool2Specialist && result ? <Tool2ChangeView result={result} scenes={current.scenes} busy={busy} />
                : <SceneViewer scenes={current.scenes} mode={viewMode} showOverlay={showOverlay && !!result && !rejected} rejected={rejected} busy={busy} onOverlayChange={setShowOverlay} />}
            {result || busy ? (
              <section className={'answer-panel ' + (rejected ? 'answer-rejected' : '')} aria-label="Analysis answer" aria-live="polite">
                <div className="answer-icon">{rejected ? <AlertTriangle size={21} /> : <Check size={21} />}</div>
                <div className="answer-content">
                  <div className="answer-title">
                    <h2>{rejected ? 'These inputs cannot be analysed' : isDemo ? 'Illustrative result' : hasStub ? 'Inputs validated. Analysis not connected.' : 'Analysis result'}</h2>
                  </div>
                  <p>{result ? rejected ? result.receipt.reason || result.answer_text : result.answer_text : 'The response will appear once the request completes.'}{showCallout && <span className="finding-anchor" data-finding-target="" />}</p>
                  {dirtyQuestion && <small className="stale-notice">This result belongs to your previous question. Run the updated question to refresh it.</small>}
                  {result?.warnings.length ? <details className="warnings"><summary><Info size={14} />{result.warnings.length} {result.warnings.length === 1 ? 'note' : 'notes'} about this result<ChevronDown size={13} /></summary><ul>{result.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul></details> : null}
                </div>
              </section>
            ) : null}
          </div>}
          <Receipt key={current.id + current.mode + String(result?.receipt.rejected)} result={result} demo={isDemo} busy={busy} question={current.submittedQuestion ?? ''} />
          <footer className="workspace-footer"><span>SatQuery AI <span className="footer-dot">·</span> SIH26167</span>{isDemo ? <button className="text-button" type="button" disabled={busy} onClick={demoReject}>Try an incompatible pair <ArrowUpRight size={13} /></button> : <span>Session stays in this browser tab</span>}</footer>
        </div>
      </main>
    </div>
  </div>;
}
