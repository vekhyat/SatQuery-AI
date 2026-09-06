import { useState } from 'react';
import { ChevronDown, Download, FileCheck2, GitBranch, Info, Search } from 'lucide-react';
import { MODES, receiptTrail, saveJson } from '../lib/notebook';
import type { ResultEnvelope } from '../lib/types';

export function Receipt({
  result,
  demo,
  busy,
  question,
}: {
  result: ResultEnvelope | null;
  demo: boolean;
  busy: boolean;
  question: string;
}) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const definitions = [
    { id: 'checker', title: 'Check inputs', subtitle: 'GeoTIFF validation', Icon: FileCheck2 },
    { id: 'router', title: 'Choose tool', subtitle: 'Deterministic routing', Icon: GitBranch },
    { id: 'tool', title: 'Inspect evidence', subtitle: 'Specialist analysis', Icon: Search },
  ];
  const selected = result?.task;
  if (!result && !busy) return null;
  return (
    <section className={'receipt' + (open ? ' is-open' : '')} aria-label="Analysis receipt" aria-busy={busy}>
      <button className="receipt-summary" type="button" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
        <span className="receipt-summary-title">Receipt</span>
        <span className="receipt-trail">{busy ? 'Waiting for the API' : result ? receiptTrail(result, demo) : ''}</span>
        <ChevronDown size={16} />
      </button>
      {open && (
        <>
          <div className="trace-flow">
            {definitions.map(({ id, title, subtitle, Icon }, index) => {
              const step = result?.receipt.trace.find((s) => s.stage === id);
              const status = busy
                ? 'Waiting'
                : !step
                  ? 'Not run'
                  : demo
                    ? result?.receipt.rejected && step.status === 'rejected'
                      ? 'Rejected'
                      : 'Demo'
                    : step.status === 'ok'
                      ? 'Passed'
                      : step.status === 'stub'
                        ? 'Not connected'
                        : 'Rejected';
              return (
                <div className={'trace-column ' + (id === 'router' ? 'router-column' : '')} key={id}>
                  <button
                    className={'trace-step ' + (expanded === id ? 'expanded ' : '') + (step?.status === 'rejected' ? 'rejected' : '')}
                    type="button"
                    disabled={!step || busy}
                    onClick={() => setExpanded(expanded === id ? null : id)}
                    aria-expanded={expanded === id}
                  >
                    <span className="step-number">{index + 1}</span>
                    <Icon size={28} strokeWidth={1.5} />
                    <span className="step-copy">
                      <strong>{title}</strong>
                      <small>{subtitle}</small>
                    </span>
                    <span className={'step-status status-' + step?.status}>
                      {status}
                      {step && !busy && <ChevronDown size={12} />}
                    </span>
                  </button>
                  {id === 'router' && (
                    <div className="route-options" aria-label="Selected analysis route">
                      {MODES.map((mode) => (
                        <span key={mode} className={selected === mode ? 'selected' : ''}>
                          <i />
                          {mode === 'single_image' ? 'Single image' : mode === 'change' ? 'Change' : 'Optical + SAR'}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
          {expanded && result && (
            <div className="trace-detail">
              <strong>{definitions.find((d) => d.id === expanded)?.title}</strong>
              <p>{result.receipt.trace.find((s) => s.stage === expanded)?.message}</p>
              <pre>{JSON.stringify(result.receipt.trace.find((s) => s.stage === expanded)?.details ?? {}, null, 2)}</pre>
            </div>
          )}
          {result && (
            <details className="receipt-details">
              <summary>
                Why this tool? <ChevronDown size={14} />
              </summary>
              <p>{result.receipt.why_this_tool}</p>
              <dl>
                <dt>Tools</dt>
                <dd>{result.tools.join(', ') || 'No tool selected'}</dd>
                <dt>Parameters</dt>
                <dd>
                  <pre>{JSON.stringify(result.parameters, null, 2)}</pre>
                </dd>
              </dl>
            </details>
          )}
        </>
      )}
      <div className="receipt-footer">
        <span>
          <Info size={15} />
          {demo || result?.receipt.trace.some((s) => s.status === 'stub') || result?.receipt.rejected || typeof result?.facts.confidence_status === 'string'
            ? 'Confidence: not measured'
            : result
              ? `Confidence: ${Math.round(result.confidence * 100)}%`
              : 'Confidence: not measured'}
          {demo ? ' · No image analysis performed' : result?.receipt.trace.some((s) => s.status === 'stub') ? ' · Analysis not connected' : ''}
        </span>
        <div className="export-actions">
          <button
            className="text-button"
            type="button"
            disabled={!result || busy}
            aria-label="Download JSON"
            onClick={() => saveJson(result, 'satquery-result.json')}
          >
            <Download size={15} />
            JSON
          </button>
          <button
            className="button primary"
            type="button"
            disabled={!result || busy}
            onClick={() =>
              saveJson(
                {
                  source: demo ? 'illustrative_demo' : 'api',
                  question,
                  receipt: result?.receipt,
                  tools: result?.tools,
                  parameters: result?.parameters,
                  warnings: result?.warnings,
                },
                'satquery-receipt.json',
              )
            }
          >
            <Download size={16} />
            Export receipt
          </button>
        </div>
      </div>
    </section>
  );
}
