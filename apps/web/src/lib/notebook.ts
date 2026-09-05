import { createDemoResult, createDemoScenes } from './demo';
import type { Mode, ResultEnvelope, Scene } from './types';

export type Investigation = {
  id: string;
  title: string;
  source: 'demo' | 'local';
  mode: Mode;
  question: string;
  scenes: Scene[];
  result: ResultEnvelope | null;
  submittedQuestion?: string;
};

export type Pending = {
  id: string;
  file: File;
  modality: 'auto' | 'optical' | 'sar';
  date: string;
};

export const MODES: Mode[] = ['single_image', 'change', 'optical_sar'];

export const MODE_NAMES: Record<Mode, string> = {
  single_image: 'Single image',
  change: 'Change detection',
  optical_sar: 'Optical + SAR',
};

export const QUESTIONS: Record<Mode, string> = {
  single_image: 'Describe the land cover in this scene.',
  change: 'What changed along the river?',
  optical_sar: 'Compare the optical and SAR images.',
};

export const TITLES: Record<Mode, string> = {
  single_image: 'A closer look at the landscape.',
  change: 'What changed along the river?',
  optical_sar: 'One landscape. Two perspectives.',
};

export function sceneRoleLabel(scene: Scene, index: number, mode: Mode): string {
  if (mode === 'change') return index === 0 ? 'Before' : 'After';
  if (mode === 'optical_sar') return scene.modality === 'sar' ? 'SAR' : 'Optical';
  if (scene.modality === 'sar') return 'SAR';
  if (scene.modality === 'optical') return 'Optical';
  return 'Scene';
}

export function questionSuggestions(scenes: Scene[]): Mode[] {
  if (scenes.length < 2) return ['single_image'];
  const hasSar = scenes.some((item) => item.modality === 'sar');
  const hasOptical = scenes.some((item) => item.modality === 'optical');
  if (hasSar && hasOptical) return ['optical_sar'];
  if (scenes.every((item) => item.modality === 'optical')) return ['change'];
  return ['single_image'];
}

export function demoInvestigation(): Investigation {
  return {
    id: 'demo',
    title: 'River corridor',
    source: 'demo',
    mode: 'change',
    question: QUESTIONS.change,
    scenes: createDemoScenes('change'),
    result: createDemoResult('change'),
    submittedQuestion: QUESTIONS.change,
  };
}

export function saveJson(data: unknown, name: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function receiptTrail(result: ResultEnvelope, demo: boolean): string {
  return result.receipt.trace
    .map((step) => {
      if (step.stage === 'checker') return step.status === 'rejected' ? 'Rejected' : 'Checked';
      if (step.stage === 'router') {
        if (step.status === 'rejected' || result.task === 'reject') return 'Not routed';
        return result.task === 'change' ? 'Change' : result.task === 'optical_sar' ? 'Optical + SAR' : 'Single image';
      }
      if (step.status === 'stub') return demo ? 'Illustrative' : 'Not connected';
      if (step.status === 'rejected') return 'Rejected';
      return 'Ran';
    })
    .join(' · ');
}
