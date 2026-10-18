"""Durable mail outbox with conservative handling of ambiguous SMTP outcomes."""
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime
import os
from pathlib import Path
import re
import smtplib
import ssl
import tempfile

from .store import digest


def prepare(store, directory, recipient, report, html_body):
    if not isinstance(recipient,str) or not re.fullmatch(r'[^\s<>@,;\r\n]+@[^\s<>@,;\r\n]+\.[^\s<>@,;\r\n]+',recipient):
        raise ValueError('INVALID_RECIPIENT')
    # Keep failed-source alerts stable within a due slot even when later retry
    # timestamps change. A repaired game/history produces a new notification.
    summary={g:{k:v for k,v in data.items() if k in ('status','reason','history_sha256')} for g,data in report.get('games',{}).items()}
    identity=digest(dict(recipient=recipient,due_slot=report.get('due_slot'),summary=summary))
    value=dict(id=identity,recipient=recipient,report_sha256=digest(report),subject='SSQ＋DLT V4.5 非正式研究／阻斷狀態',html=html_body)
    old=store.read('outbox',identity)
    if old is None:
        try: store.append('outbox',identity,value)
        except ValueError as exc:
            if str(exc)!='IMMUTABLE_CONFLICT': raise
        old=store.read('outbox',identity)
    value=old
    folder=Path(directory); folder.mkdir(parents=True,exist_ok=True)
    path=folder/(identity+'.eml')
    msg=EmailMessage()
    msg['To']=recipient
    msg['Subject']=value['subject']
    msg['Message-ID']=f'<{identity}@glp.local>'
    msg.set_content('本報表為非正式研究。下一合法期尚未獲官方明示證據；formal_A=0 / NO_EDGE。')
    msg.add_alternative(value['html'],subtype='html')
    # Pin a deterministic boundary so parallel preparations have identical bytes.
    msg.set_boundary('GLP-'+identity)
    data=msg.as_bytes()
    if not path.exists():
        fd,temporary=tempfile.mkstemp(prefix='.mail-',dir=folder)
        try:
            with os.fdopen(fd,'wb') as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
            try: os.link(temporary,path)
            except FileExistsError: pass
        finally:
            Path(temporary).unlink(missing_ok=True)
    if path.read_bytes()!=data:
        raise ValueError('EML_SHA_MISMATCH')
    return identity


def flush(store, smtp):
    results=[]
    for item in store.rows('outbox'):
        identity=item['id']
        if store.read('sent',identity):
            results.append(dict(id=identity,status='SENT_PREVIOUSLY')); continue
        if store.read('send_started',identity):
            results.append(dict(id=identity,status='UNKNOWN_REQUIRES_RECONCILIATION')); continue
        if not smtp:
            results.append(dict(id=identity,status='BLOCKED_NO_SMTP_CONFIGURATION')); continue
        client=None
        try:
            if smtp.get('port',587)!=587 or not smtp.get('host') or not smtp.get('sender'):
                raise ValueError('EXPLICIT_STARTTLS_SMTP_REQUIRED')
            credential=os.environ.get(smtp.get('password_env','GLP_SMTP_PASSWORD'))
            if not credential:
                results.append(dict(id=identity,status='BLOCKED_NO_SMTP_CREDENTIAL')); continue
            client=smtplib.SMTP(smtp['host'],587,timeout=10)
            client.ehlo(); client.starttls(context=ssl.create_default_context()); client.ehlo()
            client.login(smtp.get('username',smtp['sender']),credential)
            msg=EmailMessage()
            msg['From']=smtp['sender']; msg['To']=item['recipient']; msg['Subject']=item['subject']
            msg['Message-ID']=f'<{identity}@glp.local>'; msg['Date']=format_datetime(datetime.now(timezone.utc))
            msg.set_content('非正式研究；formal_A=0 / NO_EDGE。')
            msg.add_alternative(item['html'],subtype='html')
            # Claim before DATA. A crash after acceptance cannot trigger duplicate resend.
            if not store.append('send_started',identity,dict(id=identity,report_sha256=item['report_sha256'])):
                results.append(dict(id=identity,status='UNKNOWN_REQUIRES_RECONCILIATION')); continue
            refused=client.send_message(msg)
            if refused:
                raise RuntimeError('RECIPIENT_REFUSED')
            store.append('sent',identity,dict(id=identity,status='SMTP_ACCEPTED',at=datetime.now(timezone.utc).isoformat()))
            results.append(dict(id=identity,status='SMTP_ACCEPTED'))
        except Exception as exc:
            # Authentication/connection failures happen before send_started and retry later.
            results.append(dict(id=identity,status='UNKNOWN_REQUIRES_RECONCILIATION' if store.read('send_started',identity) else 'RETRY',error=type(exc).__name__))
        finally:
            if client:
                try: client.close()
                except OSError: pass
    return results
