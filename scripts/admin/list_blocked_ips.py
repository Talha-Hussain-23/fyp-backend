"""
List Currently Blocked IPs
Shows all IPs currently blocked by signup protection

Usage: python scripts/admin/list_blocked_ips.py
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from middleware.signup_protection import get_blocked_ips

def list_blocked_ips():
    """Display all currently blocked IPs"""
    print("🚫 CURRENTLY BLOCKED IPs")
    print("=" * 80)
    
    blocked_ips = get_blocked_ips()
    
    if not blocked_ips:
        print("No IPs currently blocked")
        return
    
    for ip, info in blocked_ips.items():
        remaining_min = info["remaining_minutes"]
        attempts = info["attempt_count"]
        print(f"IP: {ip:20} | Blocked for: {remaining_min} min | Failed attempts: {attempts}")
    
    print("=" * 80)
    print(f"Total blocked IPs: {len(blocked_ips)}")

if __name__ == "__main__":
    list_blocked_ips()
