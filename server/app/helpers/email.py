import logging
import os
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

import resend
from app.database.models import Onboarding
from app.schemas.orm_responses import serialize_onboarding

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_MAIN_AUDIENCE_ID = os.getenv("RESEND_MAIN_AUDIENCE_ID")

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


def add_to_default_audience(email: str, name: str | None = None) -> None:
    """
    Add a user to the default audience in Resend.

    Args:
        email (str): The email address of the user.
        name (str): The name of the user.
    """
    if not RESEND_MAIN_AUDIENCE_ID:
        logger.warning("Skipping audience sync: RESEND_MAIN_AUDIENCE_ID is not set")
        return

    try:
        split_name = name.split() if name else []
        fname = split_name[0] if len(split_name) > 0 else ""
        lname = " ".join(split_name[1:]) if len(split_name) > 1 else ""
        payload: resend.Contacts.CreateParams = {
            "email": email,
            "first_name": fname,
            "last_name": lname,
            "unsubscribed": False,
            "audience_id": RESEND_MAIN_AUDIENCE_ID,
        }
        resend.Contacts.create(payload)

    except Exception as e:
        logger.error(f"Failed to add user to audience: {e}", exc_info=True)


def send_onboarding_email(email: str, name: str | None = None) -> None:
    """
    Send an onboarding email to a new user.

    Args:
        email (str): The email address of the user.
        name (str): The name of the user.
    """

    try:
        one_minute_from_now = (
            datetime.now(timezone.utc) + timedelta(minutes=2)
        ).isoformat()
        split_name = name.split() if name else []
        fname = split_name[0] if split_name else ""
        formatted_name = f", {fname}" if fname else ""
        payload: resend.Emails.SendParams = {
            "from": DEFAULT_FROM,
            "to": [email],
            "subject": "Welcome to Scholens!",
            "html": load_email_template("onboarding.html").replace(
                "{{user_name}}", formatted_name
            ),
            "scheduled_at": one_minute_from_now,
            "reply_to": REPLY_TO_DEFAULT_EMAIL,
        }

        first_email = resend.Emails.send(payload)

        two_days_from_now = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()

        payload = {
            "from": DEFAULT_FROM,
            "to": [email],
            "subject": "How Researchers are Using AI to Read Papers",
            "html": load_email_template("some_tips.html"),
            "scheduled_at": two_days_from_now,
            "reply_to": REPLY_TO_DEFAULT_EMAIL,
        }

        second_email = resend.Emails.send(payload)

        four_days_from_now = (
            datetime.now(timezone.utc) + timedelta(days=4)
        ).isoformat()

        formatted_name = f" {fname}" if fname else ""

        payload = {
            "from": DEFAULT_FROM,
            "to": [email],
            "subject": "Design Principles by Scholens",
            "html": load_email_template("design_principles.html").replace(
                "{{user_name}}", formatted_name
            ),
            "scheduled_at": four_days_from_now,
            "reply_to": REPLY_TO_DEFAULT_EMAIL,
        }

        third_email = resend.Emails.send(payload)

        logger.info(
            f"Onboarding emails sent successfully: {first_email['id'] if first_email else ''}, {second_email['id'] if second_email else ''}, {third_email['id'] if third_email else ''}"
        )

    except Exception as e:
        logger.error(f"Failed to send onboarding email: {e}", exc_info=True)


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

    except Exception as e:
        logger.error(f"Failed to notify billing interval change: {e}", exc_info=True)


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

    except Exception as e:
        logger.error(f"Failed to notify billing issue: {e}", exc_info=True)


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

    except Exception as e:
        logger.error(f"Failed to send subscription welcome email: {e}", exc_info=True)


def send_profile_email(
    profile: Onboarding,
) -> None:
    """
    An internal email to send the developer with the user profile information
    """
    try:
        # Format profile data with alternating background colors
        profile_dict = serialize_onboarding(profile)
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

    except Exception as e:
        logger.error(f"Failed to send profile email: {e}", exc_info=True)


def send_general_invite_email(
    to_email: str,
    from_name: str,
) -> bool:
    """
    Send a general invitation email using Resend.

    Args:
        to_email: Recipient email address
        from_name: Name of the person sending the invite

    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    try:
        signup_link = f"{CLIENT_DOMAIN.rstrip('/')}/login"
        subject = f"{from_name} invited you to join Scholens"
        html_content = (
            load_email_template("general_invite.html")
            .replace("{{from_name}}", from_name)
            .replace("{{signup_link}}", signup_link)
        )

        payload: resend.Emails.SendParams = {
            "from": DEFAULT_FROM,
            "to": to_email,
            "subject": subject,
            "html": html_content,
        }

        resend.Emails.send(payload)
        return True

    except Exception as e:
        logger.error(f"Failed to send invite email to {to_email}: {e}", exc_info=True)
        return False


def send_project_invite_email(
    to_email: str,
    from_name: str,
    project_title: str,
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
        invite_link = f"{CLIENT_DOMAIN}/projects?openInvites=true"
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

    except Exception as e:
        logger.error(f"Failed to send invite email to {to_email}: {e}", exc_info=True)
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

    except Exception as e:
        logger.error(f"Failed to send invite email to {to_email}: {e}", exc_info=True)
        return False


def send_referral_threshold_alert(
    referrer_email: str,
    referrer_id: str,
    pending_plus_available_cents: int,
) -> None:
    """Email admin when a single referrer's earnings cross the review threshold."""
    admin_email = os.getenv("REFERRAL_REVIEW_EMAIL", PROFILE_NOTIFICATION_EMAIL)
    html = f"""
    <div style="font-family:sans-serif;max-width:700px;margin:0 auto;">
        <h2 style="color:#d35400;">Referral Review Threshold Crossed</h2>
        <p>
            <b>{referrer_email}</b> (id <code>{referrer_id}</code>) has accumulated
            <b>${pending_plus_available_cents / 100:.2f}</b> in referral credits.
        </p>
        <p>Worth a quick look at their recent referrals in the admin panel.</p>
    </div>
    """
    try:
        send_email(
            to_email=admin_email,
            subject=f"[Referral Review] {referrer_email} crossed ${pending_plus_available_cents / 100:.0f}",
            html_content=html,
            from_name="Scholens Alerts",
            from_address=DEFAULT_FROM_ADDRESS,
        )
    except Exception as e:
        logger.error(f"Failed to send referral threshold alert: {e}", exc_info=True)


def send_referral_converted_email(
    to_email: str,
    referee_email: str,
    credit_cents: int,
    available_at: datetime,
) -> bool:
    """
    Notify a referrer that someone they referred has just upgraded. Credit is
    pending until `available_at`.
    """
    try:
        dollars = credit_cents / 100
        available_str = available_at.strftime("%B %d, %Y")
        text = (
            f"Hi,\n\n"
            f"Great news — {referee_email} just upgraded to Researcher using your "
            f"referral link. You've earned a ${dollars:.2f} credit toward your "
            f"Scholens subscription.\n\n"
            f"Your credit will clear our 30-day hold on {available_str}, at which "
            f"point it'll be ready to apply against your next invoice.\n\n"
            f"Thanks for spreading the word!\n\n"
            f"- Scholens Team"
        )
        payload: resend.Emails.SendParams = {
            "from": DEFAULT_FROM,
            "reply_to": REPLY_TO_DEFAULT_EMAIL,
            "to": [to_email],
            "subject": f"Someone you referred just upgraded - ${dollars:.0f} credit pending",
            "text": text,
        }
        resend.Emails.send(payload)
        return True
    except Exception as e:
        logger.error(f"Failed to send referral_converted email: {e}", exc_info=True)
        return False


def send_referral_credit_available_email(
    to_email: str,
    credit_cents: int,
) -> bool:
    """Notify a referrer that their pending credit has cleared the hold."""
    try:
        dollars = credit_cents / 100
        text = (
            f"Hi,\n\n"
            f"Your ${dollars:.2f} referral credit has cleared the 30-day hold "
            f"and is now ready to apply against your Scholens subscription. "
            f"It'll come off your next invoice automatically — nothing else for "
            f"you to do.\n\n"
            f"If you haven't yet, you can keep sharing your link from the "
            f"account menu inside Scholens. Give $6, get $6.\n\n"
            f"Thanks again!\n\n"
            f"- Scholens Team"
        )
        payload: resend.Emails.SendParams = {
            "from": DEFAULT_FROM,
            "reply_to": REPLY_TO_DEFAULT_EMAIL,
            "to": [to_email],
            "subject": f"Your ${dollars:.0f} referral credit is ready",
            "text": text,
        }
        resend.Emails.send(payload)
        return True
    except Exception as e:
        logger.error(
            f"Failed to send referral_credit_available email: {e}", exc_info=True
        )
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
        logger.info(f"Data table complete email sent to {to_email}")
        return True

    except Exception as e:
        logger.error(
            f"Failed to send data table complete email to {to_email}: {e}",
            exc_info=True,
        )
        return False


def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: str = "",
    from_name: str = "Scholens",
    from_address: str = DEFAULT_FROM_ADDRESS,
) -> bool:
    """
    Send a generic email using Resend.

    Args:
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML content of the email
        text_content: Plain text content (optional)
        from_name: Sender name
        from_address: Sender email address

    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    try:
        payload: resend.Emails.SendParams = {
            "from": f"{from_name} <{from_address}>",
            "to": to_email,
            "subject": subject,
            "html": html_content,
        }

        # Add text content if provided
        if text_content:
            payload["text"] = text_content

        resend.Emails.send(payload)
        logger.info(f"Email sent successfully to {to_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}", exc_info=True)
        return False
