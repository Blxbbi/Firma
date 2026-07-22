import random
from dataclasses import dataclass
from typing import Tuple

@dataclass
class LoadProfile:
    name: str
    transitions_per_flight: int
    artifact_count: int
    artifact_size_bytes: int
    llm_delay_range: Tuple[float, float]
    inter_transition_delay: Tuple[float, float] # Gap between messages
    task_pool_multiplier: int # Concurrency multiplier for task pool
    sandbox_mode: str # "noop", "minimal", "full"

# CLASS A: CPU-BOUND (Kernel/CAS Stress)
CPUBoundProfile = LoadProfile(
    name="cpu",
    transitions_per_flight=1, # One clean transition per task
    artifact_count=1,
    artifact_size_bytes=1024, # 1KB
    llm_delay_range=(0.0, 0.0),
    inter_transition_delay=(0.05, 0.1),
    task_pool_multiplier=50, # Reduced to avoid SQLite lock during setup
    sandbox_mode="noop"
)


# CLASS A-HOTSPOT: Maximum Contention
CPUHotspotProfile = LoadProfile(
    name="cpu_hotspot",
    transitions_per_flight=1,
    artifact_count=1,
    artifact_size_bytes=1024,
    llm_delay_range=(0.0, 0.0),
    inter_transition_delay=(0.0, 0.0),
    task_pool_multiplier=1, # High contention
    sandbox_mode="noop"
)


# CLASS B: IO-BOUND (Real-world Simulation)
IOBoundProfile = LoadProfile(
    name="io",
    transitions_per_flight=4,
    artifact_count=5,
    artifact_size_bytes=1024 * 100, # 100KB
    llm_delay_range=(0.5, 2.0),
    inter_transition_delay=(0.1, 0.3),
    task_pool_multiplier=5,
    sandbox_mode="full"
)

# CLASS C: TRANSITION-HEAVY (Governance Stress)
TransitionHeavyProfile = LoadProfile(
    name="transition",
    transitions_per_flight=12,
    artifact_count=1,
    artifact_size_bytes=1024,
    llm_delay_range=(0.0, 0.0),
    inter_transition_delay=(0.02, 0.05),
    task_pool_multiplier=10,
    sandbox_mode="minimal"
)

PROFILES = {
    "cpu": CPUBoundProfile,
    "cpu_hotspot": CPUHotspotProfile,
    "io": IOBoundProfile,
    "transition": TransitionHeavyProfile
}


def get_profile(name: str) -> LoadProfile:
    return PROFILES.get(name, CPUBoundProfile)
