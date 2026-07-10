"""Orchestrator for ASIAbot.

Triggers the complete closed-loop self-improving cycle:
Learn -> Design -> Experiment -> Analyze -> Deploy.
"""

import logging

from asi_engine.analyzer_agent import AnalyzerAgent
from asi_engine.backtest_simulator import BacktestSimulator
from asi_engine.cognition_base import CognitionBase
from asi_engine.researcher_agent import ResearcherAgent
from config.settings import bot_config, config
from utils.weights_store import save_strategy_params, save_weights

logger = logging.getLogger("ASI_ORCHESTRATOR")


class ASIAbotOrchestrator:
    """The central manager running the self-evolving ASI-Evolve framework."""

    def __init__(self):
        self.cognition_base = CognitionBase()
        self.researcher = ResearcherAgent(self.cognition_base)
        self.simulator = BacktestSimulator()
        self.analyzer = AnalyzerAgent(self.cognition_base)

    def run_evolution_pipeline(self, rounds: int = 5) -> dict:
        """Run the complete evolutionary research loop for N rounds.

        Each round generates a new model weight/risk parameters proposal,
        tests it over historical DB trades, distills causal insights, and
        persists the learning.
        """
        logger.info("==================================================")
        logger.info("   ASIAbot: STARTING AUTONOMOUS EVOLUTION LOOP    ")
        logger.info("==================================================")

        current_round_start = len(self.cognition_base.nodes)

        for r in range(1, rounds + 1):
            run_round = current_round_start + r
            logger.info("\n--- EVOLUTION ROUND %d ---", run_round)

            # 1. DESIGN: Propose a new hypothesis and parameter set
            hypothesis, proposed_params = self.researcher.propose_hypothesis(run_round)

            # 2. EXPERIMENT: Run the proposed parameters through backtest simulator
            results = self.simulator.run_backtest(proposed_params)

            # 3. ANALYZE & LEARN: Formulate causal insights and update memory
            node = self.analyzer.analyze_results(
                run_round, hypothesis, results, proposed_params
            )
            self.cognition_base.add_node(node)

        # 4. DEPLOY: Find the best parameters in all history and write to active config files
        best_params = self.cognition_base.get_best_parameters()

        logger.info("\n==================================================")
        logger.info("   ASIAbot: DEPLOYING BEST EVOLVED STRATEGY      ")
        logger.info("==================================================")

        best_weights = best_params["model_weights"]

        logger.info("Evolved Model Weights deployed:")
        for m, w in best_weights.items():
            logger.info("  %s: %.2f%%", m, w * 100)

        # Only sync blend_weight and model_weights; min_edge and kelly_fraction
        # are protected (KRT-6) and must not be touched by the SIA loop.
        logger.info("Syncing blend_weight=%.4f and model_weights to disk...", bot_config.strategy.blend_weight)

        # Update disk storage so next process restart loads them
        save_weights(best_weights)
        save_strategy_params({"blend_weight": float(bot_config.strategy.blend_weight)})

        # Dynamically apply to in-memory active configs
        config.MODEL_WEIGHTS = best_weights

        logger.info(
            "ASIAbot: Live trading models and configurations updated successfully!"
        )

        # Return best stats
        best_node = max(self.cognition_base.nodes, key=lambda n: n.roi)
        return {
            "round": best_node.round,
            "roi": best_node.roi,
            "brier_score": best_node.brier_score,
            "parameters": best_params,
        }
