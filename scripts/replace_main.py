with open("main.py", "rb") as f:
    content = f.read()

# Find the exact bytes we want to replace
search = b'logger = __import__("logging").getLogger(__name__)\r\n\r\n\r\n# \xe2\x94\x80\xe2\x94\x80\xe2\x94\x80 Port conflict prevention'
idx = content.find(search)
if idx >= 0:
    print(f"Found at {idx}")

    # The replacement - add AI layer loops before the port conflict section
    replacement = b'''logger = __import__("logging").getLogger(__name__)


# ==== AI Layer Loops ====
async def karpathy_weekly_loop(state):
    """Layer 1: Karpathy weekly optimization (Sunday 03:00 UTC)."""
    from asi_engine.karpathy_weekly import run_karpathy_weekly

    logger.info("KARPATHY WEEKLY: Starting weekly optimization")
    while state.is_running:
        try:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            # Run on Sunday at 03:00 UTC
            if now.weekday() == 6 and now.hour == 3 and now.minute < 10:
                logger.info("KARPATHY WEEKLY: Running weekly optimization")
                result = await asyncio.wait_for(
                    asyncio.to_thread(run_karpathy_weekly, rounds=6, use_llm=False, seed=42),
                    timeout=3600,
                )
                logger.info(f"KARPATHY WEEKLY: Completed - {result}")
            await asyncio.sleep(600)
        except asyncio.TimeoutError:
            logger.error("KARPATHY WEEKLY: Timeout")
        except Exception as e:
            logger.error(f"KARPATHY WEEKLY: Error - {e}")
            await asyncio.sleep(600)


async def asi_evolve_daily_loop(state):
    """Layer 2: ASI-Evolve daily optimization (02:00 UTC daily)."""
    from asi_engine.asi_evolve import run_asi_evolve_daily

    logger.info("ASI-EVOLVE DAILY: Starting daily optimization")
    last_run_date = None
    while state.is_running:
        try:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if now.hour == 2 and now.minute < 10 and last_run_date != now.date():
                logger.info("ASI-EVOLVE DAILY: Running daily optimization")
                result = await asyncio.wait_for(
                    asyncio.to_thread(run_asi_evolve_daily, generations=50, population_size=20),
                    timeout=1800,
                )
                logger.info(f"ASI-EVOLVE DAILY: Completed - {result}")
                last_run_date = now.date()
            await asyncio.sleep(600)
        except asyncio.TimeoutError:
            logger.error("ASI-EVOLVE DAILY: Timeout")
        except Exception as e:
            logger.error(f"ASI-EVOLVE DAILY: Error - {e}")
            await asyncio.sleep(600)


# \xe2\x94\x80\xe2\x94\x80\xe2\x94\x80 Port conflict prevention'''
    replacement = replacement.encode("utf-8")

    new_content = content[:idx] + replacement + content[idx + len(search) :]

    with open("main.py", "wb") as f:
        f.write(new_content)
    print("Replaced successfully")
else:
    print("Search pattern not found")
