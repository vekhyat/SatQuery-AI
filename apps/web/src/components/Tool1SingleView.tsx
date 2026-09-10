import { useEffect, useState } from 'react';
import { Download, Layers2 } from 'lucide-react';
import type { ResultEnvelope, Scene } from '../lib/types';
import './tool1-single-view.css';

type ViewMode = 'scene' | 'overlay';

export function isTool1SingleResult(result: ResultEnvelope | null): boolean {
  return Boolean(
    result &&
      result.task === 'single_image' &&
      !result.receipt.rejected &&
      result.tools.includes('single_image_v1')
  );
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

export function Tool1SingleView({
  result,
  scene,
  busy,
}: {
  result: ResultEnvelope;
  scene?: Scene;
  busy: boolean;
}) {
  const facts = result.facts || {};
  const overlayUrl =
    safeArtifactUrl(result.overlay.file) ??
    safeArtifactUrl((facts.artifacts as Record<string, unknown> | undefined)?.overlay);
  const [mode, setMode] = useState<ViewMode>(overlayUrl ? 'overlay' : 'scene');
  const [failedOverlay, setFailedOverlay] = useState(false);

  useEffect(() => {
    setFailedOverlay(false);
  }, [overlayUrl]);

  const labels = Array.isArray(facts.labels) ? (facts.labels as string[]) : [];
  const hasWater = Boolean(facts.water);
  const hasVegetation = Boolean(facts.vegetation);
  const hasBuiltUp = Boolean(facts.built_up);
  const isPackA = Boolean(facts.is_pack_a);

  return (
    <section className="tool1-single-view" aria-label="Single-image land cover evidence" aria-busy={busy}>
      <div className="tool1-toolbar" role="group" aria-label="Evidence display selection">
        <button
          type="button"
          aria-pressed={mode === 'scene'}
          disabled={busy}
          onClick={() => setMode('scene')}
        >
          Scene
        </button>
        <button
          type="button"
          aria-pressed={mode === 'overlay'}
          disabled={busy || !overlayUrl}
          onClick={() => setMode('overlay')}
        >
          Land-cover overlay
        </button>
        {overlayUrl && (
          <a
            className="tool1-download-link"
            href={overlayUrl}
            download="landcover_overlay.png"
            aria-disabled={busy}
            tabIndex={busy ? -1 : undefined}
            onClick={event => {
              if (busy) event.preventDefault();
            }}
          >
            <Download size={14} />
            Overlay PNG
          </a>
        )}
      </div>

      <div className="tool1-stage">
        {mode === 'scene' ? (
          scene?.preview ? (
            <img className="tool1-image" src={scene.preview} alt={scene.name || 'Uploaded scene'} />
          ) : (
            <div className="tool1-missing-preview">
              <Layers2 size={36} strokeWidth={1.5} />
              <p>Original scene preview</p>
              <span>{scene?.asset?.original_name || 'Validated GeoTIFF loaded'}</span>
            </div>
          )
        ) : overlayUrl && !failedOverlay ? (
          <img
            key={overlayUrl}
            className="tool1-image"
            src={overlayUrl}
            alt="Single image land cover overlay"
            onError={() => setFailedOverlay(true)}
          />
        ) : (
          <div className="tool1-missing-preview">
            <Layers2 size={36} strokeWidth={1.5} />
            <p>Overlay unavailable</p>
            <span>The source asset may have expired or is being regenerated.</span>
          </div>
        )}
      </div>

      <div className="tool1-details">
        <div className="tool1-caption">
          <span>Land-cover detection summary</span>
          <p>{result.answer_text}</p>
        </div>

        <div className="tool1-badges" aria-label="Detected feature classes">
          <span className={`tool1-badge water ${hasWater ? 'active' : 'inactive'}`}>
            <i /> Water {hasWater ? 'detected' : 'not detected'}
          </span>
          <span className={`tool1-badge vegetation ${hasVegetation ? 'active' : 'inactive'}`}>
            <i /> Vegetation {hasVegetation ? 'detected' : 'not detected'}
          </span>
          <span className={`tool1-badge builtup ${hasBuiltUp ? 'active' : 'inactive'}`}>
            <i /> Built-up {hasBuiltUp ? 'detected' : 'not detected'}
          </span>
          {isPackA && hasWater && hasVegetation && hasBuiltUp && (
            <span className="tool1-badge pack-a active">
              <i /> Pack A card verified
            </span>
          )}
        </div>

        {labels.length > 0 && (
          <div className="tool1-labels-list">
            <strong>Classified labels:</strong> {labels.join(', ')}
          </div>
        )}

        <p className="tool1-method-note">
          Multispectral NDWI, NDVI, and brightness indices. Visual overlay highlights water (blue),
          vegetation (green), and built-up structures (red).
        </p>
      </div>
    </section>
  );
}
