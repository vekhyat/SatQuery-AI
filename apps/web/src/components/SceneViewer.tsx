import { useId, useMemo, useState, type ReactNode } from 'react';
import {
  Blend,
  ChevronsLeftRight,
  Columns2,
  Image as ImageIcon,
  ImageOff,
  ImagePlus,
  Minus,
  Plus,
  Radar,
  SquareDashed,
  SquareSplitHorizontal,
} from 'lucide-react';
import type { Mode, Scene } from '../lib/types';
import './scene-viewer.css';

export type SceneViewerProps = {
  scenes: Scene[];
  mode: Mode;
  showOverlay: boolean;
  rejected: boolean;
  busy: boolean;
  onOverlayChange: (value: boolean) => void;
};

type CompareView = 'side' | 'swipe';
type FusionView = 'optical' | 'sar' | 'fused';

const STAGE_ZOOM_MIN = 1;
const STAGE_ZOOM_MAX = 2.5;
const STAGE_ZOOM_STEP = 0.5;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

export function SceneViewer({
  scenes,
  mode,
  showOverlay,
  rejected,
  busy,
  onOverlayChange,
}: SceneViewerProps) {
  const id = useId();
  const [compareView, setCompareView] = useState<CompareView>('side');
  const [fusionView, setFusionView] = useState<FusionView>('optical');
  const [clip, setClip] = useState(50);
  const [blend, setBlend] = useState(50);
  const [zoom, setZoom] = useState(STAGE_ZOOM_MIN);

  const isDemo = scenes.length > 0 && scenes.every((scene) => scene.demo === true);
  const canOverlay = isDemo && !rejected && mode === 'change';
  const overlayOn = canOverlay && showOverlay;
  const hasPreview = scenes.some((scene) => Boolean(scene.preview));

  const changePair = useMemo(() => pickChangePair(scenes), [scenes]);
  const fusionPair = useMemo(() => pickFusionPair(scenes), [scenes]);
  const single = scenes[0];

  const showCompare = mode === 'change' && changePair !== null;
  const showFusion = mode === 'optical_sar' && fusionPair !== null;
  const captions = buildCaptions(scenes, mode, isDemo);

  const zoomOut = () => setZoom((value) => clamp(value - STAGE_ZOOM_STEP, STAGE_ZOOM_MIN, STAGE_ZOOM_MAX));
  const zoomIn = () => setZoom((value) => clamp(value + STAGE_ZOOM_STEP, STAGE_ZOOM_MIN, STAGE_ZOOM_MAX));

  if (scenes.length === 0) {
    return (
      <section className="scene-viewer" aria-label="Scene viewer">
        <div className="scene-viewer__empty">
          <ImagePlus size={22} strokeWidth={1.75} aria-hidden />
          <p>Add a GeoTIFF to begin</p>
          <span>Attach one optical or SAR file to inspect it here. Two aligned files unlock comparison.</span>
        </div>
      </section>
    );
  }

  return (
    <section className="scene-viewer" aria-label="Scene viewer" aria-busy={busy || undefined}>
      <div className="scene-viewer__toolbar">
        {showCompare ? (
          <div className="scene-viewer__tabs" aria-label="Change comparison">
            <ViewTab
              pressed={compareView === 'side'}
              onClick={() => setCompareView('side')}
              icon={<Columns2 size={15} strokeWidth={1.75} aria-hidden />}
            >
              Side by side
            </ViewTab>
            <ViewTab
              pressed={compareView === 'swipe'}
              onClick={() => setCompareView('swipe')}
              icon={<SquareSplitHorizontal size={15} strokeWidth={1.75} aria-hidden />}
            >
              Swipe
            </ViewTab>
          </div>
        ) : null}

        {showFusion ? (
          <div className="scene-viewer__tabs" aria-label="Optical and SAR display">
            <ViewTab
              pressed={fusionView === 'optical'}
              onClick={() => setFusionView('optical')}
              icon={<ImageIcon size={15} strokeWidth={1.75} aria-hidden />}
            >
              Optical
            </ViewTab>
            <ViewTab
              pressed={fusionView === 'sar'}
              onClick={() => setFusionView('sar')}
              icon={<Radar size={15} strokeWidth={1.75} aria-hidden />}
            >
              SAR
            </ViewTab>
            <ViewTab
              pressed={fusionView === 'fused'}
              onClick={() => setFusionView('fused')}
              icon={<Blend size={15} strokeWidth={1.75} aria-hidden />}
            >
              Blend
            </ViewTab>
          </div>
        ) : null}

        <div className="scene-viewer__toolbar-end">
          {busy ? (
            <p className="scene-viewer__busy" aria-live="polite">
              Working
            </p>
          ) : null}

          {hasPreview ? (
            <div className="scene-viewer__zoom" role="group" aria-label="Zoom">
              <button
                type="button"
                onClick={zoomOut}
                disabled={zoom <= STAGE_ZOOM_MIN}
                aria-label="Zoom out"
              >
                <Minus size={15} strokeWidth={1.75} aria-hidden />
              </button>
              <button
                type="button"
                onClick={zoomIn}
                disabled={zoom >= STAGE_ZOOM_MAX}
                aria-label="Zoom in"
              >
                <Plus size={15} strokeWidth={1.75} aria-hidden />
              </button>
            </div>
          ) : null}

          {canOverlay ? (
            <button
              type="button"
              className="scene-viewer__switch"
              role="switch"
              aria-checked={overlayOn}
              onClick={() => onOverlayChange(!showOverlay)}
            >
              <SquareDashed size={15} strokeWidth={1.75} aria-hidden />
              Finding mark
            </button>
          ) : null}
        </div>
      </div>

      {showCompare && changePair && compareView === 'side' ? (
        <div className="scene-viewer__pair" role="group" aria-label="Before and after scenes">
          <ScenePlate scene={changePair.before} zoom={zoom} showOverlay={false} />
          <ScenePlate scene={changePair.after} zoom={zoom} showOverlay={overlayOn} />
        </div>
      ) : null}

      {showCompare && changePair && compareView === 'swipe' ? (
        <SwipeStage
          before={changePair.before}
          after={changePair.after}
          clip={clip}
          zoom={zoom}
          overlay={overlayOn}
          rangeId={`${id}-swipe`}
          onClipChange={setClip}
        />
      ) : null}

      {showFusion && fusionPair && fusionView === 'optical' ? (
        <ScenePlate scene={fusionPair.optical} zoom={zoom} showOverlay={overlayOn} />
      ) : null}

      {showFusion && fusionPair && fusionView === 'sar' ? (
        <ScenePlate scene={fusionPair.sar} zoom={zoom} showOverlay={false} />
      ) : null}

      {showFusion && fusionPair && fusionView === 'fused' ? (
        <BlendStage
          optical={fusionPair.optical}
          sar={fusionPair.sar}
          blend={blend}
          zoom={zoom}
          overlay={overlayOn}
          rangeId={`${id}-blend`}
          onBlendChange={setBlend}
        />
      ) : null}

      {!showCompare && !showFusion && single ? (
        <ScenePlate scene={single} zoom={zoom} showOverlay={overlayOn} />
      ) : null}

      {captions.length > 0 ? (
        <div className="scene-viewer__captions">
          {captions.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function ScenePlate({
  scene,
  zoom,
  showOverlay,
}: {
  scene: Scene;
  zoom: number;
  showOverlay: boolean;
}) {
  return (
    <figure className="scene-viewer__plate">
      <SceneFrame scene={scene} zoom={zoom} showOverlay={showOverlay} />
      <figcaption className="scene-viewer__label">{formatPlateLabel(scene)}</figcaption>
    </figure>
  );
}

function SceneFrame({
  scene,
  zoom,
  showOverlay,
}: {
  scene: Scene;
  zoom: number;
  showOverlay: boolean;
}) {
  return (
    <div className="scene-viewer__frame">
      <div className="scene-viewer__scaler" style={{ transform: `scale(${zoom})` }}>
        <SceneMedia scene={scene} />
        {showOverlay && scene.preview ? <OverlayMark /> : null}
      </div>
    </div>
  );
}

function SceneMedia({ scene }: { scene: Scene }) {
  const side = compositeSide(scene);

  if (!scene.preview) {
    return <MissingPreview scene={scene} />;
  }

  if (side) {
    return (
      <div
        className="scene-viewer__media scene-viewer__media--composite"
        style={{
          backgroundImage: cssUrl(scene.preview),
          backgroundPosition: side === 'left' ? 'left center' : 'right center',
        }}
        role="img"
        aria-label={formatPlateLabel(scene)}
      />
    );
  }

  return (
    <img
      className="scene-viewer__photo"
      src={scene.preview}
      alt={formatPlateLabel(scene)}
      draggable={false}
    />
  );
}

function MissingPreview({ scene }: { scene: Scene }) {
  const filename = scene.asset?.original_name ?? scene.name;
  const meta = scene.asset?.metadata;
  const crs = meta?.crs?.trim() || 'Not recorded';
  const width = meta?.width;
  const height = meta?.height;
  const bands = meta?.band_count;
  const size =
    typeof width === 'number' && typeof height === 'number'
      ? `${width} × ${height} px`
      : 'Not recorded';
  const bandLabel =
    typeof bands === 'number' ? `${bands} ${bands === 1 ? 'band' : 'bands'}` : 'Not recorded';

  return (
    <div className="scene-viewer__missing">
      <ImageOff size={18} strokeWidth={1.75} aria-hidden />
      <p className="scene-viewer__missing-file">{filename}</p>
      <dl>
        <div>
          <dt>CRS</dt>
          <dd>{crs}</dd>
        </div>
        <div>
          <dt>Dimensions</dt>
          <dd>{size}</dd>
        </div>
        <div>
          <dt>Bands</dt>
          <dd>{bandLabel}</dd>
        </div>
      </dl>
      <p className="scene-viewer__missing-note">Preview unavailable; file can still be queried</p>
    </div>
  );
}

function OverlayMark() {
  return (
    <div className="scene-viewer__overlay" aria-hidden>
      <span className="scene-viewer__pin" data-finding-pin="" />
    </div>
  );
}

function SwipeStage({
  before,
  after,
  clip,
  zoom,
  overlay,
  rangeId,
  onClipChange,
}: {
  before: Scene;
  after: Scene;
  clip: number;
  zoom: number;
  overlay: boolean;
  rangeId: string;
  onClipChange: (value: number) => void;
}) {
  const clipRight = `${100 - clip}%`;

  return (
    <div className="scene-viewer__stage scene-viewer__swipe" role="group" aria-label="Swipe comparison">
      <SceneFrame scene={after} zoom={zoom} showOverlay={overlay} />
      <div className="scene-viewer__swipe-before" style={{ clipPath: `inset(0 ${clipRight} 0 0)` }}>
        <SceneFrame scene={before} zoom={zoom} showOverlay={false} />
      </div>
      <div className="scene-viewer__handle" style={{ left: `${clip}%` }} aria-hidden>
        <span className="scene-viewer__handle-knob">
          <ChevronsLeftRight size={14} strokeWidth={1.75} />
        </span>
      </div>
      <input
        id={rangeId}
        className="scene-viewer__clip-range"
        type="range"
        min={0}
        max={100}
        step={1}
        value={clip}
        aria-label="Swipe comparison"
        aria-valuetext={`${clip}% ${before.name}, ${100 - clip}% ${after.name}`}
        onChange={(event) => onClipChange(Number(event.target.value))}
      />
      <span className="scene-viewer__label scene-viewer__label--left">{formatPlateLabel(before)}</span>
      <span className="scene-viewer__label scene-viewer__label--right">{formatPlateLabel(after)}</span>
    </div>
  );
}

function BlendStage({
  optical,
  sar,
  blend,
  zoom,
  overlay,
  rangeId,
  onBlendChange,
}: {
  optical: Scene;
  sar: Scene;
  blend: number;
  zoom: number;
  overlay: boolean;
  rangeId: string;
  onBlendChange: (value: number) => void;
}) {
  const opticalOpacity = blend / 100;

  return (
    <div className="scene-viewer__blend">
      <div className="scene-viewer__stage scene-viewer__blend-stage" role="group" aria-label="Visual blend of optical and SAR">
        <SceneFrame scene={sar} zoom={zoom} showOverlay={false} />
        <div className="scene-viewer__blend-top" style={{ opacity: opticalOpacity }}>
          <SceneFrame scene={optical} zoom={zoom} showOverlay={overlay} />
        </div>
        <span className="scene-viewer__label scene-viewer__label--left">{formatPlateLabel(sar)}</span>
        <span className="scene-viewer__label scene-viewer__label--right">{formatPlateLabel(optical)}</span>
      </div>
      <div className="scene-viewer__blend-control">
        <label htmlFor={rangeId}>Visual blend · not analytical fusion</label>
        <input
          id={rangeId}
          className="scene-viewer__blend-range"
          type="range"
          min={0}
          max={100}
          step={1}
          value={blend}
          aria-valuetext={`${blend}% optical, ${100 - blend}% SAR`}
          onChange={(event) => onBlendChange(Number(event.target.value))}
        />
        <div className="scene-viewer__blend-ends">
          <span>SAR</span>
          <span>Optical</span>
        </div>
      </div>
    </div>
  );
}

function ViewTab({
  pressed,
  onClick,
  icon,
  children,
}: {
  pressed: boolean;
  onClick: () => void;
  icon: ReactNode;
  children: string;
}) {
  return (
    <button type="button" className="scene-viewer__tab" aria-pressed={pressed} onClick={onClick}>
      {icon}
      {children}
    </button>
  );
}

function pickChangePair(scenes: Scene[]): { before: Scene; after: Scene } | null {
  if (scenes.length < 2) {
    return null;
  }
  const before =
    scenes.find((scene) => scene.previewPosition === 'left') ??
    scenes[0];
  const after =
    scenes.find((scene) => scene !== before && scene.previewPosition === 'right') ??
    scenes.find((scene) => scene !== before) ??
    scenes[1];
  if (!before || !after) {
    return null;
  }
  return { before, after };
}

function pickFusionPair(scenes: Scene[]): { optical: Scene; sar: Scene } | null {
  if (scenes.length < 2) {
    return null;
  }
  const optical = scenes.find((scene) => scene.modality === 'optical') ?? scenes[0];
  const sar =
    scenes.find((scene) => scene !== optical && scene.modality === 'sar') ??
    scenes.find((scene) => scene !== optical) ??
    scenes[1];
  if (!optical || !sar) {
    return null;
  }
  return { optical, sar };
}

function compositeSide(scene: Scene): 'left' | 'right' | null {
  if (scene.previewPosition === 'left' || scene.previewPosition === 'right') {
    return scene.previewPosition;
  }
  return null;
}

function formatPlateLabel(scene: Scene): string {
  const date = formatSceneDate(scene.date);
  if (scene.name && date) {
    return `${scene.name} · ${date}`;
  }
  return scene.name || date || 'Scene';
}

function formatSceneDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) {
    return value;
  }
  const month = MONTHS[Number(match[2]) - 1];
  if (!month) {
    return value;
  }
  return `${Number(match[3])} ${month}`;
}

function buildCaptions(scenes: Scene[], mode: Mode, isDemo: boolean): string[] {
  const lines: string[] = [];
  if (mode === 'optical_sar' && isDemo) {
    lines.push('Illustrative SAR simulation');
  }
  for (const scene of scenes) {
    const note = scene.previewNote?.trim();
    if (note && !lines.includes(note)) {
      lines.push(note);
    }
  }
  return lines;
}

function cssUrl(src: string): string {
  return `url("${src.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}")`;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
