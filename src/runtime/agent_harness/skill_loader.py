"""
Skill Loader module.
Implements the `activate_skill` logic, fetching the SKILL.md for the agent.
"""
import os
from pathlib import Path
from typing import Optional, Dict
from .capability_discovery import CapabilityDiscovery

class SkillLoader:
    def __init__(self, discovery: CapabilityDiscovery):
        self.discovery = discovery
        
    def activate_skill(self, skill_name: str) -> str:
        target_cap: Optional[Dict] = None
        for cap in self.discovery.capabilities:
            if cap["name"] == skill_name:
                target_cap = cap
                break
                
        if not target_cap:
            return f"Error: Skill '{skill_name}' not found. Use search_capabilities to find valid skills."
            
        skill_dir = Path(target_cap["path"])
        skill_md_path = skill_dir / "SKILL.md"
        
        if not skill_md_path.exists():
            return f"Error: SKILL.md not found for '{skill_name}' at {skill_md_path}."
            
        try:
            with open(skill_md_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            return (
                f"Successfully activated skill: {skill_name}\n"
                f"--- SKILL INSTRUCTIONS ---\n"
                f"{content}\n"
                f"--- END OF INSTRUCTIONS ---\n"
                f"Note: Relevant tools have been made available in your context."
            )
        except Exception as e:
            return f"Error reading SKILL.md for '{skill_name}': {str(e)}"
