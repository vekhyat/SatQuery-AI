import { useState } from 'react';
import { Download } from 'lucide-react';
import { SceneViewer } from './SceneViewer';
import type { ResultEnvelope, Scene } from '../lib/types';
import './tool2-change-view.css';

type ViewMode = 'compare' | 'overlay' | 'mask';
type ArtifactKey = 'overlay' | 'semantic_mask_rgb' | 'binary_mask' | 'components';

type Tool2ViewModel = {
  caption: string | null;
  changedPixels: number | null;
  changedPercent: number | null;
  roadPercent: number | null;
  buildingPercent: number | null;
  physicalAreaM2: number | null;
  physicalAreaHectares: number | null;
  artifacts: Partial<Record<ArtifactKey, string>>;
};

const DOWNLOADS: Array<{ key: ArtifactKey; label: string }> = [
  { key: 'overlay', label: 'Overlay PNG' },
  { key: 'semantic_mask_rgb', label: 'Semantic mask PNG' },
  { key: 'binary_mask', label: 'Binary mask PNG' },
  { key: 'components', label: 'Components JSON' },
];

export function isTool2ChangeResult(result: ResultEnvelope | null): boolean {
  return Boolean(
    result &&
      result.task === 'change' &&
      !result.receipt.rejected &&
      result.tools.includes('change_mci_v1'),
  );
}

export function Tool2ChangeView({ result, scenes, busy }: { result: ResultEnvelope; scenes: Scene[]; busy: boolean }) {
  const [mode, setMode] = useState<ViewMode>('compare');
  const [failedArtifacts, setFailedArtifacts] = useState<Set<string>>(() => new Set());
  const view = tool2ChangeViewModel(result);
  const isNoChange = view.changedPixels === 0;
  const selectedArtifact = mode === 'overlay' ? view.artifacts.overlay : view.artifacts.semantic_mask_rgb;
  const selectedLabel = mode === 'overlay' ? 'Detected Change Overlay' : 'Semantic Change Mask';

  function markFailed(url: string) {
    setFailedArtifacts(current => new Set(current).add(url));
  }

  return <section className="tool2-change-view" aria-label="Change analysis evidence" aria-busy={busy}>
    <div className="tool2-change-view__toolbar" role="group" aria-label="Change evidence selection">
      <button type="button" aria-pressed={mode === 'compare'} disabled={busy} onClick={() => setMode('compare')}>Compare</button>
      <button type="button" aria-pressed={mode === 'overlay'} disabled={busy} onClick={() => setMode('overlay')}>Overlay</button>
      <button type="button" aria-pressed={mode === 'mask'} disabled={busy} onClick={() => setMode('mask')}>Semantic mask</button>
    </div>

    {mode === 'compare' ? <SceneViewer scenes={scenes} mode="change" showOverlay={false} rejected={false} busy={busy} onOverlayChange={() => undefined} />
      : <ArtifactImage url={selectedArtifact ?? null} label={selectedLabel} failed={selectedArtifact ? failedArtifacts.has(selectedArtifact) : false} onFailure={() => selectedArtifact && markFailed(selectedArtifact)} />}

    <div className="tool2-change-view__details">
      <div className="tool2-change-view__caption">
        <span>Model change description</span>
        <p>{view.caption ?? 'A model-generated change description is unavailable for this result.'}</p>
      </div>
      <dl className="tool2-change-view__stats">
        <div><dt>Changed</dt><dd>{formatPercent(view.changedPercent)}</dd></div>
        <div><dt>Changed pixels</dt><dd>{formatCount(view.changedPixels)}</dd></div>
        {!isNoChange && view.roadPercent !== null ? <div><dt>Road change</dt><dd>{formatPercent(view.roadPercent)}</dd></div> : null}
        {!isNoChange && view.buildingPercent !== null ? <div><dt>Building change</dt><dd>{formatPercent(view.buildingPercent)}</dd></div> : null}
        {view.physicalAreaM2 !== null ? <div><dt>Estimated changed area</dt><dd>{formatArea(view.physicalAreaM2, view.physicalAreaHectares)}</dd></div> : null}
      </dl>
    </div>

    {mode === 'mask' ? <div className="tool2-change-view__legend" aria-label="Semantic change legend">
      <span><i className="unchanged" />Unchanged/background</span>
      <span><i className="road" />Road change</span>
      <span><i className="building" />Building change</span>
    </div> : null}

    {isNoChange ? <p className="tool2-change-view__no-change" role="status">No detected change.</p> : null}
    <div className="tool2-change-view__downloads" aria-label="Download change evidence">
      {DOWNLOADS.flatMap(({ key, label }) => {
        const url = view.artifacts[key];
        return url ? [<a key={key} href={url} download><Download size={14} />{label}</a>] : [];
      })}
    </div>
  </section>;
}

function ArtifactImage({ url, label, failed, onFailure }: { url: string | null; label: string; failed: boolean; onFailure: () => void }) {
  if (!url || failed) return <div className="tool2-change-view__artifact-unavailable" role="status">This evidence item is no longer available.</div>;
  return <div className="tool2-change-view__image"><img src={url} alt={label} onError={onFailure} /></div>;
}

export function tool2ChangeViewModel(result: ResultEnvelope): Tool2ViewModel {
  const facts = result.facts;
  const caption = record(facts.caption);
  const classes = record(facts.classes);
  const road = record(classes.road_change);
  const building = record(classes.building_change);
  const artifacts = record(facts.artifacts);
  return {
    caption: stringValue(caption.text) ?? stringValue(facts.summary),
    changedPixels: nonNegativeNumber(facts.changed_pixels),
    changedPercent: nonNegativeNumber(facts.changed_percent),
    roadPercent: nonNegativeNumber(road.percent_of_valid_pixels),
    buildingPercent: nonNegativeNumber(building.percent_of_valid_pixels),
    physicalAreaM2: nonNegativeNumber(facts.physical_area_m2),
    physicalAreaHectares: nonNegativeNumber(facts.physical_area_hectares),
    artifacts: {
      overlay: safeArtifactUrl(artifacts.overlay),
      semantic_mask_rgb: safeArtifactUrl(artifacts.semantic_mask_rgb),
      binary_mask: safeArtifactUrl(artifacts.binary_mask),
      components: safeArtifactUrl(artifacts.components),
    },
  };
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' ? value as Record<string, unknown> : {};
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function nonNegativeNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

function safeArtifactUrl(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return undefined;
  const rawPath = value.split(/[?#]/, 1)[0];
  if (rawPath.split('/').some(segment => {
    try {
      const decoded = decodeURIComponent(segment);
      return decoded === '.' || decoded === '..' || decoded.includes('\\');
    } catch {
      return true;
    }
  })) return undefined;
  try {
    const url = new URL(value, window.location.origin);
    if (url.origin !== window.location.origin || url.search || url.hash || url.pathname.split('/').some(segment => segment === '.' || segment === '..')) return undefined;
    return url.pathname;
  } catch {
    return undefined;
  }
}

function formatCount(value: number | null): string {
  return value === null ? 'Unavailable' : value.toLocaleString();
}

function formatPercent(value: number | null): string {
  return value === null ? 'Unavailable' : `${value.toFixed(2)}%`;
}

function formatArea(squareMetres: number, hectares: number | null): string {
  const base = `${squareMetres.toLocaleString()} m²`;
  return hectares === null ? base : `${base} (${hectares.toFixed(2)} ha)`;
}
