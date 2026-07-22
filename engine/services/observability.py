import logging
import numpy as np
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from engine.models import SubmissionLog, SubmissionOutcome, Task, SystemMetric
from engine.repository import MessageRepository

logger = logging.getLogger(__name__)

class ObservabilityService:
    """
    ObservabilityService 2.0: Async high-fidelity system and model analytics.
    SRE-Grade: All metrics are scoped by run_id to prevent test contamination.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = MessageRepository()

    async def get_schema_compliance_rate(self, run_id: Optional[str] = None, project_id: Optional[str] = None) -> float:
        """KPI: 1 - (SCHEMA_ERROR / TOTAL_SUBMISSIONS)"""
        stmt = select(func.count()).select_from(SubmissionLog)
        if run_id:
            stmt = stmt.filter(SubmissionLog.run_id == run_id)
        if project_id:
            stmt = stmt.filter(SubmissionLog.project_id == project_id)
        
        total = (await self.session.execute(stmt)).scalar() or 0
        if total == 0:
            return 1.0
        
        stmt_err = select(func.count()).select_from(SubmissionLog).filter(
            SubmissionLog.outcome == SubmissionOutcome.SCHEMA_ERROR.value
        )
        if run_id:
            stmt_err = stmt_err.filter(SubmissionLog.run_id == run_id)
        if project_id:
            stmt_err = stmt_err.filter(SubmissionLog.project_id == project_id)
            
        errors = (await self.session.execute(stmt_err)).scalar() or 0
        return 1.0 - (errors / total)

    async def get_convergence_rate(self, run_id: Optional[str] = None, project_id: Optional[str] = None) -> float:
        """KPI: AVG(iteration_number where outcome == SUCCESS)"""
        stmt = select(func.avg(SubmissionLog.iteration_number)).filter(
            SubmissionLog.outcome == SubmissionOutcome.SUCCESS.value
        )
        if run_id:
            stmt = stmt.filter(SubmissionLog.run_id == run_id)
        if project_id:
            stmt = stmt.filter(SubmissionLog.project_id == project_id)
            
        result = (await self.session.execute(stmt)).scalar()
        return float(result) if result else 0.0

    async def get_failure_distribution(self, run_id: Optional[str] = None, project_id: Optional[str] = None) -> Dict[str, int]:
        """KPI: GROUP BY error_code ORDER BY count DESC"""
        stmt = select(SubmissionLog.error_code, func.count(SubmissionLog.id)).filter(
            SubmissionLog.error_code != None
        ).group_by(SubmissionLog.error_code)
        
        if run_id:
            stmt = stmt.filter(SubmissionLog.run_id == run_id)
        if project_id:
            stmt = stmt.filter(SubmissionLog.project_id == project_id)
            
        result = await self.session.execute(stmt)
        return {code: count for code, count in result.all()}

    async def get_average_duration(self, run_id: Optional[str] = None, project_id: Optional[str] = None) -> float:
        """KPI: AVG(duration_ms)"""
        stmt = select(func.avg(SubmissionLog.duration_ms))
        if run_id:
            stmt = stmt.filter(SubmissionLog.run_id == run_id)
        if project_id:
            stmt = stmt.filter(SubmissionLog.project_id == project_id)
            
        result = (await self.session.execute(stmt)).scalar()
        return float(result) if result else 0.0

    async def get_model_performance_comparison(self, run_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Compares different models based on compliance and convergence."""
        stmt = select(SubmissionLog.model_name).distinct()
        if run_id:
            stmt = stmt.filter(SubmissionLog.run_id == run_id)
            
        result = await self.session.execute(stmt)
        model_names = result.scalars().all()
        comparison = []
        
        for name in model_names:
            if not name: continue
            
            stmt_total = select(func.count()).select_from(SubmissionLog).filter(SubmissionLog.model_name == name)
            if run_id:
                stmt_total = stmt_total.filter(SubmissionLog.run_id == run_id)
            total = (await self.session.execute(stmt_total)).scalar() or 0
            
            stmt_err = select(func.count()).select_from(SubmissionLog).filter(
                SubmissionLog.model_name == name, 
                SubmissionLog.outcome == SubmissionOutcome.SCHEMA_ERROR.value
            )
            if run_id:
                stmt_err = stmt_err.filter(SubmissionLog.run_id == run_id)
            errors = (await self.session.execute(stmt_err)).scalar() or 0
            
            stmt_conv = select(func.avg(SubmissionLog.iteration_number)).filter(
                SubmissionLog.model_name == name,
                SubmissionLog.outcome == SubmissionOutcome.SUCCESS.value
            )
            if run_id:
                stmt_conv = stmt_conv.filter(SubmissionLog.run_id == run_id)
            conv = (await self.session.execute(stmt_conv)).scalar()
            
            comparison.append({
                "model": name,
                "compliance_rate": 1.0 - (errors / total) if total > 0 else 0,
                "avg_iterations": float(conv) if conv else 0,
                "total_attempts": total
            })
            
        return comparison

    async def get_iteration_histogram(self, run_id: Optional[str] = None) -> Dict[int, int]:
        stmt = select(SubmissionLog.iteration_number, func.count(SubmissionLog.id)).group_by(SubmissionLog.iteration_number).order_by(SubmissionLog.iteration_number)
        if run_id:
            stmt = stmt.filter(SubmissionLog.run_id == run_id)
        result = await self.session.execute(stmt)
        return {iter_num: count for iter_num, count in result.all()}

    # --- SRE / Scaling Metrics ---

    async def get_system_metric_stats(self, metric_name: str, run_id: Optional[str] = None) -> Dict[str, float]:
        """Fetches avg, p95, p99, and max for a specific system metric."""
        stmt = select(SystemMetric.value).filter(SystemMetric.metric_name == metric_name)
        if run_id:
            stmt = stmt.filter(SystemMetric.run_id == run_id)
        
        result = await self.session.execute(stmt)
        values = result.scalars().all()
        
        if not values:
            return {"avg": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}
            
        return {
            "avg": float(np.mean(values)),
            "p95": float(np.percentile(values, 95)),
            "p99": float(np.percentile(values, 99)),
            "max": float(np.max(values))
        }

    async def get_cas_stats(self, run_id: Optional[str] = None) -> Dict[str, float]:
        """Calculates total CAS attempts and reject rate."""
        stmt_att = select(func.count()).select_from(SystemMetric).filter(SystemMetric.metric_name == "cas_attempt")
        if run_id:
            stmt_att = stmt_att.filter(SystemMetric.run_id == run_id)
            
        stmt_rej = select(func.count()).select_from(SystemMetric).filter(SystemMetric.metric_name == "cas_reject")
        if run_id:
            stmt_rej = stmt_rej.filter(SystemMetric.run_id == run_id)
        
        attempts = (await self.session.execute(stmt_att)).scalar() or 0
        rejects = (await self.session.execute(stmt_rej)).scalar() or 0
        
        return {
            "total_attempts": attempts,
            "rejects": rejects,
            "reject_rate": (rejects / attempts) if attempts > 0 else 0.0
        }

    async def generate_scaling_report(self, concurrency_level: int, run_id: str) -> Dict[str, Any]:
        """
        Generates the structured Scaling Report Format scoped by run_id.
        """
        # 1. Completion & Stability
        stmt_total = select(func.count()).select_from(Task).filter(Task.run_id == run_id)
        total_tasks = (await self.session.execute(stmt_total)).scalar() or 0
        
        stmt_comp = select(func.count()).select_from(Task).filter(
            Task.run_id == run_id, 
            Task.execution_phase == "COMPLETE"
        )
        completed_tasks = (await self.session.execute(stmt_comp)).scalar() or 0
        
        stability = (completed_tasks / total_tasks) if total_tasks > 0 else 0.0
        
        # 2. Duration Metrics
        stmt_dur = select(SubmissionLog.duration_ms).filter(
            SubmissionLog.run_id == run_id, 
            SubmissionLog.duration_ms != None
        )
        durations = (await self.session.execute(stmt_dur)).scalars().all()
        
        avg_dur = float(np.mean(durations)) if durations else 0.0
        p95_dur = float(np.percentile(durations, 95)) if durations else 0.0
        
        # 3. CAS Metrics
        cas = await self.get_cas_stats(run_id=run_id)
        
        # 4. Loop Lag
        lag_stats = await self.get_system_metric_stats("loop_lag", run_id=run_id)
        
        # 5. DB Write Latency
        db_stats = await self.get_system_metric_stats("db_write_latency", run_id=run_id)
        
        # Kipppunkt Logic: 2+ conditions
        conditions = [
            p95_dur > (2.5 * avg_dur if avg_dur > 0 else 1000),
            stability < 0.95,
            cas["reject_rate"] > 0.10,
            lag_stats["p95"] > 0.3, # 3 * 100ms interval
            db_stats["p95"] > 300 # Hypothetical baseline
        ]
        
        kipppunkt = "YES" if sum(conditions) >= 2 else "NO"
        if kipppunkt == "YES":
            reasons = []
            if stability < 0.95: reasons.append("Stability")
            if cas["reject_rate"] > 0.10: reasons.append("CAS Contention")
            if lag_stats["p95"] > 0.3: reasons.append("Loop Starvation")
            kipppunkt = f"YES ({', '.join(reasons)})"

        return {
            "concurrency": concurrency_level,
            "stability": stability,
            "avg_duration": avg_dur,
            "p95_duration": p95_dur,
            "cas_reject_rate": cas["reject_rate"],
            "loop_lag_p95": lag_stats["p95"],
            "db_write_p95": db_stats["p95"],
            "kipppunkt": kipppunkt
        }
