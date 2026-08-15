"""
Capability Discovery module.
Implements the `search_capabilities` tool for the agent to find relevant Powers/Skills.
"""
import os
import json
from pathlib import Path
from typing import List, Dict

class CapabilityDiscovery:
    def __init__(self, powers_root: str):
        self.powers_root = Path(powers_root)
        self.capabilities = self._scan_capabilities()

    def _scan_capabilities(self) -> List[Dict]:
        results = []
        if not self.powers_root.exists():
            return results
            
        for root, dirs, files in os.walk(self.powers_root):
            if "metadata.json" in files:
                meta_path = Path(root) / "metadata.json"
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                        if "name" in meta and "description" in meta:
                            results.append({
                                "name": meta["name"],
                                "description": meta["description"],
                                "path": str(Path(root))
                            })
                except Exception:
                    pass
        return results

    def search(self, query: str = "") -> str:
        query_lower = query.lower()
        matches = []
        
        for cap in self.capabilities:
            if not query or query_lower in cap["name"].lower() or query_lower in cap["description"].lower():
                matches.append(cap)
                
        if not matches:
            return f"No capabilities found matching '{query}'."
            
        lines = [f"Found {len(matches)} capabilities:"]
        for cap in matches:
            lines.append(f"- {cap['name']}: {cap['description']}")
            
        lines.append("\nUse `activate_skill(skill_name)` to load instructions and tools for a specific capability.")
        return "\n".join(lines)
