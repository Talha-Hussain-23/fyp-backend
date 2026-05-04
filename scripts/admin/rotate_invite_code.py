"""
Generate New Organization Invite Code
Creates a cryptographically secure invite code for recruiter signup

Usage: python scripts/admin/rotate_invite_code.py [--length 24]

Example:
    python scripts/admin/rotate_invite_code.py --length 32
"""
import secrets
import string
import argparse

def generate_secure_code(length=24):
    """Generate cryptographically secure invite code"""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
    return ''.join(secrets.choice(alphabet) for _ in range(length))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate new invite code")
    parser.add_argument("--length", type=int, default=24, help="Length of code (default: 24)")
    args = parser.parse_args()
    
    new_code = generate_secure_code(args.length)
    
    print("🔑 NEW ORGANIZATION INVITE CODE GENERATED")
    print("=" * 60)
    print(f"\n{new_code}\n")
    print("=" * 60)
    print("\n📋 NEXT STEPS:")
    print("1. Update backend/.env:")
    print(f"   ORGANIZATION_INVITE_CODE={new_code}")
    print(f"   RECRUITER_INVITE_CODE={new_code}")
    print("\n2. Restart backend server:")
    print("   cd backend && python -m uvicorn app:app --reload")
    print("\n3. Distribute code securely:")
    print("   - Use password manager (1Password, LastPass)")
    print("   - Send via encrypted channel")
    print("   - Do NOT post in public Slack/email")
    print("\n⚠️  WARNING: Old code will stop working immediately after restart!")
    print("=" * 60)
