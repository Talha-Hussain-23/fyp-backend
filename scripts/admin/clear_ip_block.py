"""
Emergency Script: Clear IP Block
Manually unblock an IP address from signup protection

Usage: python scripts/admin/clear_ip_block.py <ip_address>

Example:
    python scripts/admin/clear_ip_block.py 192.168.1.100
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from middleware.signup_protection import clear_ip_block
from utils import logger

def clear_block(ip: str):
    """Clear IP block and log the action"""
    clear_ip_block(ip)
    print(f"✅ IP block cleared for: {ip}")
    
    # Log to application logger
    logger.info(
        f"🔓 IP UNBLOCKED (Manual) | "
        f"IP: {ip}"
    )

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python clear_ip_block.py <ip_address>")
        print("Example: python clear_ip_block.py 192.168.1.100")
        sys.exit(1)
    
    ip = sys.argv[1]
    print(f"🔓 Clearing IP block for: {ip}")
    clear_block(ip)
