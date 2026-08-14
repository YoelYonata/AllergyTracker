"""SES email sending. Templates are deliberately plain and minimal for v1.

Both functions build a plain-text email and send it via SES's simple send_email API (no
attachments/HTML needed here, so no reason to deal with raw MIME messages).
"""
import boto3


def _client():
    return boto3.client("ses")


def send_alert_email(sender: str, to: str, location_name: str, date: str, breaches: list) -> None:
    """One pollen-threshold alert: location, date, and each breached type's UPI value."""
    subject = f"Pollen alert for {location_name} on {date}"
    lines = [f"Pollen levels are elevated for {location_name} on {date}:", ""]
    for breach in breaches:
        lines.append(f"  - {breach['display_name']}: UPI {breach['upi']} ({breach['category']})")
    lines.append("")
    lines.append("This is an automated alert from Allergy Tracker.")

    _client().send_email(
        Source=sender,
        Destination={"ToAddresses": [to]},
        Message={
            "Subject": {"Data": subject},
            "Body": {"Text": {"Data": "\n".join(lines)}},
        },
    )


def send_confirmation_email(sender: str, to: str, confirm_url: str, location_name: str) -> None:
    """Double opt-in step: subscriber must click this link before alerts start."""
    subject = f"Confirm your Allergy Tracker subscription for {location_name}"
    body = (
        f"You (or someone using this email address) requested pollen alerts for "
        f"{location_name}.\n\n"
        f"Confirm this subscription by clicking the link below:\n{confirm_url}\n\n"
        "If you didn't request this, you can safely ignore this email -- no alerts will be "
        "sent unless the link above is clicked."
    )

    _client().send_email(
        Source=sender,
        Destination={"ToAddresses": [to]},
        Message={
            "Subject": {"Data": subject},
            "Body": {"Text": {"Data": body}},
        },
    )
