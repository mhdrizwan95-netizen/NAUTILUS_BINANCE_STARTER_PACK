type RecordValue = string | number | boolean | null | undefined;

export function shallowEqualRecords<T extends Record<string, RecordValue>>(
  a: T | undefined,
  b: T | undefined,
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
  next: Array<Record<string, unknown>>,
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

export function stableHash(value: unknown): string {
  const seen = new WeakSet<object>();

  const hashValue = (input: unknown): string => {
    if (input === null) return "null";

    const type = typeof input;

    if (type === "undefined") return "undefined";
    if (type === "number") {
      if (Number.isNaN(input)) return "number:NaN";
      if (input === Infinity) return "number:Infinity";
      if (input === -Infinity) return "number:-Infinity";
      return `number:${input}`;
    }
    if (type === "string") return `string:${input}`;
    if (type === "boolean") return `boolean:${input}`;
    if (type === "bigint") return `bigint:${(input as bigint).toString()}`;
    if (type === "symbol") return `symbol:${String(input as symbol)}`;
    if (type === "function") return "function";

    if (input instanceof Date) {
      return `date:${input.toISOString()}`;
    }

    if (Array.isArray(input)) {
      const arrayObject = input as unknown as object;
      if (seen.has(arrayObject)) {
        return "array:[Circular]";
      }
      seen.add(arrayObject);
      const entries = input.map((item) => hashValue(item));
      return `array:[${entries.join("|")}]`;
    }

    if (input && typeof input === "object") {
      const objectValue = input as Record<string, unknown>;
      if (seen.has(objectValue)) {
        return "object:[Circular]";
      }
      seen.add(objectValue);
      const keys = Object.keys(objectValue).sort();
      const entries = keys.map((key) => `${key}:${hashValue(objectValue[key])}`);
      return `object:{${entries.join(",")}}`;
    }

    return "unknown";
  };

  return hashValue(value);
}
