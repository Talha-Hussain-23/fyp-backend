"""
Emergency Script: Revoke User Access
Immediately deactivate a user account and downgrade role to candidate

Usage: python scripts/admin/revoke_user_access.py <email> [--reason "reason"]

Example:
    python scripts/admin/revoke_user_access.py ex-employee@company.com --reason "Employee terminated"
"""
import sys
import os
import argparse
from datetime import datetime
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from utils import get_db, logger

def revoke_access(email: str, reason: str = "Administrative action"):
    """Deactivate user account and log the action"""
    db = next(get_db())  # Get database instance from generator
    
    # Find user
    user = db.users.find_one({"email": email})
    if not user:
        print(f"❌ User not found: {email}")
        return False
    
    # Update user
    result = db.users.update_one(
        {"email": email},
        {
            "$set": {
                "is_active": False,
                "role": "candidate",  # Downgrade to candidate
                "deactivated_at": datetime.utcnow().isoformat(),
                "deactivation_reason": reason
            }
        }
    )
    
    if result.modified_count > 0:
        print(f"✅ Access revoked for: {email}")
        print(f"   Reason: {reason}")
        
        # Invalidate all tokens
        db.users.update_one(
            {"email": email},
            {"$inc": {"token_version": 1}}
        )
        print("   All active sessions terminated")
        
        # Log to application logger
        logger.warning(
            f"🚨 ACCOUNT DEACTIVATED | "
            f"Email: {email} | "
            f"Reason: {reason}"
        )
        
        return True
    else:
        print(f"⚠️  No changes made for: {email}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Revoke user access")
    parser.add_argument("email", help="Email of user to deactivate")
    parser.add_argument("--reason", default="Administrative action", help="Reason for deactivation")
    
    args = parser.parse_args()
    
    print("🚨 EMERGENCY USER DEACTIVATION")
    print("=" * 60)
    print(f"Target: {args.email}")
    print(f"Reason: {args.reason}")
    print("=" * 60)
    
    confirm = input("Are you sure? (yes/no): ")
    if confirm.lower() == "yes":
        revoke_access(args.email, args.reason)
    else:
        print("❌ Operation cancelled")
