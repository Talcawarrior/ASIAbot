"""ASIAbot Telegram Bot — monitor & control via Telegram."""

import logging
import os

import httpx
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("TELEGRAM_BOT")

API_BASE = os.getenv("ASIABOT_API", "http://127.0.0.1:8091")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "REDACTED_TELEGRAM_TOKEN")


# ── HTTP helpers ──────────────────────────────────────────────────────────────

async def api_get(path: str) -> dict | str:
    """GET from ASIAbot API, return parsed JSON or error string."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{API_BASE}{path}")
            r.raise_for_status()
            return r.json()
    except httpx.HTTPError as e:
        return f"API hatasi: {e}"
    except Exception as e:
        return f"Hata: {e}"


# ── Handlers ──────────────────────────────────────────────────────────────────

async def start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *ASIAbot Telegram*\n\n"
        "Komutlar:\n"
        "/status — Bot durumu\n"
        "/health — Saglik kontrolu\n"
        "/portfolio — Portfoy/Equity\n"
        "/bets — Son bahisler\n"
        "/markets — Aktif marketler\n"
        "/signals — Sinyaller\n"
        "/weights — SIA agirliklari\n"
        "/help — Yardim",
    )


async def cmd_status(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    data = await api_get("/api/status")
    if isinstance(data, str):
        await update.message.reply_text(f"❌ {data}")
        return

    msg = (
        f"📊 *ASIAbot Status*\n"
        f"• Calisiyor: {data.get('is_running', '?')}\n"
        f"• Kilitli: {data.get('locked', '?')}\n"
        f"• Portfoy: ${data.get('portfolio_value', '?'):.2f}\n"
        f"• Acik pozisyon: {data.get('open_positions', 0)}\n"
        f"• Toplam bet: {data.get('total_bets', 0)}\n"
    )
    await update.message.reply_text(msg)


async def cmd_health(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    data = await api_get("/api/health-check")
    if isinstance(data, str):
        await update.message.reply_text(f"❌ {data}")
        return

    msg = (
        f"💚 *Health Check*\n"
        f"• DB: {'✅' if data.get('database', False) else '❌'}\n"
        f"• API: {'✅' if data.get('api', False) else '❌'}\n"
        f"• SIA: {'✅' if data.get('sia', False) else '❌'}\n"
        f"• Polymarket: {'✅' if data.get('polymarket', False) else '❌'}\n"
    )
    await update.message.reply_text(msg)


async def cmd_portfolio(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    data = await api_get("/api/equity-curve")
    if isinstance(data, str):
        await update.message.reply_text(f"❌ {data}")
        return
    if not data or not isinstance(data, list):
        await update.message.reply_text("Portfoy verisi yok.")
        return

    last = data[-1] if data else {}
    pnl = last.get("pnl", 0)
    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"

    points = len(data)
    high = max(d.get("equity", 0) for d in data) if data else 0
    low = min(d.get("equity", 0) for d in data) if data else 0

    msg = (
        f"💰 *Portfoy*\n"
        f"• Equity: ${last.get('equity', 0):.2f}\n"
        f"• PnL: {pnl_str}\n"
        f"• ROI: {last.get('roi_pct', 0):.2f}%\n"
        f"• Veri noktasi: {points}\n"
        f"• Peak: ${high:.2f} / Dip: ${low:.2f}\n"
    )
    await update.message.reply_text(msg)


async def cmd_bets(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    data = await api_get("/api/bets?limit=5")
    if isinstance(data, str):
        await update.message.reply_text(f"❌ {data}")
        return

    bets = data if isinstance(data, list) else data.get("bets", [])
    if not bets:
        await update.message.reply_text("Bahis yok.")
        return

    lines = ["🎲 *Son 5 Bahis*"]
    for b in bets[:5]:
        status = b.get("status", "?")
        side = b.get("side", "?")
        amount = b.get("amount", 0)
        pnl = b.get("realized_pnl")
        pnl_str = f" | PnL: ${pnl:.2f}" if pnl is not None else ""
        lines.append(f"`{status}` ${amount:.2f} {side}{pnl_str}")

    await update.message.reply_text("\n".join(lines))


async def cmd_markets(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    data = await api_get("/api/markets")
    if isinstance(data, str):
        await update.message.reply_text(f"❌ {data}")
        return

    markets = data if isinstance(data, list) else data.get("markets", [])
    if not markets:
        await update.message.reply_text("Aktif market yok.")
        return

    lines = ["🌤 *Aktif Marketler*"]
    for m in markets[:8]:
        q = m.get("question", "?")[:40]
        p = m.get("price", "?")
        loc = m.get("location", m.get("city", ""))
        lines.append(f"• {q} — ${p} ({loc})")

    if len(markets) > 8:
        lines.append(f"...ve {len(markets)-8} daha")
    await update.message.reply_text("\n".join(lines))


async def cmd_signals(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    data = await api_get("/api/signals")
    if isinstance(data, str):
        await update.message.reply_text(f"❌ {data}")
        return

    signals = data if isinstance(data, list) else data.get("signals", [])
    if not signals:
        await update.message.reply_text("Sinyal yok.")
        return

    lines = ["📡 *Sinyaller*"]
    for s in signals[:6]:
        city = s.get("city", "?")
        side = s.get("side", "?")
        edge = s.get("edge", 0)
        prob = s.get("probability", 0)
        lines.append(f"• {city}: {side} edge={edge:.1%} prob={prob:.1%}")

    if len(signals) > 6:
        lines.append(f"...ve {len(signals)-6} daha")
    await update.message.reply_text("\n".join(lines))


async def cmd_weights(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    data = await api_get("/api/asi/weights")
    if isinstance(data, str):
        await update.message.reply_text(f"❌ {data}")
        return

    w = data if isinstance(data, dict) else {}
    lines = ["⚖️ *SIA Model Agirliklari*"]
    for model, pct in sorted(w.items(), key=lambda x: -x[1]):
        lines.append(f"• {model}: {pct*100:.2f}%")
    await update.message.reply_text("\n".join(lines))


async def cmd_help(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    await start(update, _ctx)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("bets", cmd_bets))
    app.add_handler(CommandHandler("markets", cmd_markets))
    app.add_handler(CommandHandler("signals", cmd_signals))
    app.add_handler(CommandHandler("weights", cmd_weights))
    app.add_handler(CommandHandler("help", cmd_help))

    logger.info("ASIAbot Telegram bot baslatiliyor...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
