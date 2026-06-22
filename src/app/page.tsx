"use client";

import React, { useState, useEffect } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  BarChart,
  Bar,
  ResponsiveContainer,
} from "recharts";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  kpiData,
  portfolioData,
  openPositions,
  activityFeed,
  edgeDistribution,
  type ActivityItem,
} from "@/lib/mock-data";
import { TrendingUp, Moon, Wallet, Activity, Target, BarChart3 } from "lucide-react";

// ---- Color constants ----
const TEAL = "#20B2AA";
const TEAL_LIGHT = "rgba(32, 178, 170, 0.15)";
const RED = "#FF6B6B";
const RED_LIGHT = "rgba(255, 107, 107, 0.15)";
const TEXT_PRIMARY = "#374151";
const TEXT_MUTED = "#9CA3AF";
const BORDER = "#E5E7EB";

// ---- Activity dot color map ----
const dotColorMap: Record<ActivityItem["color"], string> = {
  blue: "#3B82F6",
  purple: "#8B5CF6",
  gray: "#9CA3AF",
  orange: "#F59E0B",
  teal: "#20B2AA",
  red: "#FF6B6B",
};

// ---- Formatters ----
function fmtUsd(v: number) {
  const sign = v >= 0 ? "+" : "";
  return `${sign}$${v.toFixed(2)}`;
}

// ---- Custom tooltip for portfolio chart ----
function PortfolioTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ value: number }>; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 shadow-lg text-xs">
      <p className="font-medium text-gray-500 mb-1">{label}</p>
      <p className="font-mono font-semibold" style={{ color: TEAL }}>
        ${payload[0].value.toLocaleString("en-US", { minimumFractionDigits: 0 })}
      </p>
    </div>
  );
}

// ---- Custom tooltip for edge chart ----
function EdgeTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ value: number }>; label?: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2 shadow-lg text-xs">
      <p className="font-medium text-gray-500 mb-1">Edge: {label}</p>
      <p className="font-mono font-semibold" style={{ color: "#22C55E" }}>
        {payload[0].value} trade
      </p>
    </div>
  );
}

// ---- Client-only wrapper for Recharts ----
function ClientOnly({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => { setMounted(true); }, []);
  if (!mounted) {
    return (
      <div className="w-full flex items-center justify-center" style={{ minHeight: 200 }}>
        <span className="text-xs text-gray-400">Yükleniyor...</span>
      </div>
    );
  }
  return <>{children}</>;
}

// ==========================================
// Main Dashboard
// ==========================================
export default function DashboardPage() {
  return (
    <div className="min-h-screen flex flex-col bg-gray-50/50" style={{ fontFamily: "'Inter', system-ui, sans-serif" }}>
      {/* ---- HEADER ---- */}
      <header className="sticky top-0 z-50 bg-white border-b" style={{ borderColor: BORDER }}>
        <div className="max-w-7xl mx-auto flex items-center justify-between px-4 sm:px-6 h-14">
          <div className="flex items-center gap-3">
            <h1 className="text-lg font-bold tracking-tight" style={{ color: TEXT_PRIMARY }}>
              ASIAbot
            </h1>
            <div className="flex items-center gap-1.5">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
              </span>
              <span className="text-xs font-medium text-green-600">ÇALIŞIYOR</span>
            </div>
          </div>
          <button className="p-2 rounded-md hover:bg-gray-100 transition-colors" aria-label="Dark mode">
            <Moon className="h-4 w-4 text-gray-500" />
          </button>
        </div>
      </header>

      {/* ---- MAIN CONTENT ---- */}
      <main className="flex-1 max-w-7xl mx-auto w-full px-4 sm:px-6 py-6 space-y-6">
        {/* KPI Cards */}
        <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Portfolio Value */}
          <Card className="py-4 gap-2 shadow-sm" style={{ borderColor: BORDER }}>
            <CardContent className="px-4 pb-0 pt-0">
              <p className="text-xs font-medium" style={{ color: TEXT_MUTED }}>Portföy Değeri</p>
              <div className="flex items-center gap-2 mt-1">
                <Wallet className="h-4 w-4" style={{ color: TEAL }} />
                <span className="text-xl font-bold tabular-nums" style={{ color: TEAL }}>
                  ${kpiData.portfolioValue.toLocaleString("en-US", { minimumFractionDigits: 2 })}
                </span>
              </div>
            </CardContent>
          </Card>

          {/* Daily PnL */}
          <Card className="py-4 gap-2 shadow-sm" style={{ borderColor: BORDER }}>
            <CardContent className="px-4 pb-0 pt-0">
              <p className="text-xs font-medium" style={{ color: TEXT_MUTED }}>Bugünkü PnL</p>
              <div className="flex items-center gap-2 mt-1">
                <TrendingUp className="h-4 w-4 text-green-500" />
                <span className="text-xl font-bold tabular-nums text-green-600">
                  ▲ {fmtUsd(kpiData.dailyPnl)}
                </span>
              </div>
            </CardContent>
          </Card>

          {/* Open Positions */}
          <Card className="py-4 gap-2 shadow-sm" style={{ borderColor: BORDER }}>
            <CardContent className="px-4 pb-0 pt-0">
              <p className="text-xs font-medium" style={{ color: TEXT_MUTED }}>Açık Bahisler</p>
              <div className="flex items-center gap-2 mt-1">
                <Activity className="h-4 w-4" style={{ color: TEXT_PRIMARY }} />
                <span className="text-xl font-bold tabular-nums" style={{ color: TEXT_PRIMARY }}>
                  {kpiData.openPositions}
                </span>
              </div>
            </CardContent>
          </Card>

          {/* Win Rate */}
          <Card className="py-4 gap-2 shadow-sm" style={{ borderColor: BORDER }}>
            <CardContent className="px-4 pb-0 pt-0">
              <p className="text-xs font-medium" style={{ color: TEXT_MUTED }}>Win Rate</p>
              <div className="flex items-center gap-2 mt-1">
                <Target className="h-4 w-4" style={{ color: TEXT_PRIMARY }} />
                <span className="text-xl font-bold tabular-nums" style={{ color: TEXT_PRIMARY }}>
                  {kpiData.winRate}%
                </span>
                <Badge
                  className="text-[10px] px-1.5 py-0 h-5 font-semibold"
                  style={{ backgroundColor: TEAL_LIGHT, color: TEAL, border: `1px solid ${TEAL}33` }}
                >
                  {kpiData.winRateLabel}
                </Badge>
              </div>
            </CardContent>
          </Card>
        </section>

        {/* Portfolio Value Chart */}
        <Card className="shadow-sm py-4 gap-3" style={{ borderColor: BORDER }}>
          <CardHeader className="pb-0 pt-0 px-5">
            <div className="flex items-center gap-2">
              <BarChart3 className="h-4 w-4" style={{ color: TEXT_MUTED }} />
              <CardTitle className="text-sm font-semibold" style={{ color: TEXT_PRIMARY }}>
                Portföy Değeri (30 Gün)
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="px-4">
            <ClientOnly>
              <div className="w-full" style={{ height: 280 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={portfolioData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
                    <defs>
                      <linearGradient id="portfolioGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor={TEAL} stopOpacity={0.25} />
                        <stop offset="95%" stopColor={TEAL} stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke={BORDER} vertical={false} />
                    <XAxis
                      dataKey="date"
                      tick={{ fontSize: 11, fill: TEXT_MUTED }}
                      axisLine={{ stroke: BORDER }}
                      tickLine={false}
                    />
                    <YAxis
                      domain={[9200, 10100]}
                      tick={{ fontSize: 11, fill: TEXT_MUTED }}
                      axisLine={false}
                      tickLine={false}
                      tickFormatter={(v: number) => `$${(v / 1000).toFixed(1)}k`}
                      width={45}
                    />
                    <Tooltip content={<PortfolioTooltip />} />
                    <Area
                      type="monotone"
                      dataKey="value"
                      stroke={TEAL}
                      strokeWidth={2}
                      fill="url(#portfolioGradient)"
                      dot={false}
                      activeDot={{ r: 4, stroke: TEAL, strokeWidth: 2, fill: "#fff" }}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </ClientOnly>
          </CardContent>
        </Card>

        {/* Open Positions + Activity Feed */}
        <section className="grid grid-cols-1 lg:grid-cols-5 gap-4">
          {/* Open Positions Table — 3/5 */}
          <Card className="lg:col-span-3 shadow-sm py-4 gap-3" style={{ borderColor: BORDER }}>
            <CardHeader className="pb-0 pt-0 px-5">
              <CardTitle className="text-sm font-semibold" style={{ color: TEXT_PRIMARY }}>
                Açık Pozisyonlar
              </CardTitle>
            </CardHeader>
            <CardContent className="px-3">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: TEXT_MUTED }}>Şehir</TableHead>
                    <TableHead className="text-[11px] font-semibold uppercase tracking-wider" style={{ color: TEXT_MUTED }}>Taraf</TableHead>
                    <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-right" style={{ color: TEXT_MUTED }}>Giriş</TableHead>
                    <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-right" style={{ color: TEXT_MUTED }}>Güncel</TableHead>
                    <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-right" style={{ color: TEXT_MUTED }}>PnL</TableHead>
                    <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-right" style={{ color: TEXT_MUTED }}>Edge</TableHead>
                    <TableHead className="text-[11px] font-semibold uppercase tracking-wider text-right" style={{ color: TEXT_MUTED }}>Kalan</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {openPositions.map((pos) => (
                    <TableRow key={pos.id}>
                      <TableCell className="font-medium text-sm" style={{ color: TEXT_PRIMARY }}>
                        {pos.city}
                      </TableCell>
                      <TableCell>
                        <Badge
                          className="text-[10px] font-bold px-2 py-0.5 h-5"
                          style={{
                            backgroundColor: pos.side === "YES" ? TEAL_LIGHT : RED_LIGHT,
                            color: pos.side === "YES" ? TEAL : RED,
                            border: `1px solid ${pos.side === "YES" ? TEAL : RED}33`,
                          }}
                        >
                          {pos.side}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm tabular-nums" style={{ color: TEXT_PRIMARY }}>
                        {pos.entryPrice.toFixed(2)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm tabular-nums" style={{ color: TEXT_PRIMARY }}>
                        {pos.currentPrice.toFixed(2)}
                      </TableCell>
                      <TableCell
                        className="text-right font-mono text-sm font-semibold tabular-nums"
                        style={{ color: pos.pnl >= 0 ? TEAL : RED }}
                      >
                        {fmtUsd(pos.pnl)}
                      </TableCell>
                      <TableCell className="text-right font-mono text-sm tabular-nums" style={{ color: TEXT_PRIMARY }}>
                        {pos.edge}%
                      </TableCell>
                      <TableCell className="text-right text-sm tabular-nums" style={{ color: TEXT_MUTED }}>
                        {pos.timeLeft}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {/* Activity Feed — 2/5 */}
          <Card className="lg:col-span-2 shadow-sm py-4 gap-3" style={{ borderColor: BORDER }}>
            <CardHeader className="pb-0 pt-0 px-5">
              <CardTitle className="text-sm font-semibold" style={{ color: TEXT_PRIMARY }}>
                Aktivite Akışı
              </CardTitle>
            </CardHeader>
            <CardContent className="px-4">
              <div className="space-y-0 max-h-[340px] overflow-y-auto pr-1 custom-scroll">
                {activityFeed.map((item) => (
                  <div key={item.id} className="flex gap-3 py-2.5 border-b last:border-0" style={{ borderColor: `${BORDER}80` }}>
                    <div className="flex flex-col items-center gap-1 pt-1 shrink-0">
                      <div className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: dotColorMap[item.color] }} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs leading-relaxed" style={{ color: TEXT_PRIMARY }}>
                        {item.message}
                      </p>
                    </div>
                    <span className="text-[10px] tabular-nums shrink-0 pt-0.5" style={{ color: TEXT_MUTED }}>
                      {item.time}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </section>

        {/* Edge Distribution Chart */}
        <Card className="shadow-sm py-4 gap-3" style={{ borderColor: BORDER }}>
          <CardHeader className="pb-0 pt-0 px-5">
            <CardTitle className="text-sm font-semibold" style={{ color: TEXT_PRIMARY }}>
              Edge Dağılımı
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4">
            <ClientOnly>
              <div className="w-full" style={{ height: 220 }}>
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={edgeDistribution} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={BORDER} vertical={false} />
                    <XAxis
                      dataKey="range"
                      tick={{ fontSize: 11, fill: TEXT_MUTED }}
                      axisLine={{ stroke: BORDER }}
                      tickLine={false}
                    />
                    <YAxis
                      tick={{ fontSize: 11, fill: TEXT_MUTED }}
                      axisLine={false}
                      tickLine={false}
                      width={30}
                    />
                    <Tooltip content={<EdgeTooltip />} cursor={{ fill: "rgba(0,0,0,0.04)" }} />
                    <Bar dataKey="count" fill="#22C55E" radius={[4, 4, 0, 0]} barSize={40} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </ClientOnly>
          </CardContent>
        </Card>
      </main>

      {/* ---- FOOTER ---- */}
      <footer className="mt-auto py-4 text-center">
        <p className="text-xs" style={{ color: TEXT_MUTED }}>
          ASIAbot — Polymarket Hava Ticaret Botu - SIA Modeli ile Otomatik İşlem
        </p>
      </footer>
    </div>
  );
}