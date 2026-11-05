import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate


def is_configured(values):
    return bool(
        (values.get("host") or "").strip()
        and (values.get("from_addr") or "").strip()
        and (values.get("to_addr") or "").strip()
    )


def _clean_header(value):
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())


def _clean_error(exc):
    text = " ".join(str(exc).split())
    return (text or exc.__class__.__name__)[:500]


def _build_message(values, subject, body):
    message = EmailMessage()
    message["Subject"] = _clean_header(subject)
    from_name = _clean_header(values.get("from_name")) or "知乎收藏"
    message["From"] = formataddr((from_name, values["from_addr"]))
    message["To"] = values["to_addr"]
    message["Date"] = formatdate(localtime=True)
    message.set_content(body)
    return message


def send_epub(
    values,
    epub_bytes,
    display_name,
    collection_name,
    md_count,
    date_label,
    archive_bytes=None,
    archive_name=None,
):
    try:
        has_archive = archive_bytes is not None and bool(archive_name)
        attachment_text = (
            "EPUB 和原始数据归档（tar.gz）" if has_archive else "EPUB 文件"
        )
        body = (
            f"收藏夹：{collection_name}\n"
            f"篇数：{md_count}\n"
            f"生成时间：{date_label}\n\n"
            f"附件为该收藏夹的{attachment_text}，请查收。\n"
        )
        message = _build_message(
            values,
            f"[知乎收藏] {_clean_header(collection_name)} {date_label}",
            body,
        )
        filename = _clean_header(display_name) or "zhihu_collection.epub"
        _attach(message, epub_bytes, filename, "application", "epub+zip")
        if has_archive:
            archive_filename = (
                _clean_header(archive_name) or "zhihu_rawdata.tar.gz"
            )
            _attach(message, archive_bytes, archive_filename, "application", "gzip")
        return _deliver(values, message)
    except Exception as exc:
        return False, _clean_error(exc)


def send_archive(
    values, archive_bytes, display_name, collection_name, md_count, date_label
):
    try:
        body = (
            f"收藏夹：{collection_name}\n"
            f"篇数：{md_count}\n"
            f"生成时间：{date_label}\n\n"
            "附件为该收藏夹的原始数据归档（Markdown 与图片），请查收。\n"
        )
        message = _build_message(
            values,
            f"[知乎收藏] {_clean_header(collection_name)} {date_label} 原始数据",
            body,
        )
        filename = _clean_header(display_name) or "zhihu_rawdata.tar.gz"
        _attach(message, archive_bytes, filename, "application", "gzip")
        return _deliver(values, message)
    except Exception as exc:
        return False, _clean_error(exc)


def send_test(values):
    try:
        message = _build_message(
            values,
            "[知乎收藏] SMTP 测试邮件",
            "这是一封来自知乎收藏夹管理服务的测试邮件。\n\n如果收到此邮件，说明 SMTP 配置可用。\n",
        )
        return _deliver(values, message)
    except Exception as exc:
        return False, _clean_error(exc)


def _attach(message, data, filename, maintype, subtype):
    message.add_attachment(
        data,
        maintype=maintype,
        subtype=subtype,
        filename=filename,
    )


def _deliver(values, message):
    if not is_configured(values):
        return False, "SMTP 未配置完整（需要主机、发件地址和收件邮箱）。"

    host = values["host"]
    port = int(values.get("port") or 587)
    security = (values.get("security") or "starttls").lower()
    username = values.get("username") or ""
    password = values.get("password") or ""
    timeout = int(values.get("timeout") or 30)

    server = None
    try:
        context = ssl.create_default_context()
        if security == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
            server.ehlo()
            if security == "starttls":
                server.starttls(context=context)
                server.ehlo()
        if username:
            server.login(username, password)
        server.send_message(message)
        return True, None
    except Exception as exc:
        return False, _clean_error(exc)
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass
