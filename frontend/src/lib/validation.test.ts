import { describe, it, expect } from "vitest";

import {
  validateApiResponse,
  validateFormData,
  modeSchema,
  strategySummarySchema,
  dashboardSummarySchema,
  ordersListResponseSchema,
  metricsModelListResponseSchema,
} from "./validation";

describe("Validation Functions", () => {
  describe("validateApiResponse", () => {
    it("should validate correct strategy summary data", () => {
      const validData = {
        id: "hmm",
        name: "HMM",
        kind: "HMM",
        status: "running" as const,
        symbols: ["BTC/USDT"],
        paramsSchema: { fields: [] },
        performance: {
          pnl: 1000,
          equitySeries: [{ t: "2025-01-01", equity: 10000 }],
          winRate: 0.6,
          sharpe: 1.5,
          drawdown: 0.05,
        },
      };

      expect(() => validateApiResponse(strategySummarySchema, validData)).not.toThrow();
      const result = validateApiResponse(strategySummarySchema, validData);
      expect(result.id).toBe("hmm");
    });

    it("should throw error for invalid data", () => {
      const invalidData = {
        id: "hmm",
        name: "HMM",
        status: "invalid-status", // Invalid status
        symbols: ["BTC/USDT"],
      };

      expect(() => validateApiResponse(strategySummarySchema, invalidData)).toThrow();
    });
  });

  describe("validateFormData", () => {
    it("should validate correct mode data", () => {
      expect(() => validateFormData(modeSchema, "paper")).not.toThrow();
      expect(() => validateFormData(modeSchema, "live")).not.toThrow();
    });

    it("should throw error for invalid mode", () => {
      expect(() => validateFormData(modeSchema, "invalid")).toThrow();
    });
  });

  describe("Schema Validation", () => {
    describe("modeSchema", () => {
      it("should accept valid modes", () => {
        expect(modeSchema.safeParse("paper").success).toBe(true);
        expect(modeSchema.safeParse("live").success).toBe(true);
      });

      it("should reject invalid modes", () => {
        expect(modeSchema.safeParse("invalid").success).toBe(false);
        expect(modeSchema.safeParse("").success).toBe(false);
      });
    });

    describe("dashboardSummarySchema", () => {
      it("should validate correct dashboard summary", () => {
        const validData = {
          kpis: {
            totalPnl: 1000,
            winRate: 0.6,
            sharpe: 1.5,
            maxDrawdown: 0.1,
            openPositions: 5,
          },
          equityByStrategy: [{ t: "2025-01-01", HMM: 10000, MeanRev: 10000 }],
          pnlBySymbol: [{ symbol: "BTC/USDT", pnl: 500 }],
          returns: [0.01, 0.02, -0.01],
        };

        expect(dashboardSummarySchema.safeParse(validData).success).toBe(true);
      });

      it("should reject invalid win rate", () => {
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

  describe("ordersListResponseSchema", () => {
    it("should validate paginated orders", () => {
      const payload = {
        data: [
          {
            id: "order-1",
            symbol: "BTCUSDT",
            side: "buy",
            type: "limit",
            qty: 1,
            filled: 0.5,
            price: 42000,
            status: "open",
            createdAt: Date.now(),
          },
        ],
        page: {
          nextCursor: null,
          prevCursor: null,
          limit: 50,
          totalHint: 1,
          hasMore: false,
        },
      };

      expect(ordersListResponseSchema.safeParse(payload).success).toBe(true);
    });
  });

  describe("metricsModelListResponseSchema", () => {
    it("should validate paginated model metrics", () => {
      const payload = {
        data: [
          {
            id: "trend:binance",
            model: "trend",
            venue: "binance",
            ordersSubmitted: 10,
            ordersFilled: 9,
            trades: 9,
            pnlRealized: 120.5,
            pnlUnrealized: 30.2,
            totalPnl: 150.7,
            winRate: 0.6,
            returnPct: 3.2,
            sharpe: 1.1,
            drawdown: 0.08,
            maxDrawdown: 0.12,
            strategyType: "momentum",
            version: "1.0",
            tradingDays: 14,
          },
        ],
        page: {
          nextCursor: null,
          prevCursor: null,
          limit: 50,
          hasMore: false,
        },
        meta: {
          metricsSource: "stub",
          fetchedAt: Date.now(),
          records: 1,
        },
      };

      expect(metricsModelListResponseSchema.safeParse(payload).success).toBe(true);
    });
  });
});
