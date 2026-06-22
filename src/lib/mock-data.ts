// ==========================================
// ASIAbot Dashboard — Mock Data & Types
// ==========================================

// ---- Types ----

export interface KpiData {
  portfolioValue: number;
  dailyPnl: number;
  openPositions: number;
  winRate: number;
  winRateLabel: string;
}

export interface PortfolioPoint {
  date: string;
  value: number;
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

// ---- Mock Data ----

export const kpiData: KpiData = {
  portfolioValue: 10045.2,
  dailyPnl: 45.2,
  openPositions: 6,
  winRate: 74.7,
  winRateLabel: "İyi",
};

export const portfolioData: PortfolioPoint[] = [
  { date: "16 Ara", value: 9250 },
  { date: "18 Ara", value: 9310 },
  { date: "20 Ara", value: 9280 },
  { date: "22 Ara", value: 9420 },
  { date: "24 Ara", value: 9380 },
  { date: "26 Ara", value: 9510 },
  { date: "28 Ara", value: 9470 },
  { date: "30 Ara", value: 9620 },
  { date: "01 Oca", value: 9580 },
  { date: "03 Oca", value: 9710 },
  { date: "05 Oca", value: 9650 },
  { date: "07 Oca", value: 9780 },
  { date: "09 Oca", value: 9740 },
  { date: "11 Oca", value: 9850 },
  { date: "13 Oca", value: 9920 },
  { date: "15 Oca", value: 10045 },
];

export const openPositions: OpenPosition[] = [
  { id: "1", city: "Dallas", side: "YES", entryPrice: 0.62, currentPrice: 0.71, pnl: 1.12, edge: 8.2, timeLeft: "2s 17dk" },
  { id: "2", city: "Miami", side: "NO", entryPrice: 0.38, currentPrice: 0.29, pnl: 0.9, edge: 6.5, timeLeft: "3s 34dk" },
  { id: "3", city: "New York", side: "YES", entryPrice: 0.55, currentPrice: 0.48, pnl: -1.05, edge: 4.1, timeLeft: "4s 51dk" },
  { id: "4", city: "Chicago", side: "YES", entryPrice: 0.7, currentPrice: 0.78, pnl: 0.64, edge: 9.8, timeLeft: "1s 8dk" },
  { id: "5", city: "Phoenix", side: "NO", entryPrice: 0.25, currentPrice: 0.19, pnl: 1.2, edge: 11.3, timeLeft: "2s 25dk" },
  { id: "6", city: "Denver", side: "YES", entryPrice: 0.45, currentPrice: 0.52, pnl: 0.84, edge: 5.7, timeLeft: "3s 42dk" },
];

export const activityFeed: ActivityItem[] = [
  { id: "a1", time: "14:30", color: "blue", message: "Dallas için YES bet açıldı: $12.50 @ 0.62 (net edge: 8.2%)" },
  { id: "a2", time: "14:25", color: "purple", message: "SIA ağırlık güncellemesi: ECMWF +2%, GFS -1%" },
  { id: "a3", time: "14:20", color: "gray", message: "5 yeni market tarandı, 2'si filtreli (edge düşük)" },
  { id: "a4", time: "13:45", color: "blue", message: "Miami için NO bet açıldı: $10.00 @ 0.38 (net edge: 6.5%)" },
  { id: "a5", time: "13:30", color: "purple", message: "Model uyumu: ECMWF/GFS/HRRR ortalaması hesaplandı" },
  { id: "a6", time: "13:00", color: "orange", message: "Günlük performans: 2 win, 1 loss, net PnL +$8.40" },
  { id: "a7", time: "12:45", color: "teal", message: "Los Angeles marketi çözüldü: YES kazandı, +$3.20" },
  { id: "a8", time: "12:30", color: "red", message: "Seattle marketi çözüldü: NO kaybetti, -$1.50" },
  { id: "a9", time: "12:10", color: "blue", message: "New York için YES bet açıldı: $15.00 @ 0.55 (net edge: 4.1%)" },
];

export const edgeDistribution: EdgeBucket[] = [
  { range: "0-2%", count: 3 },
  { range: "2-4%", count: 5 },
  { range: "4-6%", count: 9 },
  { range: "6-8%", count: 7 },
  { range: "8-10%", count: 10 },
  { range: "10%+", count: 4 },
];