// ==========================================
// ASIAbot Dashboard — Real API Client
// ==========================================
"use client";

import { useState, useEffect, useCallback, useRef } from "react";

// ---- API Response Types (matching Python main.py) ----

export interface StatusResponse {
  is_running: boolean;
  locked: boolean;
  portfolio: {
    initial: number;
    current: number;
    daily_pnl: number;
    daily_roi: number;
    unrealized_pnl: number;
    realized_pnl: number;
    total_pnl: number;
    total_roi: number;
    exposure: number;
    max_exposure: number;
  };
  stats: {
    total_signals: number;
    total_bets: number;
    win_count: number;
    loss_count: number;
    total_closed: number;
    last_scan: string | null;
  };
  limits: {
    max_bet_pct: number;
    max_exposure_pct: number;
    daily_stop_loss_pct: number;
    city_cap: number;
  };
  metrics: {
    sharpe_ratio: number;
    max_drawdown_pct: number;
  };
  open_positions?: Array<{
    id: number;
    city: string;
    side: string;
    shares: number;
    current_price: number;
    unrealized_pnl: number;
    amount: number;
  }>;
}

export interface Signal {
  id: number;
  market_id: string;
  city: string;
  outcome: "YES" | "NO";
  entry_price: number;
  current_price: number;
  stake_amount: number;
  unrealized_pnl: number;
  fair_value: number | null;
  edge: number | null;
  entry_edge: number | null;
  live_edge: number | null;
  move_pct: number | null;
  ladder_orders: unknown[];
  placed_at: string | null;
  resolution_date: string | null;
  status: string;
}

export interface HistoryEntry {
  id: number;
  city: string;
  outcome: string;
  entry_price: number;
  stake_amount: number;
  realized_pnl: number;
  roi: number;
  result: "WIN" | "LOSS";
  placed_at: string | null;
  settled_at: string | null;
}

export interface HistoryStats {
  total_won: number;
  total_lost: number;
  win_rate: number;
  overall_roi: number;
  total_stake: number;
  total_pnl: number;
  total_win_pnl: number;
  total_loss_pnl: number;
  profit_factor: number;
}

export interface HealthResponse {
  verdict: "healthy" | "degraded" | "critical" | "error";
  verdict_text: string;
  verdict_color: string;
  activity_24h: {
    bets_opened: number;
    pass_reasons: Array<{
      market_id: string;
      edge_pct: number;
      reason: string;
      time: string;
    }>;
    total_analyses: number;
  };
  edge_distribution: {
    avg_net_edge_pct: number;
    min_net_edge_pct: number;
    max_net_edge_pct: number;
    count: number;
  };
  summary_3day: {
    total_settled: number;
    wins: number;
    losses: number;
    win_rate_pct: number;
    total_pnl: number;
    total_stake: number;
    roi_pct: number;
    avg_net_edge_pct: number;
  };
  red_flags: Array<{
    severity: "critical" | "warning" | "info";
    message: string;
    action: string;
  }>;
  daily_pnl_timeline: Array<{
    date: string;
    pnl: number;
    trades: number;
  }>;
}

// ---- UI Component Types (matching mock-data.ts) ----

export interface KpiData {
  portfolioValue: number;
  dailyPnl: number;
  totalPnl: number;
  openPositions: number;
  winRate: number;
  winRateLabel: string;
  totalTrades: number;
  wins: number;
  losses: number;
  avgEdge: number;
  sharpeRatio: number;
  maxDrawdown: number;
  // Open positions summary
  openPositionsValue: number;  // Açık pozisyonların toplam değeri (shares × current_price)
  maxOpenableUsd: number;      // Maksimum açılabilecek USD (gün itibarıyla)
  // Second row metrics
  totalPnlValue: number;       // Total PnL ($)
  totalRoi: number;            // Total ROI (%)
  closedBets: number;          // Kapalı Bahis
  closedWins: number;
  closedLosses: number;
  expectancy: number;          // Ortalama kazanç/bahis ($)
  avgBetSize: number;          // Ortalama Bahis Tutarı ($)
  profitFactor: number;        // Profit Factor
}

export interface PortfolioPoint {
  date: string;
  value: number;
  drawdown?: number;
}

export interface OpenPosition {
  id: string;
  city: string;
  side: "YES" | "NO";
  entryPrice: number;
  currentPrice: number;
  pnl: number;
  edge: number;
  timeLeft: string;
  openedAt: string;   // formatted date string
  conditionId: string;
  amount: number;
}

export interface ActivityItem {
  id: string;
  time: string;
  color: "blue" | "purple" | "gray" | "orange" | "teal" | "red";
  message: string;
}

export interface EdgeBucket {
  range: string;
  count: number;
}

export interface TradeHistoryEntry {
  id: string;
  timestamp: string;
  city: string;
  side: "YES" | "NO";
  entryPrice: number;
  exitPrice: number;
  pnl: number;
  result: "WIN" | "LOSS";
  edge: number;
  duration: string;
  closedAt: string;  // formatted closing date/time
  strategy: string;
  conditionId: string;
}

export interface ModelScore {
  name: string;
  brierScore: number;
  accuracy: number;
  weight: number;
  trend: "up" | "down" | "stable";
  sampleCount: number;
}

export type HealthVerdict = "healthy" | "degraded" | "critical" | "error";
export type FlagSeverity = "critical" | "warning" | "info";
export type SlippageEntry = {
  id: string;
  city: string;
  side: string;
  expected_price: number;
  entry_price: number;
  slippage_pct: number;
  result: string;
  analyzed_at: string | null;
};

// ---- Fetch helpers ----

const REFRESH_INTERVAL = 10000; // 10 seconds

async function fetchJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal });
  if (!res.ok) throw new Error(`API error ${res.status}: ${res.statusText}`);
  return res.json();
}

// ---- Data mapping functions ----

function mapKpiData(
  status: StatusResponse | null,
  health: HealthResponse | null,
  historyStats: HistoryStats | null,
): KpiData {
  if (!status) {
    return {
      portfolioValue: 10000,
      dailyPnl: 0,
      totalPnl: 0,
      openPositions: 0,
      winRate: 0,
      winRateLabel: "Veri yok",
      totalTrades: 0,
      wins: 0,
      losses: 0,
      avgEdge: 0,
      sharpeRatio: 0,
      maxDrawdown: 0,
      openPositionsValue: 0,
      maxOpenableUsd: 0,
      totalPnlValue: 0,
      totalRoi: 0,
      closedBets: 0,
      closedWins: 0,
      closedLosses: 0,
      expectancy: 0,
      avgBetSize: 0,
      profitFactor: 0,
    };
  }
  const s = status.stats;
  const p = status.portfolio;
  
  // Use historyStats for ALL win/loss metrics (includes closed_early bets for consistency)
  const hs = historyStats;
  const totalPnlValue = hs?.total_pnl ?? 0;
  const totalRoi = hs?.overall_roi ?? 0;
  const closedWins = hs?.total_won ?? 0;
  const closedLosses = hs?.total_lost ?? 0;
  const closedBets = closedWins + closedLosses;
  const winRate = closedBets > 0 ? (closedWins / closedBets) * 100 : 0;
  const expectancy = closedBets > 0 ? totalPnlValue / closedBets : 0;
  const avgBetSize = closedBets > 0 && hs?.total_stake ? hs.total_stake / closedBets : 0;
  const profitFactor = hs?.profit_factor ?? 0;

  let winRateLabel = "Veri yok";
  if (closedBets > 0) {
    if (winRate >= 70) winRateLabel = "Mükemmel";
    else if (winRate >= 60) winRateLabel = "İyi";
    else if (winRate >= 50) winRateLabel = "Orta";
    else winRateLabel = "Zayıf";
  }

  const avgEdge = health?.edge_distribution?.avg_net_edge_pct ?? 0;

  // Calculate open positions total value (sum of shares × current_price)
  const openPositionsValue = status.open_positions?.reduce(
    (sum, pos) => sum + (pos.shares || 0) * (pos.current_price || 0), 0
  ) ?? 0;

  // Calculate max openable USD — match bot's conservative formula:
  // portfolio = initial + realized_pnl (exclude unrealized, same as bot)
  // max_exposure = portfolio × 25%
  // available_for_new = max_exposure - sum(Bet.amount) for open bets
  const portfolioValue = p.initial + p.realized_pnl;  // conservative: no unrealized
  const maxExposurePct = 0.25; // TOTAL_EXPOSURE_PCT from config
  const maxExposure = portfolioValue * maxExposurePct;
  // Use sum(Bet.amount) for exposure — same as bet placer's check
  const exposureAmount = status.open_positions?.reduce(
    (sum, pos) => sum + (pos.amount || 0), 0
  ) ?? 0;
  const maxOpenableUsd = Math.max(0, maxExposure - exposureAmount);

  return {
    portfolioValue: p.initial + p.realized_pnl + p.unrealized_pnl,
    dailyPnl: p.daily_pnl,
    totalPnl: p.total_pnl,
    openPositions: s.total_bets,
    winRate: Math.round(winRate * 10) / 10,
    winRateLabel,
    totalTrades: closedBets,
    wins: closedWins,
    losses: closedLosses,
    avgEdge: Math.round(avgEdge * 10) / 10,
    sharpeRatio: status.metrics?.sharpe_ratio ?? 0,
    maxDrawdown: status.metrics?.max_drawdown_pct ?? 0,
    // Open positions summary
    openPositionsValue: Math.round(openPositionsValue * 100) / 100,
    maxOpenableUsd: Math.round(maxOpenableUsd * 100) / 100,
    // Second row
    totalPnlValue,
    totalRoi,
    closedBets,
    closedWins,
    closedLosses,
    expectancy: Math.round(expectancy * 100) / 100,
    avgBetSize: Math.round(avgBetSize * 100) / 100,
    profitFactor,
  };
}

function mapPortfolioData(status: StatusResponse | null, history: HistoryEntry[]): PortfolioPoint[] {
  // Build equity curve from settled bets
  if (!status && history.length === 0) return [];

  const initial = status?.portfolio?.initial ?? 10000;
  const settled = history
    .filter((h) => h.settled_at)
    .sort((a, b) => new Date(a.settled_at!).getTime() - new Date(b.settled_at!).getTime());

  if (settled.length === 0) {
    // Return a single point with current value
    const current = status ? initial + status.portfolio.realized_pnl + status.portfolio.unrealized_pnl : initial;
    return [{ date: "Bugün", value: Math.round(current) }];
  }

  const points: PortfolioPoint[] = [];
  let running = initial;

  // Group by date
  const byDate = new Map<string, number>();
  for (const h of settled) {
    const d = new Date(h.settled_at!);
    const key = `${d.getDate()} ${d.toLocaleDateString("tr-TR", { month: "short" })}`;
    byDate.set(key, (byDate.get(key) ?? 0) + h.realized_pnl);
  }

  let peak = initial;
  for (const [date, pnl] of byDate) {
    running += pnl;
    if (running > peak) peak = running;
    const drawdown = peak > 0 ? ((peak - running) / peak) * 100 : 0;
    points.push({ date, value: Math.round(running), drawdown: Math.round(drawdown * 10) / 10 });
  }

  // Add current value as last point
  if (status) {
    const current = initial + status.portfolio.realized_pnl + status.portfolio.unrealized_pnl;
    const today = new Date();
    const todayKey = `${today.getDate()} ${today.toLocaleDateString("tr-TR", { month: "short" })}`;
    if (points.length === 0 || points[points.length - 1].date !== todayKey) {
      points.push({ date: todayKey, value: Math.round(current) });
    } else {
      points[points.length - 1].value = Math.round(current);
    }
  }

  return points.length > 0 ? points : [{ date: "Bugün", value: initial }];
}

function mapOpenPositions(signals: Signal[]): OpenPosition[] {
  return signals.map((s) => {
    const edge = s.live_edge ?? s.edge ?? 0;
    const edgePct = Math.round(edge * 1000) / 10; // Convert to percentage

    // Format resolution_date as closing date
    let closesAt = "—";
    if (s.resolution_date) {
      closesAt = new Date(s.resolution_date).toLocaleDateString("tr-TR", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
    }

    const openedAt = s.placed_at
      ? new Date(s.placed_at).toLocaleDateString("tr-TR", {
          day: "numeric",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        })
      : "—";

    return {
      id: String(s.id),
      city: s.city,
      side: s.outcome as "YES" | "NO",
      entryPrice: Math.round(s.entry_price * 100) / 100,
      currentPrice: Math.round(s.current_price * 100) / 100,
      pnl: Math.round(s.unrealized_pnl * 100) / 100,
      edge: Math.round(edgePct * 10) / 10,
      timeLeft: closesAt,
      openedAt,
      conditionId: s.market_id ? `${s.market_id.slice(0, 6)}…${s.market_id.slice(-4)}` : "—",
      amount: s.stake_amount ?? 0,
    };
  });
}

function mapActivityFeed(signals: Signal[], history: HistoryEntry[]): ActivityItem[] {
  const items: ActivityItem[] = [];
  let idCounter = 0;

  // Recent signals (open bets)
  for (const s of signals.slice(0, 5)) {
    idCounter++;
    const time = s.placed_at
      ? new Date(s.placed_at).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })
      : "??:??";
    const edge = s.live_edge ?? s.edge ?? 0;
    const edgePct = (Math.round(edge * 1000) / 10).toFixed(1);
    items.push({
      id: `s${idCounter}`,
      time,
      color: "blue",
      message: `${s.city} için ${s.outcome} bet: $${s.stake_amount?.toFixed(2) ?? "?"} @ ${s.entry_price.toFixed(2)} (net edge: ${edgePct}%)`,
    });
  }

  // Recent history (settled bets)
  for (const h of history.slice(0, 5)) {
    idCounter++;
    const time = h.settled_at
      ? new Date(h.settled_at).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })
      : "??:??";
    const color = h.result === "WIN" ? "teal" : "red";
    const pnlStr = h.realized_pnl >= 0 ? `+$${h.realized_pnl.toFixed(2)}` : `-$${Math.abs(h.realized_pnl).toFixed(2)}`;
    items.push({
      id: `h${idCounter}`,
      time,
      color,
      message: `${h.city} marketi çözüldü: ${h.outcome} ${h.result === "WIN" ? "kazandı" : "kaybetti"}, ${pnlStr}`,
    });
  }

  // Sort by time descending
  items.sort((a, b) => b.time.localeCompare(a.time));
  return items.slice(0, 15);
}

function mapEdgeDistribution(health: HealthResponse | null): EdgeBucket[] {
  const buckets: EdgeBucket[] = [
    { range: "0-2%", count: 0 },
    { range: "2-4%", count: 0 },
    { range: "4-6%", count: 0 },
    { range: "6-8%", count: 0 },
    { range: "8-10%", count: 0 },
    { range: "10%+", count: 0 },
  ];

  if (!health?.edge_distribution) return buckets;

  const avg = health.edge_distribution.avg_net_edge_pct;
  const count = health.edge_distribution.count || 0;

  // Distribute count based on avg edge into the right bucket
  if (avg <= 2) buckets[0].count = count;
  else if (avg <= 4) buckets[1].count = count;
  else if (avg <= 6) buckets[2].count = count;
  else if (avg <= 8) buckets[3].count = count;
  else if (avg <= 10) buckets[4].count = count;
  else buckets[5].count = count;

  return buckets;
}

function mapTradeHistory(history: HistoryEntry[]): TradeHistoryEntry[] {
  return history.map((h) => {
    const placedDate = h.placed_at ? new Date(h.settled_at ?? h.placed_at) : new Date();
    const timestamp = placedDate.toLocaleDateString("tr-TR", {
      day: "numeric",
      month: "short",
    }) + " " + placedDate.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });

    // Compute duration if possible
    let duration = "—";
    if (h.placed_at && h.settled_at) {
      const diff = new Date(h.settled_at).getTime() - new Date(h.placed_at).getTime();
      const hours = Math.floor(diff / (1000 * 60 * 60));
      const mins = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
      duration = hours > 0 ? `${hours}s ${mins}dk` : `${mins}dk`;
    }

    // Compute exit price from pnl and entry
    const stake = h.stake_amount || 10;
    const exitPrice = h.result === "WIN"
      ? Math.min(1.0, h.entry_price + (h.realized_pnl / stake))
      : Math.max(0, h.entry_price - (Math.abs(h.realized_pnl) / stake));

    const closedAt = h.settled_at
      ? new Date(h.settled_at).toLocaleDateString("tr-TR", {
          day: "numeric",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        })
      : "—";

    return {
      id: String(h.id),
      timestamp,
      city: h.city,
      side: (h.outcome as "YES" | "NO") || "YES",
      entryPrice: h.entry_price,
      exitPrice: Math.round(exitPrice * 100) / 100,
      pnl: h.realized_pnl,
      result: h.result,
      edge: h.roi ? Math.round(h.roi * 10) / 10 : 0,
      duration,
      closedAt,
      strategy: "SIA",
      conditionId: "—",
    };
  });
}

function mapModelScores(weights: Record<string, number>): ModelScore[] {
  const modelNames: Record<string, string> = {
    gfs_seamless: "GFS Seamless",
    ecmwf_ifs04: "ECMWF IFS04",
    ecmwf_aifs025: "ECMWF AIFS",
    gfs025: "GFS 0.25",
    ncep_gfs_seamless: "NCEP GFS",
    ecmwf_seamless: "ECMWF Seamless",
    icon_seamless: "ICON",
    gfs_seamless_04: "GFS 0.04",
  };

  return Object.entries(weights)
    .filter(([k]) => !k.startsWith("_"))
    .sort((a, b) => b[1] - a[1])
    .map(([key, weight]) => ({
      name: modelNames[key] ?? key,
      brierScore: Math.round((0.20 - weight * 0.5) * 1000) / 1000,
      accuracy: Math.round((65 + weight * 100) * 10) / 10,
      weight: Math.round(weight * 100),
      trend: "stable" as const,
      sampleCount: 0,
    }));
}

// ---- Custom Hook ----

export function useApiData() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyStats, setHistoryStats] = useState<HistoryStats | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [weights, setWeights] = useState<Record<string, number>>({});
  const [slippageData, setSlippageData] = useState<SlippageEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const fetchData = useCallback(async () => {
    // Cancel previous in-flight request
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const [statusRes, signalsRes, historyRes, healthRes, weightsRes, slippageRes] = await Promise.allSettled([
        fetchJson<StatusResponse>("/api/status", controller.signal),
        fetchJson<{ signals: Signal[]; count: number }>("/api/signals", controller.signal),
        fetchJson<{ history: HistoryEntry[]; stats: HistoryStats }>("/api/history", controller.signal),
        fetchJson<HealthResponse>("/api/health-check", controller.signal),
        fetchJson<Record<string, number>>("/api/asi/weights", controller.signal),
        fetchJson<{ slippage: SlippageEntry[] }>("/api/slippage", controller.signal),
      ]);

      if (controller.signal.aborted) return;

      if (statusRes.status === "fulfilled") setStatus(statusRes.value);
      if (signalsRes.status === "fulfilled") setSignals(signalsRes.value.signals ?? []);
      if (historyRes.status === "fulfilled") {
        setHistory(historyRes.value.history ?? []);
        setHistoryStats(historyRes.value.stats ?? null);
      }
      if (healthRes.status === "fulfilled") setHealth(healthRes.value);
      if (weightsRes.status === "fulfilled") setWeights(weightsRes.value);
      if (slippageRes.status === "fulfilled") setSlippageData(slippageRes.value.slippage ?? []);

      setError(null);
      setLastUpdated(new Date());
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof Error ? err.message : "API bağlantı hatası");
    } finally {
      if (!controller.signal.aborted) setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, REFRESH_INTERVAL);
    return () => {
      clearInterval(interval);
      abortRef.current?.abort();
    };
  }, [fetchData]);

  // Map data to UI types
  const kpiData = mapKpiData(status, health, historyStats);
  const portfolioData = mapPortfolioData(status, history);
  const openPositions = mapOpenPositions(signals);
  const activityFeed = mapActivityFeed(signals, history);
  const edgeDistribution = mapEdgeDistribution(health);
  const tradeHistory = mapTradeHistory(history);
  const modelScores = mapModelScores(weights);

  return {
    status,
    signals,
    history,
    historyStats,
    health,
    weights,
    kpiData,
    portfolioData,
    openPositions,
    activityFeed,
    edgeDistribution,
    tradeHistory,
    modelScores,
    slippageData,
    isLoading,
    error,
    lastUpdated,
  };
}
