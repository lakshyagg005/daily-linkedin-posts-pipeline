#!/usr/bin/env python3
"""
personal_brand/linkedin_auth_setup.py
-------------------------------------
Interactive setup and verification helper for LinkedIn API publishing credentials.

Safely tests your LinkedIn OAuth token in READ-ONLY mode (fetches profile via
/v2/userinfo) without publishing any content or making any public actions.

Usage:
  python3 -m personal_brand.linkedin_auth_setup
  python3 -m personal_brand.linkedin_auth_setup --verify-only
"""

import os
import sys
import json
import urllib.request
import urllib.error
import ssl
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from personal_brand.research import load_env_file

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def verify_linkedin_token(token: str) -> dict:
    """Verifies a LinkedIn OAuth Bearer token using the OpenID userinfo endpoint."""
    url = "https://api.linkedin.com/v2/userinfo"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=15, context=SSL_CTX) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "valid": True,
                "sub": data.get("sub"),
                "name": data.get("name"),
                "email": data.get("email"),
                "person_urn": f"urn:li:person:{data.get('sub')}",
            }
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8", errors="replace")
        return {
            "valid": False,
            "status": e.code,
            "error": err_msg,
        }
    except Exception as e:
        return {
            "valid": False,
            "error": str(e),
        }


def main():
    print("\n========================================================")
    print("  LINKEDIN API AUTHENTICATION & CREDENTIAL SETUP")
    print("========================================================")
    print("This utility verifies your LinkedIn API token in read-only mode.")
    print("No posts or public actions will be created.\n")

    env_vars = load_env_file()
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN") or env_vars.get("LINKEDIN_ACCESS_TOKEN")
    person_urn = os.environ.get("LINKEDIN_PERSON_URN") or env_vars.get("LINKEDIN_PERSON_URN")

    if not token:
        print("No LINKEDIN_ACCESS_TOKEN found in environment or .env file.\n")
        print("To obtain your 60-day OAuth token:")
        print("1. Go to https://developer.linkedin.com/ and sign in.")
        print("2. Create an App (associate it with your LinkedIn Page).")
        print("3. In the 'Products' tab, add:")
        print("   • 'Share on LinkedIn' (provides w_member_social scope)")
        print("   • 'Sign In with LinkedIn using OpenID Connect' (provides openid, profile, email)")
        print("4. In the 'Auth' tab, use the OAuth 2.0 tools or Token Generator")
        print("   to generate an Access Token with 'w_member_social' and 'openid, profile'.")
        print("5. Paste your access token below (or set LINKEDIN_ACCESS_TOKEN in .env):\n")

        try:
            entered_token = input("Enter LINKEDIN_ACCESS_TOKEN (or press Enter to exit): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            sys.exit(0)

        if not entered_token:
            print("No token entered. Exiting.")
            sys.exit(1)
        token = entered_token

    masked_token = f"{token[:6]}...{token[-4:]}" if len(token) > 10 else "***"
    print(f"\n[1/2] Verifying token ({masked_token}) with LinkedIn API...")

    result = verify_linkedin_token(token)

    if result.get("valid"):
        print("\n✅ TOKEN VERIFICATION SUCCEEDED!")
        print(f"  • Member Name: {result.get('name')}")
        print(f"  • Member Email: {result.get('email')}")
        print(f"  • Member ID (sub): {result.get('sub')}")
        print(f"  • Author URN: {result.get('person_urn')}")

        env_path = ROOT_DIR / ".env"
        if env_path.exists():
            existing_content = env_path.read_text(encoding="utf-8")
            if "LINKEDIN_ACCESS_TOKEN=" not in existing_content:
                with open(env_path, "a", encoding="utf-8") as f:
                    f.write(f"\n# LinkedIn API Credentials (60-day token)\n")
                    f.write(f"LINKEDIN_ACCESS_TOKEN={token}\n")
                    f.write(f"LINKEDIN_PERSON_URN={result.get('person_urn')}\n")
                print(f"\n✓ Saved LINKEDIN_ACCESS_TOKEN and LINKEDIN_PERSON_URN to {env_path}")
            else:
                print(f"\nNote: {env_path} already contains LINKEDIN_ACCESS_TOKEN entry.")
        print("\nNext step: Add LINKEDIN_ACCESS_TOKEN and LINKEDIN_PERSON_URN to GitHub Secrets.")
    else:
        print("\n❌ TOKEN VERIFICATION FAILED!")
        print(f"  • HTTP Status: {result.get('status', 'N/A')}")
        print(f"  • Details:     {result.get('error')}")
        print("\nPlease check that your token includes the 'openid' and 'profile' scopes,")
        print("and has not expired.")
        sys.exit(1)


if __name__ == "__main__":
    main()
