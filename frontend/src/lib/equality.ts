type RecordValue = string | number | boolean | null | undefined;

export function shallowEqualRecords<T extends Record<string, RecordValue>>(
  a: T | undefined,
  b: T | undefined
): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  const aKeys = Object.keys(a);
  const bKeys = Object.keys(b);
  if (aKeys.length !== bKeys.length) return false;
  return aKeys.every((key) => Object.is(a[key], b[key]));
}

export function areVenueArraysEqual(
  prev: Array<Record<string, unknown>>,
  next: Array<Record<string, unknown>>
): boolean {
  if (prev === next) return true;
  if (prev.length !== next.length) return false;
  for (let i = 0; i < prev.length; i += 1) {
    const prevRow = prev[i];
    const nextRow = next[i];
    const prevKeys = Object.keys(prevRow);
    const nextKeys = Object.keys(nextRow);
    if (prevKeys.length !== nextKeys.length) return false;
    for (const key of prevKeys) {
      if (!Object.is(prevRow[key], nextRow[key])) {
        return false;
      }
    }
  }
  return true;
}
