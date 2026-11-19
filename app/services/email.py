import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

MY_EMAIL = os.getenv("MY_EMAIL")
APP_PASSWORD = os.getenv("APP_PASSWORD")


def send_email(subject: str, body_text: str, body_html: str = None, recipients: list = None):
    if recipients is None:
        if not MY_EMAIL:
            raise ValueError("MY_EMAIL environment variable is not set")
        recipients = [MY_EMAIL]
    
    recipients = [r for r in recipients if r is not None]
    if not recipients:
        raise ValueError("No valid recipients provided")
    
    if not MY_EMAIL:
        raise ValueError("MY_EMAIL environment variable is not set")
    if not APP_PASSWORD:
        raise ValueError("APP_PASSWORD environment variable is not set")
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = MY_EMAIL
    msg["To"] = ", ".join(recipients)
    
    part1 = MIMEText(body_text, "plain")
    msg.attach(part1)
    
    if body_html:
        part2 = MIMEText(body_html, "html")
        msg.attach(part2)
    
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15, context=ssl.create_default_context()) as smtp:
        smtp.login(MY_EMAIL, APP_PASSWORD)
        smtp.sendmail(MY_EMAIL, recipients, msg.as_string())


def markdown_to_html(markdown_text: str) -> str:
    from app.web_digest import safe_email_html

    return safe_email_html({"introduction": {"introduction": markdown_text}})


def digest_to_html(digest_response) -> str:
    from app.agent.email_agent import EmailDigestResponse
    from app.web_digest import safe_email_html

    if isinstance(digest_response, EmailDigestResponse):
        return safe_email_html(digest_response.model_dump())
    text = digest_response.to_markdown() if hasattr(digest_response, "to_markdown") else str(digest_response)
    return markdown_to_html(text)


def send_email_to_self(subject: str, body: str):
    if not MY_EMAIL:
        raise ValueError("MY_EMAIL environment variable is not set. Please set it in your .env file.")
    send_email(subject, body, recipients=[MY_EMAIL])


if __name__ == "__main__":
    send_email_to_self("Test from Python", "Hello from my script.")
