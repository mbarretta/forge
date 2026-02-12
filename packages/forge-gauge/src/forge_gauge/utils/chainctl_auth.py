"""
Consolidated chainctl authentication utilities.

Provides a single source of truth for chainctl authentication operations,
with caching and error handling for efficient batch operations.
"""

import json
import logging
import shutil
import subprocess
from typing import Optional

from forge_gauge.constants import CLI_SUBPROCESS_TIMEOUT

logger = logging.getLogger(__name__)

# The chainguard-support folder UIDP - support identities are children of this folder
CHAINGUARD_SUPPORT_UIDP = "b1904b41e5385c95df709af6aca3530511383fef"

# Module-level cache for auth status and tokens
_cached_token: Optional[str] = None
_cached_auth_status: Optional[dict] = None


def verify_chainctl_installed() -> bool:
    """
    Check if chainctl is installed and available.

    Returns:
        True if chainctl is available, False otherwise
    """
    return shutil.which("chainctl") is not None


def get_chainctl_token(
    timeout: int = CLI_SUBPROCESS_TIMEOUT,
    audience: Optional[str] = None,
    use_cache: bool = True,
) -> Optional[str]:
    """
    Get chainctl auth token, with optional caching.

    Args:
        timeout: Subprocess timeout in seconds
        audience: Optional audience for the token (e.g., "libraries.cgr.dev")
        use_cache: Whether to use/update the module-level cache

    Returns:
        Auth token string or None if authentication fails
    """
    global _cached_token

    # Return cached token if available and caching enabled
    if use_cache and _cached_token and not audience:
        return _cached_token

    if not verify_chainctl_installed():
        logger.debug("chainctl not installed")
        return None

    cmd = ["chainctl", "auth", "token"]
    if audience:
        cmd.extend(["--audience", audience])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "not authenticated" in stderr.lower() or "login" in stderr.lower():
                logger.debug("Not authenticated with chainctl")
            else:
                logger.debug(f"Failed to get chainctl token: {stderr}")
            return None

        token = result.stdout.strip()

        # Cache the token if no custom audience and caching enabled
        if use_cache and not audience:
            _cached_token = token

        return token

    except subprocess.TimeoutExpired:
        logger.debug("chainctl auth token timed out")
        return None
    except FileNotFoundError:
        logger.debug("chainctl not found")
        return None


def clear_token_cache() -> None:
    """Clear the cached token to force refresh on next call."""
    global _cached_token
    _cached_token = None


def get_auth_status(timeout: int = CLI_SUBPROCESS_TIMEOUT) -> Optional[dict]:
    """
    Get chainctl auth status as a dictionary.

    Returns cached result if available. Use clear_auth_status_cache() to force refresh.

    Args:
        timeout: Subprocess timeout in seconds

    Returns:
        Dictionary with auth status (identity, capabilities, etc.) or None if unavailable
    """
    global _cached_auth_status

    if _cached_auth_status is not None:
        return _cached_auth_status

    if not verify_chainctl_installed():
        return None

    try:
        result = subprocess.run(
            ["chainctl", "auth", "status", "-o", "json"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            logger.debug("chainctl auth status failed")
            return None

        auth_data = json.loads(result.stdout)
        _cached_auth_status = auth_data
        return auth_data

    except subprocess.TimeoutExpired:
        logger.debug("chainctl auth status timed out")
        return None
    except json.JSONDecodeError as e:
        logger.debug(f"Failed to parse auth status JSON: {e}")
        return None
    except FileNotFoundError:
        logger.debug("chainctl not found")
        return None


def clear_auth_status_cache() -> None:
    """Clear the cached auth status to force refresh on next call."""
    global _cached_auth_status
    _cached_auth_status = None


def is_support_identity() -> bool:
    """
    Check if the current chainctl session is authenticated as a support identity.

    Support identities are stored under the chainguard-support folder. When authenticated
    as a support identity, the identity ID in 'chainctl auth status' will have the format:
    <chainguard-support-uidp>/<identity-id>

    Returns:
        True if authenticated as a support identity, False otherwise
    """
    auth_status = get_auth_status()
    if not auth_status:
        return False

    identity = auth_status.get("identity", "")

    # Support identities have format: <chainguard-support-uidp>/<identity-id>
    if identity.startswith(f"{CHAINGUARD_SUPPORT_UIDP}/"):
        logger.debug("Detected support identity authentication")
        return True

    return False


def has_org_access(organization: str) -> bool:
    """
    Check if the current user has access to an organization.

    Uses chainctl auth status to check if the organization is in the user's
    capabilities.

    Args:
        organization: Organization name (e.g., 'cbp.gov')

    Returns:
        True if user has access to the organization, False otherwise
    """
    auth_status = get_auth_status()
    if not auth_status:
        return False

    capabilities = auth_status.get("capabilities", {})

    if organization in capabilities:
        role = capabilities[organization]
        logger.debug(f"User has '{role}' role on '{organization}'")
        return True

    logger.debug(f"User has no access to '{organization}'")
    return False


def configure_docker_auth(timeout: int = CLI_SUBPROCESS_TIMEOUT) -> bool:
    """
    Configure Docker to authenticate with cgr.dev.

    Args:
        timeout: Subprocess timeout in seconds

    Returns:
        True if configuration succeeded, False otherwise
    """
    if not verify_chainctl_installed():
        return False

    try:
        result = subprocess.run(
            ["chainctl", "auth", "configure-docker"],
            capture_output=True,
            timeout=timeout,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def login(
    identity_id: Optional[str] = None,
    timeout: int = 60,
) -> bool:
    """
    Login to chainctl, optionally with a specific identity.

    Args:
        identity_id: Optional identity ID to assume (for support mode)
        timeout: Subprocess timeout in seconds (default 60 for browser auth)

    Returns:
        True if login succeeded, False otherwise
    """
    if not verify_chainctl_installed():
        return False

    cmd = ["chainctl", "auth", "login"]
    if identity_id:
        cmd.append(f"--identity={identity_id}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode == 0:
            # Clear caches after successful login
            clear_token_cache()
            clear_auth_status_cache()
            return True

        logger.debug(f"chainctl auth login failed: {result.stderr}")
        return False

    except subprocess.TimeoutExpired:
        logger.debug("chainctl auth login timed out")
        return False
    except FileNotFoundError:
        logger.debug("chainctl not found")
        return False


def logout(timeout: int = CLI_SUBPROCESS_TIMEOUT) -> bool:
    """
    Logout from chainctl.

    Args:
        timeout: Subprocess timeout in seconds

    Returns:
        True if logout succeeded, False otherwise
    """
    if not verify_chainctl_installed():
        return False

    try:
        result = subprocess.run(
            ["chainctl", "auth", "logout"],
            capture_output=True,
            timeout=timeout,
        )

        # Clear caches after logout
        clear_token_cache()
        clear_auth_status_cache()

        return result.returncode == 0

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def get_support_identity_id(organization: str) -> Optional[str]:
    """
    Get the support identity ID for an organization.

    Args:
        organization: Organization name (e.g., 'cbp.gov')

    Returns:
        Support identity ID if found, None otherwise
    """
    if not verify_chainctl_installed():
        return None

    try:
        result = subprocess.run(
            [
                "chainctl", "iam", "ids", "ls",
                "--parent=chainguard-support",
                f"--name={organization} support identity",
                "--output=id",
            ],
            capture_output=True,
            text=True,
            timeout=CLI_SUBPROCESS_TIMEOUT,
        )

        if result.returncode != 0:
            logger.debug(f"No support identity found for {organization}: {result.stderr}")
            return None

        identity_id = result.stdout.strip()
        return identity_id if identity_id else None

    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.debug(f"Error getting support identity for {organization}: {e}")
        return None


def login_as_support(organization: str) -> bool:
    """
    Login as the support identity for an organization.

    Args:
        organization: Organization name (e.g., 'cbp.gov')

    Returns:
        True if login successful, False otherwise
    """
    identity_id = get_support_identity_id(organization)
    if not identity_id:
        logger.warning(f"No support identity found for organization '{organization}'")
        return False

    logger.info(f"Logging in as support identity for '{organization}'...")
    if login(identity_id=identity_id, timeout=60):
        logger.info(f"Successfully logged in as support for '{organization}'")
        return True

    logger.error(f"Failed to login as support for '{organization}'")
    return False


def refresh_token() -> bool:
    """
    Refresh the chainctl token and Docker configuration.

    Returns:
        True if refresh succeeded, False otherwise
    """
    if not verify_chainctl_installed():
        return False

    # Clear cache first
    clear_token_cache()

    # Try to get a fresh token
    token = get_chainctl_token(use_cache=False)
    if not token:
        # Token expired, need to login
        logger.warning("Chainguard token expired, attempting login...")
        if not login():
            return False

    # Reconfigure Docker auth
    if configure_docker_auth():
        logger.info("Chainguard token refreshed successfully")
        return True

    logger.warning("Failed to configure Docker auth after token refresh")
    return False
