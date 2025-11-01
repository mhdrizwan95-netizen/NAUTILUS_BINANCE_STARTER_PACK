import { describe, it, expect } from 'vitest';
import {
  validateApiResponse,
  validateFormData,
  modeSchema,
  strategySummarySchema,
  dashboardSummarySchema,
} from './validation';

describe('Validation Functions', () => {
  describe('validateApiResponse', () => {
    it('should validate correct strategy summary data', () => {
      const validData = {
        id: 'hmm',
        name: 'HMM',
        kind: 'HMM',
        status: 'running' as const,
        symbols: ['BTC/USDT'],
        paramsSchema: { fields: [] },
        performance: {
          pnl: 1000,
          equitySeries: [{ t: '2025-01-01', equity: 10000 }],
          winRate: 0.6,
          sharpe: 1.5,
          drawdown: 0.05,
        },
      };

      expect(() => validateApiResponse(strategySummarySchema, validData)).not.toThrow();
      const result = validateApiResponse(strategySummarySchema, validData);
      expect(result.id).toBe('hmm');
    });

    it('should throw error for invalid data', () => {
      const invalidData = {
        id: 'hmm',
        name: 'HMM',
        status: 'invalid-status', // Invalid status
        symbols: ['BTC/USDT'],
      };

      expect(() => validateApiResponse(strategySummarySchema, invalidData)).toThrow();
    });
  });

  describe('validateFormData', () => {
    it('should validate correct mode data', () => {
      expect(() => validateFormData(modeSchema, 'paper')).not.toThrow();
      expect(() => validateFormData(modeSchema, 'live')).not.toThrow();
    });

    it('should throw error for invalid mode', () => {
      expect(() => validateFormData(modeSchema, 'invalid')).toThrow();
    });
  });

  describe('Schema Validation', () => {
    describe('modeSchema', () => {
      it('should accept valid modes', () => {
        expect(modeSchema.safeParse('paper').success).toBe(true);
        expect(modeSchema.safeParse('live').success).toBe(true);
      });

      it('should reject invalid modes', () => {
        expect(modeSchema.safeParse('invalid').success).toBe(false);
        expect(modeSchema.safeParse('').success).toBe(false);
      });
    });

    describe('dashboardSummarySchema', () => {
      it('should validate correct dashboard summary', () => {
        const validData = {
          kpis: {
            totalPnl: 1000,
            winRate: 0.6,
            sharpe: 1.5,
            maxDrawdown: 0.1,
            openPositions: 5,
          },
          equityByStrategy: [
            { t: '2025-01-01', HMM: 10000, MeanRev: 10000 },
          ],
          pnlBySymbol: [
            { symbol: 'BTC/USDT', pnl: 500 },
          ],
          returns: [0.01, 0.02, -0.01],
        };

        expect(dashboardSummarySchema.safeParse(validData).success).toBe(true);
      });

      it('should reject invalid win rate', () => {
        const invalidData = {
          kpis: {
            totalPnl: 1000,
            winRate: 1.5, // Invalid: should be <= 1
            sharpe: 1.5,
            maxDrawdown: 0.1,
            openPositions: 5,
          },
          equityByStrategy: [],
          pnlBySymbol: [],
          returns: [],
        };

        expect(dashboardSummarySchema.safeParse(invalidData).success).toBe(false);
      });
    });
  });
});
