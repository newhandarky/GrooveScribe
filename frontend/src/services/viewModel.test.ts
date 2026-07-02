import { describe, expect, it } from 'vitest';

import { isTerminalJobStatus, runtimeStatusTone, stageLabel } from './viewModel';

describe('view model helpers', () => {
  it('maps runtime statuses to tones', () => {
    expect(runtimeStatusTone('ready')).toBe('ready');
    expect(runtimeStatusTone('degraded')).toBe('degraded');
    expect(runtimeStatusTone('not_ready')).toBe('notReady');
    expect(runtimeStatusTone('error')).toBe('error');
  });

  it('detects terminal job states', () => {
    expect(isTerminalJobStatus('completed')).toBe(true);
    expect(isTerminalJobStatus('failed')).toBe(true);
    expect(isTerminalJobStatus('interrupted')).toBe(true);
    expect(isTerminalJobStatus('canceled')).toBe(true);
    expect(isTerminalJobStatus('processing')).toBe(false);
  });

  it('formats pipeline stage labels', () => {
    expect(stageLabel('source_separation')).toBe('Source Separation');
  });
});
