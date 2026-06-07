#!/usr/bin/env python3
"""PostToolUse hook — warns if a send call is added without an interrupt nearby."""
import sys
import json
import re

input_data = json.load(sys.stdin)
file_path = input_data.get("path", "")
content = input_data.get("content", "")

if not file_path.endswith(".py"):
    sys.exit(0)

# Detect raw send calls
send_patterns = [r"\.send_message\(", r"sendgrid.*\.send\(", r"messages\.create\("]
has_send = any(re.search(pat, content) for pat in send_patterns)
has_approval_context = "interrupt" in content or "approved" in content or "hitl" in content.lower()

if has_send and not has_approval_context:
    print("⚠️  WARNING: This file sends a message but shows no HITL approval gate.")
    print("   Confirm the send is downstream of an approved interrupt.")
    # Warn but don't block (exit 0) — human reviews
sys.exit(0)
