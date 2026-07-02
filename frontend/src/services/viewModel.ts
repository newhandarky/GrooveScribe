export function runtimeStatusTone(status: string): string {
  if (status === 'ready') return 'ready';
  if (status === 'degraded') return 'degraded';
  if (status === 'not_ready') return 'notReady';
  if (status === 'error') return 'error';
  return 'neutral';
}

export function isTerminalJobStatus(status: string): boolean {
  return status === 'completed' || status === 'failed' || status === 'canceled' || status === 'interrupted';
}

export function stageLabel(stage: string): string {
  return stage
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return '-';
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}
