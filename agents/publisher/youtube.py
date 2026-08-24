#!/usr/bin/env python3
"""
YouTube Publisher & OAuth Diagnostic Utility.

Usage:
    python3 youtube.py auth          # Force OAuth2 re-authorization with scope verification & API testing
    python3 youtube.py upload <mp4> --title "..." --description "..." --tags "a,b,c"
    python3 youtube.py upload <mp4> --title "..." --sandbox  # dry run, no actual upload
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

PUBLISHER_DIR = Path(__file__).resolve().parent
CLIENT_SECRET_PATH = PUBLISHER_DIR / "client_secret.json"
TOKEN_PATH = PUBLISHER_DIR / "youtube_token.json"

REQUIRED_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

API_SERVICE_NAME = "youtube"
API_VERSION = "v3"


def check_and_get_credentials(force_reauth: bool = False):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    print("Required scopes:")
    for s in REQUIRED_SCOPES:
        print(f" - {s}")

    existing_token_found = TOKEN_PATH.exists()
    print(f"\nExisting token found: {'YES' if existing_token_found else 'NO'}")

    creds = None
    if existing_token_found:
        try:
            with open(TOKEN_PATH) as f:
                token_data = json.load(f)

            granted_scopes = set(token_data.get("scopes", []))
            print("Existing token scopes:")
            for s in granted_scopes:
                print(f" - {s}")

            missing_scopes = [s for s in REQUIRED_SCOPES if s not in granted_scopes]
            if missing_scopes:
                print("\nMissing scopes:")
                for s in missing_scopes:
                    print(f" - {s}")
                print("\nAction:")
                print("- Existing token insufficient; forcing reauthorization")
                TOKEN_PATH.unlink(missing_ok=True)
                existing_token_found = False
            elif force_reauth:
                print("\nAction:")
                print("- Force reauthorization requested; invalidating existing token")
                TOKEN_PATH.unlink(missing_ok=True)
                existing_token_found = False
            else:
                print("\nAction:")
                print("- Reusing existing valid token")
                creds = Credentials.from_authorized_user_info(token_data)
                if not creds.valid and creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                        with open(TOKEN_PATH, "w") as f:
                            f.write(creds.to_json())
                    except Exception as re:
                        print(f"Token refresh failed: {re}", file=sys.stderr)
                        TOKEN_PATH.unlink(missing_ok=True)
                        creds = None
        except Exception as e:
            print(f"Warning parsing existing token: {e}", file=sys.stderr)
            TOKEN_PATH.unlink(missing_ok=True)
            creds = None

    if not creds or not creds.valid:
        if not CLIENT_SECRET_PATH.exists():
            print(f"\nError: {CLIENT_SECRET_PATH} not found.", file=sys.stderr)
            print("Download client_secret.json from Google Cloud Console:", file=sys.stderr)
            print("  1. Go to https://console.cloud.google.com/apis/credentials", file=sys.stderr)
            print("  2. Create OAuth 2.0 Client ID (Desktop app)", file=sys.stderr)
            print("  3. Download JSON, save as agents/publisher/client_secret.json", file=sys.stderr)
            sys.exit(1)

        flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), REQUIRED_SCOPES)
        creds = flow.run_local_server(
            port=8080,
            prompt="consent",
            access_type="offline"
        )

        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

        print(f"\nOAuth authorization completed: YES")
        with open(TOKEN_PATH) as f:
            token_data = json.load(f)
        print("New token scopes:")
        for s in token_data.get("scopes", []):
            print(f" - {s}")

    return creds


def get_authenticated_service():
    from googleapiclient.discovery import build
    creds = check_and_get_credentials(force_reauth=False)
    return build(API_SERVICE_NAME, API_VERSION, credentials=creds)


def do_auth():
    print("=" * 65)
    print("COLONY YOUTUBE OAUTH DIAGNOSTIC & AUTHORIZATION")
    print("=" * 65)

    creds = check_and_get_credentials(force_reauth=True)

    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError

    youtube = build(API_SERVICE_NAME, API_VERSION, credentials=creds)

    print("\nExecuting YouTube channels.list test...")
    try:
        res = youtube.channels().list(part="statistics,snippet", mine=True).execute()
        print("YouTube channels.list test: SUCCESS")
        if res.get("items"):
            ch = res["items"][0]
            name = ch.get("snippet", {}).get("title", "Unknown")
            subs = ch.get("statistics", {}).get("subscriberCount", 0)
            print(f"  Channel Name: {name}")
            print(f"  Subscribers: {subs}")
        else:
            print("  Note: Authenticated Google account has no YouTube channel created yet.")
        print("\nAuthentication fully verified and active!")
    except HttpError as e:
        print("YouTube channels.list test: FAILED")
        print(f"  HTTP Status Code: {e.resp.status}")
        reason = getattr(e, 'reason', str(e))
        print(f"  Error Reason: {reason}")
        print(f"  Granted Scopes on Credential: {getattr(creds, 'scopes', 'Unknown')}")
        sys.exit(1)


def do_upload(mp4_path: str, title: str, description: str, tags: list[str], sandbox: bool, privacy: str = "public"):
    mp4 = Path(mp4_path)
    if not mp4.exists():
        print(f"Error: {mp4_path} not found.", file=sys.stderr)
        sys.exit(1)

    if sandbox:
        print(f"[SANDBOX] Would upload: {mp4.name}")
        print(f"  Title: {title}")
        print(f"  Description: {description[:80]}...")
        print(f"  Tags: {', '.join(tags)}")
        print(f"  Size: {mp4.stat().st_size / 1024 / 1024:.1f} MB")
        print("[SANDBOX] Upload simulated successfully.")
        return

    print(f"Uploading {mp4.name} ({mp4.stat().st_size / 1024 / 1024:.1f} MB)...")
    service = get_authenticated_service()

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "28",  # Science & Technology
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(str(mp4), mimetype="video/mp4", resumable=True)
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    max_retries = 3
    for attempt in range(max_retries):
        try:
            while response is None:
                status, response = request.next_chunk()
                if status:
                    print(f"  Progress: {int(status.progress() * 100)}%")
            break
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rateLimitExceeded" in err_str or "uploadRateLimitExceeded" in err_str:
                wait = 60 * (attempt + 1)
                print(f"  Rate limited, waiting {wait}s...", file=sys.stderr)
                time.sleep(wait)
                response = None
                media = MediaFileUpload(str(mp4), mimetype="video/mp4", resumable=True)
                request = service.videos().insert(part="snippet,status", body=body, media_body=media)
                continue
            elif attempt < max_retries - 1:
                wait = 10 * (attempt + 1)
                print(f"  Upload error, retrying in {wait}s: {e}", file=sys.stderr)
                time.sleep(wait)
                response = None
                media = MediaFileUpload(str(mp4), mimetype="video/mp4", resumable=True)
                request = service.videos().insert(part="snippet,status", body=body, media_body=media)
                continue
            else:
                print(f"  Upload failed after {max_retries} attempts: {e}", file=sys.stderr)
                sys.exit(1)

    if response is None:
        print("Upload failed: no response", file=sys.stderr)
        sys.exit(1)

    video_id = response["id"]
    print(f"\nUpload complete!")
    print(f"  Video ID: {video_id}")
    print(f"  URL: https://youtube.com/watch?v={video_id}")


def main():
    parser = argparse.ArgumentParser(description="YouTube Publisher")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("auth", help="Authenticate with YouTube API & verify channels.list")

    upload_parser = sub.add_parser("upload", help="Upload video to YouTube")
    upload_parser.add_argument("mp4", help="Path to MP4 file")
    upload_parser.add_argument("--title", required=True, help="Video title")
    upload_parser.add_argument("--description", default="", help="Video description")
    upload_parser.add_argument("--tags", default="", help="Comma-separated tags")
    upload_parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"], help="Privacy status")
    upload_parser.add_argument("--sandbox", action="store_true", help="Dry run, no actual upload")

    args = parser.parse_args()

    if args.command == "auth":
        do_auth()
    elif args.command == "upload":
        tags = [t.strip() for t in args.tags.split(",") if t.strip()]
        do_upload(args.mp4, args.title, args.description, tags, args.sandbox, args.privacy)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
