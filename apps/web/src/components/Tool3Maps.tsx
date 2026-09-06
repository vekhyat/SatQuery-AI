import { useState } from 'react';
import type { ResultEnvelope } from '../lib/types';
import './tool3-maps.css';

const LABELS = { optical_only: 'Optical-only', sar_only: 'SAR-only', fused: 'Fused' };
type Layer = keyof typeof LABELS;
type LayerUrls = Record<Layer, string>;

export function tool3LayerUrls(result: ResultEnvelope | null): LayerUrls | null {
  if (!result || result.task !== 'optical_sar' || result.receipt.rejected) return null;
  const urls = result.facts.layer_urls;
  if (!urls || typeof urls !== 'object') return null;
  const record = urls as Record<string, unknown>;
  if (!Object.keys(LABELS).every(key => typeof record[key] === 'string' && (record[key] as string).startsWith('/') && !(record[key] as string).startsWith('//'))) return null;
  return record as LayerUrls;
}

function count(facts: Record<string, unknown>, layer: Layer, category: string): string {
  const layers = facts.layers as Record<string, Record<string, { pixels?: unknown }>> | undefined;
  const pixels = layers?.[layer]?.[category]?.pixels;
  return typeof pixels === 'number' && Number.isFinite(pixels) ? pixels.toLocaleString() : 'Unavailable';
}

export function Tool3Maps({ result, urls, busy }: { result: ResultEnvelope; urls: LayerUrls; busy: boolean }) {
  const [selected, select] = useState<Layer>('fused');
  const [failedUrl, setFailedUrl] = useState('');
  return <section className="tool3-maps" aria-label="Computed optical and SAR candidate maps" aria-busy={busy}>
    <div className="tool3-toolbar" role="group" aria-label="Candidate map selection">
      {(Object.keys(LABELS) as Layer[]).map(layer => <button key={layer} type="button" aria-pressed={selected === layer} disabled={busy} onClick={() => select(layer)}>{LABELS[layer]}</button>)}
      <a href={urls[selected]} download>{LABELS[selected]} PNG</a>
    </div>
    <div className="tool3-map-image">
      {failedUrl === urls[selected] ? <p role="status">This map is unavailable. Its uploaded scenes may have expired; upload and run again.</p>
        : <img key={urls[selected]} src={urls[selected]} alt={`${LABELS[selected]} water and built-up candidate map`} onError={() => setFailedUrl(urls[selected])} />}
    </div>
    <div className="tool3-map-caption" aria-live="polite">
      <span><i className="water" />Water candidates: {count(result.facts, selected, 'water')} pixels</span>
      <span><i className="builtup" />Built-up candidates: {count(result.facts, selected, 'builtup')} pixels</span>
      <span><i className="other" />Other / unclassified · transparent = nodata</span>
    </div>
    <p className="tool3-method-note">Threshold baseline · confidence not calibrated. All three maps use the same pixel grid.</p>
  </section>;
}
