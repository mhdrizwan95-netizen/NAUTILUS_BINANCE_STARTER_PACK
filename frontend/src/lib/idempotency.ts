const FALLBACK_CHARS = 'abcdefghijklmnopqrstuvwxyz0123456789';

const randomFallback = (length = 16): string => {
  let output = '';
  for (let i = 0; i < length; i += 1) {
    const idx = Math.floor(Math.random() * FALLBACK_CHARS.length);
    output += FALLBACK_CHARS[idx];
  }
  return output;
};

export const generateIdempotencyKey = (prefix = 'ops'): string => {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `${prefix}_${crypto.randomUUID()}`;
  }
  return `${prefix}_${randomFallback(24)}`;
};
