import type { Mode, Overlay, Receipt, ResultEnvelope, Scene, TraceStep } from './types';

const RIVER_PAIR_PREVIEW = '/assets/river-pair.png';
const BEFORE_DATE = '2024-06-12';
const AFTER_DATE = '2024-06-24';
const DEMO_WARNING = 'Illustrative demonstration. No image analysis was performed.';
const SAR_PREVIEW_NOTE =
  'Illustrative stand-in only. A visual filter is not radar and this frame is not a SAR product.';

export function createDemoScenes(mode: Mode): Scene[] {
  switch (mode) {
    case 'single_image':
      return [
        {
          id: 'demo-single-optical',
          name: 'River corridor',
          date: BEFORE_DATE,
          modality: 'optical',
          preview: RIVER_PAIR_PREVIEW,
          demo: true,
          previewPosition: 'left',
        },
      ];
    case 'change':
      return [
        {
          id: 'demo-change-before',
          name: 'Before',
          date: BEFORE_DATE,
          modality: 'optical',
          preview: RIVER_PAIR_PREVIEW,
          demo: true,
          previewPosition: 'left',
        },
        {
          id: 'demo-change-after',
          name: 'After',
          date: AFTER_DATE,
          modality: 'optical',
          preview: RIVER_PAIR_PREVIEW,
          demo: true,
          previewPosition: 'right',
        },
      ];
    case 'optical_sar':
      return [
        {
          id: 'demo-fusion-optical',
          name: 'Optical',
          date: BEFORE_DATE,
          modality: 'optical',
          preview: RIVER_PAIR_PREVIEW,
          demo: true,
          previewPosition: 'left',
        },
        {
          id: 'demo-fusion-sar',
          name: 'SAR (illustrative)',
          date: AFTER_DATE,
          modality: 'sar',
          preview: RIVER_PAIR_PREVIEW,
          demo: true,
          previewPosition: 'right',
          previewNote: SAR_PREVIEW_NOTE,
        },
      ];
  }
}

export function createDemoResult(mode: Mode, reject = false): ResultEnvelope {
  if (reject) {
    return createRejectedResult(mode);
  }
  switch (mode) {
    case 'single_image':
      return createSuccessResult({
        mode,
        tool: 'single_image_demo',
        parameters: { asset_id: 'demo-single-optical' },
        why: 'Illustrative demonstration of the single-image workflow.',
        routerMessage: 'Illustrative demonstration: routed to the single-image workflow.',
        answer:
          'A river corridor bordered by farmland and scattered settlements.',
      });
    case 'change':
      return createSuccessResult({
        mode,
        tool: 'change_demo',
        parameters: {
          before_asset_id: 'demo-change-before',
          after_asset_id: 'demo-change-after',
          before_date: BEFORE_DATE,
          after_date: AFTER_DATE,
        },
        why: 'Illustrative demonstration of the two-date optical change workflow.',
        routerMessage: 'Illustrative demonstration: routed to the change workflow.',
        answer:
          'Possible water expansion along the river’s eastern bank.',
      });
    case 'optical_sar':
      return createSuccessResult({
        mode,
        tool: 'optical_sar_demo',
        parameters: {
          optical_asset_id: 'demo-fusion-optical',
          sar_asset_id: 'demo-fusion-sar',
        },
        why: 'Illustrative demonstration of the optical–SAR comparison workflow.',
        routerMessage: 'Illustrative demonstration: routed to the optical–SAR workflow.',
        answer:
          'Explore the optical frame, the illustrative SAR stand-in, and a visual blend of the same landscape.',
      });
  }
}

function createSuccessResult(options: {
  mode: Mode;
  tool: string;
  parameters: Record<string, unknown>;
  why: string;
  routerMessage: string;
  answer: string;
}): ResultEnvelope {
  const { mode, tool, parameters, why, routerMessage, answer } = options;
  return {
    task: mode,
    tools: ['checker_demo', 'router_demo', tool],
    parameters,
    facts: {
      demo: true,
      source: 'canned_illustration',
      summary: answer,
    },
    answer_text: answer,
    confidence: 0,
    warnings: [DEMO_WARNING],
    overlay: emptyOverlay(),
    receipt: demoReceipt({
      why,
      rejected: false,
      reason: null,
      trace: [
        checkerStep('Illustrative demonstration: pack check skipped; no GeoTIFF was inspected.'),
        routerStep('ok', routerMessage, { task: mode, tool, demo: true }),
        {
          stage: 'tool',
          status: 'stub',
          message: `${tool} returned a canned illustration. No image analysis was performed.`,
          details: { demo: true, facts_returned: true },
        },
      ],
    }),
  };
}

function createRejectedResult(mode: Mode): ResultEnvelope {
  const reason = rejectReason(mode);
  return {
    task: 'reject',
    tools: ['checker_demo', 'router_demo'],
    parameters: { rejection_code: 'question_input_mismatch' },
    facts: {},
    answer_text: reason,
    confidence: 0,
    warnings: [DEMO_WARNING],
    overlay: emptyOverlay(),
    receipt: demoReceipt({
      why: 'The input and question do not form a supported specialist workflow.',
      rejected: true,
      reason,
      trace: [
        checkerStep('Illustrative demonstration: pack check skipped; no GeoTIFF was inspected.'),
        routerStep('rejected', reason, { task: 'reject', tool: null, demo: true }),
      ],
    }),
  };
}

function rejectReason(mode: Mode): string {
  switch (mode) {
    case 'single_image':
      return 'Illustrative rejection: a temporal or cross-sensor question does not match a single image.';
    case 'change':
      return 'Illustrative rejection: a temporal-change question requires two aligned optical images from different dates.';
    case 'optical_sar':
      return 'Illustrative rejection: an optical–SAR comparison requires one optical image and one SAR image.';
  }
}

function emptyOverlay(): Overlay {
  return { type: 'none', file: null };
}

function demoReceipt(options: {
  why: string;
  rejected: boolean;
  reason: string | null;
  trace: TraceStep[];
}): Receipt {
  return {
    why_this_tool: options.why,
    rejected: options.rejected,
    reason: options.reason,
    trace: options.trace,
  };
}

function checkerStep(message: string): TraceStep {
  return {
    stage: 'checker',
    status: 'ok',
    message,
    details: { demo: true },
  };
}

function routerStep(
  status: 'ok' | 'rejected',
  message: string,
  details: Record<string, unknown>,
): TraceStep {
  return {
    stage: 'router',
    status,
    message,
    details,
  };
}
