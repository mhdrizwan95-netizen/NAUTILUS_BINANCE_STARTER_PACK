type LoopGuardOptions = {
  maxIter?: number;
  timeoutMs?: number;
  sampleEvery?: number;
  name?: string;
};

export class LoopGuard {
  private maxIter: number;
  private timeoutMs: number;
  private sampleEvery: number;
  private name: string;
  private count = 0;
  private start = Date.now();
  private lastFingerprint: string | null = null;
  private repeatedSamples = 0;

  constructor({
    maxIter = 10_000,
    timeoutMs = 10_000,
    sampleEvery = 100,
    name = "loop",
  }: LoopGuardOptions = {}) {
    this.maxIter = maxIter;
    this.timeoutMs = timeoutMs;
    this.sampleEvery = sampleEvery;
    this.name = name;
  }

  tick(state: Record<string, unknown> = {}): void {
    this.count += 1;
    if (this.count % this.sampleEvery !== 0) {
      return;
    }
    const fingerprint = this.fingerprint(state);
    if (fingerprint === this.lastFingerprint) {
      this.repeatedSamples += 1;
      if (this.repeatedSamples === 1 || this.repeatedSamples % 5 === 0) {
        // eslint-disable-next-line no-console
        console.warn(`[LoopGuard][state] ${this.name} repeating`, state);
      }
    } else {
      this.repeatedSamples = 0;
      this.lastFingerprint = fingerprint;
      // eslint-disable-next-line no-console
      console.info(`[LoopGuard][state] ${this.name} sample`, state);
    }

    const elapsed = Date.now() - this.start;
    if (this.count >= this.maxIter || elapsed >= this.timeoutMs) {
      const err = new Error(
        `[LoopGuard] ${this.name} abort at i=${this.count}, t=${elapsed}ms, state=${JSON.stringify(state).slice(0, 512)}`,
      );
      (err as Error & { code?: string }).code = "LOOP_GUARD_ABORT";
      throw err;
    }
  }

  reset(): void {
    this.count = 0;
    this.start = Date.now();
    this.lastFingerprint = null;
    this.repeatedSamples = 0;
  }

  private fingerprint(state: Record<string, unknown>): string {
    try {
      const ordered = Object.keys(state)
        .sort()
        .reduce<Record<string, unknown>>((acc, key) => {
          acc[key] = state[key];
          return acc;
        }, {});
      return JSON.stringify(ordered).slice(0, 512);
    } catch {
      return JSON.stringify(Object.keys(state)).slice(0, 512);
    }
  }
}
