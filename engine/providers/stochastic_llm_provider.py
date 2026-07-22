import asyncio
import random
import logging
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass

from engine.services.telemetry import telemetry
from .base import BaseLLMProvider

logger = logging.getLogger("engine.providers.stochastic")

@dataclass
class ProviderConfig:
    # Latency parameters (Log-Normal)
    # mu=1.0, sigma=0.5 approx: p50=2.7s, p95=6.2s
    mu: float = 1.0
    sigma: float = 0.5
    
    # Congestion penalty: latency += inflight^2 * coefficient
    congestion_coeff: float = 0.01
    
    # Error probabilities
    p_error_normal: float = 0.01    # 1% error in normal mode
    p_error_burst: float = 0.50     # 50% error in burst mode
    p_enter_burst: float = 0.30     # 30% chance to enter burst mode on error
    p_exit_burst: float = 0.20      # 20% chance to recover from burst mode per request
    
    # Timeout threshold
    timeout_limit: float = 30.0

class StochasticLLMProvider(BaseLLMProvider):
    """
    A provider that simulates realistic LLM API behavior:
    - Log-normal latency (Heavy Tail)
    - Congestion-based latency penalty (Inflight requests)
    - Burst-error modeling (Markov-like 429 clusters)
    """
    def __init__(self, config: ProviderConfig = ProviderConfig()):
        self.config = config
        self.inflight_requests = 0
        self.is_bursting = False
        
    async def _generate(self, system_prompt: str, user_prompt: str, timeout: int) -> str:
        """
        Simulates an LLM generation call with stochastic behavior.
        """
        self.inflight_requests += 1
        telemetry.set_gauge("llm_inflight", self.inflight_requests)
        telemetry.increment("llm_request")
        start_time = time.time()
        try:
            # 1. Determine if an error occurs (Burst Model)
            error_prob = self.config.p_error_burst if self.is_bursting else self.config.p_error_normal
            
            if random.random() < error_prob:
                # Transition to burst mode?
                if not self.is_bursting and random.random() < self.config.p_enter_burst:
                    self.is_bursting = True
                    logger.warning("StochasticProvider: ENTERING BURST MODE (Rate Limit Cluster)")
                
                # Simulate a 429 Rate Limit or 500 Error
                error_type = "429" if random.random() < 0.8 else "500"
                telemetry.increment("llm_error")
                raise Exception(f"LLM_API_ERROR_{error_type}")

            # If we were bursting, we might recover now
            if self.is_bursting and random.random() < self.config.p_exit_burst:
                self.is_bursting = False
                logger.info("StochasticProvider: RECOVERED from burst mode")

            # 2. Calculate Latency
            # Base log-normal latency
            base_latency = random.lognormvariate(self.config.mu, self.config.sigma)
            
            # Add congestion penalty based on current inflight requests
            penalty = (self.inflight_requests ** 2) * self.config.congestion_coeff
            final_latency = base_latency + penalty
            
            # 3. Simulate the wait
            if final_latency > self.config.timeout_limit:
                await asyncio.sleep(self.config.timeout_limit)
                telemetry.increment("llm_error")
                raise asyncio.TimeoutError("LLM_API_TIMEOUT")
            
            await asyncio.sleep(final_latency)
            
            latency_ms = (time.time() - start_time) * 1000
            telemetry.observe("llm_latency_ms", latency_ms)
            
            return "Stochastic generated content"
            
        finally:
            self.inflight_requests -= 1
            telemetry.set_gauge("llm_inflight", self.inflight_requests)

    async def _generate_json(self, system_prompt: str, user_prompt: str, schema: Dict[str, Any], timeout: int) -> Dict[str, Any]:
        # For simplicity, reuse _generate and wrap in a dummy JSON
        content = await self._generate(system_prompt, user_prompt, timeout)
        return {"response": content, "status": "SUCCESS"}

# Global instance for testing
stochastic_provider = StochasticLLMProvider()
