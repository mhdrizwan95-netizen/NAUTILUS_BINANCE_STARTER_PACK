#!/usr/bin/env python3
import smtplib, os, json
from email.message import EmailMessage

POLICY = "ops/m25_policy.yaml"
LOG = "data/processed/m25/compliance_log.jsonl"


def send_email(subject, body):
    sender = os.getenv("SMTP_USER")
    passwd = os.getenv("SMTP_PASS")
    approver = "compliance@yourdomain.com"
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = approver
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(sender, passwd)
        s.send_message(msg)


if __name__ == "__main__":
    payload = json.dumps({"approval_required": True, "reason": "model_promotion"}, indent=2)
    send_email("Organism Approval Required", payload)
    print("[M25] Approval email sent.")
