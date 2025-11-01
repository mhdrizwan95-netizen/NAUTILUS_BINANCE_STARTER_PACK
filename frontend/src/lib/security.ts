// Security utilities and hardening

// Content Security Policy headers (to be set by server)
export const CSP_HEADERS = {
  'Content-Security-Policy': [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'", // Allow inline scripts for React
    "style-src 'self' 'unsafe-inline'", // Allow inline styles
    "img-src 'self' data: https:", // Allow data URLs and HTTPS images
    "font-src 'self' data:", // Allow data URLs for fonts
    "connect-src 'self' ws: wss: https:", // Allow WebSocket and HTTPS connections
    "object-src 'none'", // Block plugins
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'", // Prevent clickjacking
  ].join('; '),
};

// Input sanitization utilities
export class InputSanitizer {
  // Sanitize text input
  static sanitizeText(input: string): string {
    return input
      .replace(/[<>]/g, '') // Remove potential HTML tags
      .trim()
      .slice(0, 1000); // Limit length
  }

  // Sanitize email
  static sanitizeEmail(email: string): string {
    const sanitized = email.toLowerCase().trim();
    // Basic email validation
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(sanitized)) {
      throw new Error('Invalid email format');
    }
    return sanitized;
  }

  // Sanitize numeric input
  static sanitizeNumber(input: string | number, min?: number, max?: number): number {
    const num = typeof input === 'string' ? parseFloat(input) : input;

    if (isNaN(num)) {
      throw new Error('Invalid number');
    }

    if (min !== undefined && num < min) {
      throw new Error(`Number must be at least ${min}`);
    }

    if (max !== undefined && num > max) {
      throw new Error(`Number must be at most ${max}`);
    }

    return num;
  }

  // Sanitize strategy parameters
  static sanitizeStrategyParams(params: Record<string, any>): Record<string, any> {
    const sanitized: Record<string, any> = {};

    for (const [key, value] of Object.entries(params)) {
      // Only allow alphanumeric keys
      if (!/^[a-zA-Z0-9_]+$/.test(key)) {
        throw new Error(`Invalid parameter key: ${key}`);
      }

      // Sanitize values based on type
      if (typeof value === 'string') {
        sanitized[key] = this.sanitizeText(value);
      } else if (typeof value === 'number') {
        sanitized[key] = value; // Numbers are safe
      } else if (typeof value === 'boolean') {
        sanitized[key] = value; // Booleans are safe
      } else {
        throw new Error(`Unsupported parameter type for ${key}`);
      }
    }

    return sanitized;
  }
}

// Rate limiting for API calls
export class RateLimiter {
  private static instance: RateLimiter;
  private calls: Map<string, number[]> = new Map();

  static getInstance(): RateLimiter {
    if (!RateLimiter.instance) {
      RateLimiter.instance = new RateLimiter();
    }
    return RateLimiter.instance;
  }

  // Check if request should be allowed
  canMakeRequest(endpoint: string, limit = 10, windowMs = 60000): boolean {
    const now = Date.now();
    const windowStart = now - windowMs;

    if (!this.calls.has(endpoint)) {
      this.calls.set(endpoint, []);
    }

    const calls = this.calls.get(endpoint)!;

    // Remove old calls outside the window
    const recentCalls = calls.filter(call => call > windowStart);

    if (recentCalls.length >= limit) {
      return false; // Rate limit exceeded
    }

    // Add current call
    recentCalls.push(now);
    this.calls.set(endpoint, recentCalls);

    return true;
  }

  // Get remaining calls for endpoint
  getRemainingCalls(endpoint: string, limit = 10, windowMs = 60000): number {
    const now = Date.now();
    const windowStart = now - windowMs;

    const calls = this.calls.get(endpoint) || [];
    const recentCalls = calls.filter(call => call > windowStart);

    return Math.max(0, limit - recentCalls.length);
  }
}

// API request signing (for authenticated requests)
export class RequestSigner {
  private static instance: RequestSigner;
  private apiKey: string | null = null;
  private apiSecret: string | null = null;

  static getInstance(): RequestSigner {
    if (!RequestSigner.instance) {
      RequestSigner.instance = new RequestSigner();
    }
    return RequestSigner.instance;
  }

  setCredentials(apiKey: string, apiSecret: string): void {
    this.apiKey = apiKey;
    this.apiSecret = apiSecret;
  }

  // Generate HMAC signature for request
  signRequest(method: string, endpoint: string, body?: any): string {
    if (!this.apiSecret) {
      throw new Error('API credentials not set');
    }

    const timestamp = Date.now().toString();
    const message = `${method}${endpoint}${timestamp}${body ? JSON.stringify(body) : ''}`;

    // Simple HMAC implementation (in production, use crypto.subtle)
    // This is a placeholder - implement proper HMAC-SHA256
    return btoa(message + this.apiSecret).slice(0, 64);
  }

  // Add authentication headers to request
  addAuthHeaders(headers: Headers, method: string, endpoint: string, body?: any): void {
    if (!this.apiKey) {
      return; // No auth if credentials not set
    }

    headers.set('X-API-Key', this.apiKey);
    headers.set('X-Timestamp', Date.now().toString());
    headers.set('X-Signature', this.signRequest(method, endpoint, body));
  }
}

// Secure storage utilities
export class SecureStorage {
  private static readonly PREFIX = 'nautilus_secure_';

  // Store sensitive data (encrypted in production)
  static setItem(key: string, value: string): void {
    try {
      const encrypted = this.encrypt(value); // Placeholder encryption
      localStorage.setItem(this.PREFIX + key, encrypted);
    } catch (error) {
      console.error('Failed to store secure item:', error);
    }
  }

  // Retrieve sensitive data
  static getItem(key: string): string | null {
    try {
      const encrypted = localStorage.getItem(this.PREFIX + key);
      return encrypted ? this.decrypt(encrypted) : null; // Placeholder decryption
    } catch (error) {
      console.error('Failed to retrieve secure item:', error);
      return null;
    }
  }

  // Remove sensitive data
  static removeItem(key: string): void {
    localStorage.removeItem(this.PREFIX + key);
  }

  // Clear all secure data
  static clear(): void {
    const keys = Object.keys(localStorage);
    keys.forEach(key => {
      if (key.startsWith(this.PREFIX)) {
        localStorage.removeItem(key);
      }
    });
  }

  // Placeholder encryption (implement proper encryption in production)
  private static encrypt(value: string): string {
    return btoa(value); // Base64 encoding as placeholder
  }

  // Placeholder decryption
  private static decrypt(value: string): string {
    return atob(value);
  }
}

// CSRF protection
export class CSRFProtection {
  private static token: string | null = null;

  static generateToken(): string {
    if (!this.token) {
      this.token = Math.random().toString(36).substring(2) + Date.now().toString(36);
    }
    return this.token;
  }

  static validateToken(token: string): boolean {
    return this.token === token;
  }

  static getToken(): string | null {
    return this.token;
  }
}

// Audit logging
export class AuditLogger {
  private static instance: AuditLogger;
  private logs: Array<{
    timestamp: number;
    action: string;
    userId?: string;
    details: Record<string, any>;
  }> = [];

  static getInstance(): AuditLogger {
    if (!AuditLogger.instance) {
      AuditLogger.instance = new AuditLogger();
    }
    return AuditLogger.instance;
  }

  logAction(action: string, details: Record<string, any>, userId?: string): void {
    const logEntry = {
      timestamp: Date.now(),
      action,
      userId,
      details,
    };

    this.logs.push(logEntry);

    // Keep only last 1000 entries
    if (this.logs.length > 1000) {
      this.logs.shift();
    }

    // In production, send to audit service
    console.log('Audit log:', logEntry);
  }

  getRecentLogs(limit = 100): any[] {
    return this.logs.slice(-limit);
  }

  exportLogs(): string {
    return JSON.stringify(this.logs, null, 2);
  }
}

// Network security checks
export class NetworkSecurity {
  // Check if connection is secure
  static isSecureConnection(): boolean {
    return window.location.protocol === 'https:' ||
           window.location.hostname === 'localhost' ||
           window.location.hostname === '127.0.0.1';
  }

  // Validate API endpoint
  static isValidEndpoint(url: string): boolean {
    try {
      const parsedUrl = new URL(url);

      // Only allow HTTPS in production
      if (process.env.NODE_ENV === 'production' && parsedUrl.protocol !== 'https:') {
        return false;
      }

      // Allow localhost in development
      if (process.env.NODE_ENV === 'development' && parsedUrl.hostname === 'localhost') {
        return true;
      }

      // Check against allowed domains
      const allowedDomains = [
        'api.nautilus.com',
        'localhost',
        '127.0.0.1',
      ];

      return allowedDomains.includes(parsedUrl.hostname);
    } catch {
      return false;
    }
  }

  // Detect potential security threats
  static detectThreats(): string[] {
    const threats: string[] = [];

    // Check for insecure connection
    if (!this.isSecureConnection()) {
      threats.push('Insecure connection detected');
    }

    // Check for dev tools (basic detection)
    if ((window as any).console && (window as any).console.clear) {
      // This is a very basic check - not foolproof
      threats.push('Developer tools may be open');
    }

    return threats;
  }
}

// Initialize security measures
export function initializeSecurity(): void {
  // Set up CSRF protection
  CSRFProtection.generateToken();

  // Log security initialization
  AuditLogger.getInstance().logAction('security_initialized', {
    timestamp: Date.now(),
    userAgent: navigator.userAgent,
    secureConnection: NetworkSecurity.isSecureConnection(),
  });

  // Check for security threats periodically
  setInterval(() => {
    const threats = NetworkSecurity.detectThreats();
    if (threats.length > 0) {
      threats.forEach(threat => {
        AuditLogger.getInstance().logAction('security_threat_detected', { threat });
      });
    }
  }, 30000); // Check every 30 seconds
}
