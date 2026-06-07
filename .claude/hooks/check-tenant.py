#!/usr/bin/env python3
"""PostToolUse hook — flags DB queries that may be missing tenant filtering."""
import sys
import json
import re

input_data = json.load(sys.stdin)
file_path = input_data.get("path", "")
content = input_data.get("content", "")

if not file_path.endswith(".py"):
    sys.exit(0)

# Find select() statements
selects = re.findall(r"select\([A-Z][A-Za-z]+\)", content)
if selects and "tenant_id" not in content:
    print("⚠️  WARNING: Found DB queries but no tenant_id filtering in this file.")
    print("   Every query must filter by tenant_id (see CLAUDE.md).")
sys.exit(0)
