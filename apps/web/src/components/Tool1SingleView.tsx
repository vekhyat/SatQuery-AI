import { useState } from 'react';
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

export function Tool1SingleView({
  result,
  scene,
  busy,
}: {
  result: ResultEnvelope;
  scene?: Scene;
  busy: boolean;
}) {
  const [mode, setMode] = useState<ViewMode>('overlay');
  const [failedOverlay, setFailedOverlay] = useState(false);

  const facts = result.facts || {};
  const labels = Array.isArray(facts.labels) ? (facts.labels as string[]) : [];
  const hasWater = Boolean(facts.water);
  const hasVegetation = Boolean(facts.vegetation);
  const hasBuiltUp = Boolean(facts.built_up);
  const isPackA = Boolean(facts.is_pack_a);
  const overlayUrl = result.overlay.file || (facts.artifacts as Record<string, string> | undefined)?.overlay;

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
          <a className="tool1-download-link" href={overlayUrl} download="landcover_overlay.png">
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
          {isPackA && (
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
