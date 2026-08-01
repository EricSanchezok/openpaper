import logging
import os
from html import escape
from pathlib import Path

import resend
from app.modules.identity.application.onboarding_contracts import OnboardingResponse

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
resend.api_key = RESEND_API_KEY

CLIENT_DOMAIN = os.getenv("CLIENT_DOMAIN", "http://localhost:3000")
BRAND_NAME = "Scholens"
DEFAULT_FROM_ADDRESS = os.getenv("RESEND_FROM_ADDRESS", "no-reply@example.invalid")
REPLY_TO_DEFAULT_EMAIL = os.getenv(
    "RESEND_REPLY_TO_ADDRESS", "no-reply@example.invalid"
)
PROFILE_NOTIFICATION_EMAIL = os.getenv(
    "PROFILE_NOTIFICATION_EMAIL", REPLY_TO_DEFAULT_EMAIL
)
SOURCE_REPOSITORY_URL = os.getenv(
    "SOURCE_REPOSITORY_URL", "https://github.com/khoj-ai/openpaper"
)
DEFAULT_FROM = f"{BRAND_NAME} <{DEFAULT_FROM_ADDRESS}>"


def load_email_template(template_name: str) -> str:
    """Load HTML email template from templates directory"""
    # Get the directory of the current file
    current_dir = Path(__file__).parent
    template_path = current_dir / "templates" / template_name

    try:
        with open(template_path, "r", encoding="utf-8") as file:
            return (
                file.read()
                .replace("{{client_domain}}", CLIENT_DOMAIN.rstrip("/"))
                .replace(
                    "{{brand_logo_url}}",
                    f"{CLIENT_DOMAIN.rstrip('/')}/scholens.svg",
                )
                .replace("{{source_repository_url}}", SOURCE_REPOSITORY_URL)
            )
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Template {template_name} not found at {template_path}"
        )


def notify_converted_billing_interval(
    email: str,
    new_interval: str,
    name: str | None = None,
) -> None:
    """
    Notify user about their billing interval change.

    Args:
        email (str): The email address of the user.
        name (str): The name of the user.
        new_interval (str): The new billing interval (e.g., "yearly").
    """
    try:
        subject = f"{new_interval.zfill(1).capitalize()} Cycle Activated - Scholens"
        payload: resend.Emails.SendParams = {
            "from": DEFAULT_FROM,
            "reply_to": REPLY_TO_DEFAULT_EMAIL,
            "to": [email],
            "subject": subject,
            "text": f"Hello {name},\n\nYour cycle has been successfully changed to {new_interval}. Thank you for your continued support for open research!\n\nScholens Team",
        }

        resend.Emails.send(payload)

    except Exception:
        logger.exception("email.billing_interval_notification.failed")


def notify_billing_issue(email: str, issue: str, name: str | None = None) -> None:
    """
    Notify user about a billing issue.

    Args:
        email (str): The email address of the user.
        name (str): The name of the user.
        issue (str): The type of billing issue (e.g., "payment").
    """
    try:
        manage_url = f"{CLIENT_DOMAIN}/pricing"
        payload: resend.Emails.SendParams = {
            "from": DEFAULT_FROM,
            "reply_to": REPLY_TO_DEFAULT_EMAIL,
            "to": [email],
            "subject": "Scholens - Fulfillment Issue Detected",
            "text": f"Hello {name},\n\nWe have detected an issue with your account. {issue}.\n\nVisit {manage_url} for assistance.\n\n- Scholens",
        }

        resend.Emails.send(payload)

    except Exception:
        logger.exception("email.billing_issue_notification.failed")


def send_subscription_welcome_email(
    email: str,
) -> None:
    """Send a welcome email to a new subscriber."""
    try:
        payload: resend.Emails.SendParams = {
            "from": DEFAULT_FROM,
            "reply_to": REPLY_TO_DEFAULT_EMAIL,
            "to": [email],
            "subject": "You're all set - Scholens",
            "html": load_email_template("subscription_welcome.html"),
        }

        resend.Emails.send(payload)

    except Exception:
        logger.exception("email.subscription_welcome.failed")


def send_profile_email(profile: OnboardingResponse) -> None:
    """
    An internal email to send the developer with the user profile information
    """
    try:
        # Format profile data with alternating background colors
        profile_dict = profile.model_dump(mode="json")
        formatted_data = ""

        excluded_keys = ["id", "created_at", "updated_at"]
        for i, (key, value) in enumerate(profile_dict.items()):
            if key in excluded_keys:
                continue
            # Alternate between light and white backgrounds
            bg_color = "#ffffff" if i % 2 == 0 else "#f8f9fa"

            formatted_data += f"""
            <div style="background-color:{bg_color};padding:12px;margin:2px 0;border-radius:6px">
                <div style="font-weight:600;color:#2c3e50;margin-bottom:4px">{key.replace("_", " ").title()}:</div>
                <div style="color:#34495e;word-wrap:break-word">{escape(str(value))}</div>
            </div>
            """

        html_content = load_email_template("profile.html").replace(
            "{{profile_data}}", formatted_data
        )

        payload: resend.Emails.SendParams = {
            "from": DEFAULT_FROM,
            "reply_to": REPLY_TO_DEFAULT_EMAIL,
            "to": PROFILE_NOTIFICATION_EMAIL,
            "subject": "Scholens onboarding",
            "html": html_content,
        }

        resend.Emails.send(payload)

    except Exception:
        logger.exception("email.profile.failed")


def send_project_invite_email(
    to_email: str,
    from_name: str,
    project_title: str,
    invitation_token: str,
) -> bool:
    """
    Send a project invitation email using Resend.

    Args:
        to_email: Recipient email address
        from_name: Name of the person sending the invite
        project_title: Title of the project

    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    try:
        invite_link = (
            f"{CLIENT_DOMAIN.rstrip('/')}/project-invitations/{invitation_token}"
        )
        subject = f"{from_name} invited you to collaborate on '{project_title}'"
        html_content = (
            load_email_template("project_invite.html")
            .replace("{{from_name}}", from_name)
            .replace("{{project_title}}", project_title)
            .replace("{{invite_link}}", invite_link)
        )

        payload: resend.Emails.SendParams = {
            "from": DEFAULT_FROM,
            "to": to_email,
            "subject": subject,
            "html": html_content,
        }

        resend.Emails.send(payload)
        return True

    except Exception:
        logger.exception("email.project_invitation.failed")
        return False


def send_confirmation_cancellation_email(
    to_email: str,
    name: str | None = None,
) -> bool:
    """
    Send a confirmation email when user has cancelled their paid subscription.

    Args:
        to_email: Recipient email address
        from_name: Name of the person cancelling the invite

    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    try:
        user_name_str = f", {name}" if name else ""

        subject = f"Sorry to see you go{user_name_str} - Scholens"

        payload: resend.Emails.SendParams = {
            "from": DEFAULT_FROM,
            "reply_to": REPLY_TO_DEFAULT_EMAIL,
            "to": to_email,
            "subject": subject,
            "text": f"Hello{user_name_str},\n\nThis email is to confirm that your subscription has been successfully cancelled. We're sorry to see you go!\n\nIf you have any feedback or if there's anything we can do to improve your experience, please reply to this email.\n\nThank you for being a part of Scholens.\n\nHappy researching!\n- Scholens Team",
        }

        resend.Emails.send(payload)
        return True

    except Exception:
        logger.exception("email.subscription_cancellation.failed")
        return False


def send_data_table_complete_email(
    to_email: str,
    table_title: str,
    columns: list[str],
    row_count: int,
    project_name: str,
    project_id: str,
    result_id: str,
) -> bool:
    """
    Send an email notification when a data table extraction job completes.

    Args:
        to_email: Recipient email address
        table_title: Title of the data table
        columns: List of column names extracted
        row_count: Number of rows extracted
        project_name: Name of the project containing the data table
        project_id: ID of the project for constructing the view URL
        result_id: ID of the data table result for deep linking

    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    try:
        view_url = f"{CLIENT_DOMAIN}/projects/{project_id}/tables/{result_id}"
        subject = f"Data table ready: {table_title}"
        columns_str = ", ".join(columns)

        html_content = (
            load_email_template("data_table_complete.html")
            .replace("{{table_title}}", table_title)
            .replace("{{columns}}", columns_str)
            .replace("{{row_count}}", str(row_count))
            .replace("{{project_name}}", project_name)
            .replace("{{view_url}}", view_url)
        )

        payload: resend.Emails.SendParams = {
            "from": DEFAULT_FROM,
            "to": to_email,
            "subject": subject,
            "html": html_content,
        }

        resend.Emails.send(payload)
        logger.info("email.data_table_completion.sent")
        return True

    except Exception:
        logger.exception("email.data_table_completion.failed")
        return False
