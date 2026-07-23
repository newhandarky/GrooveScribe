export type CanonicalDrum = 'kick' | 'snare' | 'hi_hat' | 'tom' | 'cymbal';

const legacyHiHats = new Set(['closed_hat', 'open_hat', 'pedal_hat']);
const canonicalDrums = new Set<CanonicalDrum>(['kick', 'snare', 'hi_hat', 'tom', 'cymbal']);

export function canonicalDrumName(drum: string): CanonicalDrum | null {
  const normalized = legacyHiHats.has(drum) ? 'hi_hat' : drum;
  return canonicalDrums.has(normalized as CanonicalDrum) ? (normalized as CanonicalDrum) : null;
}

export function normalizeDrumCounts(drumCounts: Record<string, number>): Partial<Record<CanonicalDrum, number>> {
  const normalized: Partial<Record<CanonicalDrum, number>> = {};
  for (const [drum, count] of Object.entries(drumCounts)) {
    const canonical = canonicalDrumName(drum);
    if (canonical === null || !Number.isFinite(count)) continue;
    normalized[canonical] = (normalized[canonical] ?? 0) + count;
  }
  return normalized;
}
