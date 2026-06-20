import os
import sys
import unittest
from unittest.mock import patch

# Ensure src and tests are in the system path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from eris_test_adapter import _make_coordinator
from runtime.debug_console import DebugConsole

class TestTemporalOverrides(unittest.TestCase):
    def test_overrides_expiry(self):
        # Create coordinator with empty initial state
        coord, transport = _make_coordinator({})
        console = DebugConsole(coord)
        
        # Initially no overrides
        self.assertEqual(getattr(coord, "_debug_overrides", {}), {})
        
        # Apply an override via command
        res = console.execute("set attachment 0.95")
        self.assertIn("attachment=0.95", res)
        
        # The override should be active immediately
        overrides = getattr(coord, "_debug_overrides", {})
        self.assertIn("attachment", overrides)
        val, ts = overrides["attachment"]
        self.assertEqual(val, 0.95)
        
        # Check that get_internal_state applies override
        state = coord._get_internal_state()
        self.assertEqual(state.attachment, 0.95)
        
        # Mock time forward by 15 seconds: override should still be active
        with patch("time.time", return_value=ts + 15.0):
            state = coord._get_internal_state()
            self.assertEqual(state.attachment, 0.95)
            self.assertIn("attachment", getattr(coord, "_debug_overrides", {}))
            
        # Mock time forward by 31 seconds: override should be expired and removed
        with patch("time.time", return_value=ts + 31.0):
            state = coord._get_internal_state()
            # It should have decayed / reverted to default baseline (which is 0.0 or 0.3 for attachment in baseline)
            self.assertNotEqual(state.attachment, 0.95)
            self.assertNotIn("attachment", getattr(coord, "_debug_overrides", {}))

if __name__ == "__main__":
    unittest.main()
