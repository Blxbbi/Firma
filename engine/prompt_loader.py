"""
PromptLoader for Firma
Loads prompts from the prompts/ directory instead of hardcoding them in workers.
"""

import os
from pathlib import Path
from typing import Dict, Optional


class PromptLoader:
    """Loads role-specific prompts from the prompts/ directory."""
    
    def __init__(self, prompts_dir: str = "prompts"):
        self.prompts_dir = Path(prompts_dir)
        self._cache: Dict[str, str] = {}
    
    def load(self, role: str, variant: str = "default") -> str:
        """
        Load a prompt for a given role and variant.
        
        Args:
            role: One of 'planner', 'executor', 'researcher', 'reviewer'
            variant: One of 'system', 'user_template', 'pimesh_system', 'pimesh_output'
        
        Returns:
            The prompt content as a string
        """
        cache_key = f"{role}:{variant}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Map variant to filename
        variant_map = {
            'system': 'system.md',
            'user_template': 'user_template.md',
            'pimesh_system': 'pimesh_system.md',
            'pimesh_output': 'pimesh_output.md',
            'pimesh_research_context': 'pimesh_research_context.md',
        }
        
        if variant not in variant_map:
            raise ValueError(f"Unknown variant: {variant}. Must be one of {list(variant_map.keys())}")
        
        filename = variant_map[variant]
        filepath = self.prompts_dir / role / filename
        
        if not filepath.exists():
            raise FileNotFoundError(f"Prompt file not found: {filepath}")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        self._cache[cache_key] = content
        return content
    
    def load_contract(self, contract_name: str) -> str:
        """Load a contract from prompts/contracts/."""
        cache_key = f"contract:{contract_name}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        filepath = self.prompts_dir / "contracts" / f"{contract_name}.md"
        if not filepath.exists():
            raise FileNotFoundError(f"Contract file not found: {filepath}")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        self._cache[cache_key] = content
        return content
    
    def clear_cache(self):
        """Clear the prompt cache."""
        self._cache.clear()


# Global instance
_loader: Optional[PromptLoader] = None


def get_prompt_loader() -> PromptLoader:
    """Get the global PromptLoader instance."""
    global _loader
    if _loader is None:
        _loader = PromptLoader()
    return _loader
