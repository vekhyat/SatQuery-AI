export type Mode = 'single_image' | 'change' | 'optical_sar';

export type Task = Mode | 'reject';

export type Modality = 'optical' | 'sar' | 'unknown';

export type ModalityHint = 'auto' | 'optical' | 'sar';

export type OverlayType = 'heatmap' | 'change_mask' | 'none';

export type ProvenanceSource =
  | 'user'
  | 'tag'
  | 'band_description'
  | 'band_count_heuristic'
  | 'unknown';

export type AffineTransform = [
  number,
  number,
  number,
  number,
  number,
  number,
];

export type PixelResolution = [number, number];

export type Bounds = {
  left: number;
  bottom: number;
  right: number;
  top: number;
};

export type ValueProvenance = {
  source: ProvenanceSource;
  detected_value: string | null;
  detected_source: string | null;
};

export type MetadataProvenance = {
  modality: ValueProvenance;
  acquisition_date: ValueProvenance;
};

export type RasterMetadata = {
  driver: string;
  width: number;
  height: number;
  band_count: number;
  dtypes: string[];
  crs: string;
  bounds: Bounds;
  transform: AffineTransform;
  resolution: PixelResolution;
  nodata: number | null;
  band_descriptions: Array<string | null>;
  tags: Record<string, string>;
  modality: Modality;
  acquisition_date: string | null;
  provenance: MetadataProvenance;
};

export type UploadResponse = {
  asset_id: string;
  original_name: string;
  size_bytes: number;
  sha256: string;
  created_at: string;
  expires_at: string;
  metadata: RasterMetadata;
  warnings: string[];
};

export type Overlay = {
  type: OverlayType;
  file: string | null;
};

export type TraceStage = 'checker' | 'router' | 'tool';

export type TraceStatus = 'ok' | 'rejected' | 'stub';

export type TraceStep = {
  stage: TraceStage;
  status: TraceStatus;
  message: string;
  details: Record<string, unknown>;
};

export type Receipt = {
  why_this_tool: string;
  rejected: boolean;
  reason: string | null;
  trace: TraceStep[];
};

export type ResultEnvelope = {
  task: Task;
  tools: string[];
  parameters: Record<string, unknown>;
  facts: Record<string, unknown>;
  answer_text: string;
  confidence: number;
  warnings: string[];
  overlay: Overlay;
  receipt: Receipt;
};

export type ErrorDetail = {
  code: string;
  message: string;
  details: Record<string, unknown>;
};

export type ErrorEnvelope = {
  error: ErrorDetail;
};

export interface Scene {
  id: string;
  name: string;
  date: string;
  modality: 'optical' | 'sar' | 'unknown';
  preview: string | null;
  asset?: UploadResponse;
  demo?: boolean;
  previewPosition?: 'left' | 'right';
  previewNote?: string;
}
