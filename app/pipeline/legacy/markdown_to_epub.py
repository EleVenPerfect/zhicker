#!/usr/bin/env python3
"""
把一个目录里的 Markdown 文件打包成 EPUB，成功后把输入目录和镜像目录一起归档成 ZIP，
归档成功后默认还会删掉这两个原始目录释放空间。

每篇 Markdown 成一章，按 Frontmatter 里的 modified / created 时间从早到晚排序。
默认把文章引用的本地图片嵌进 EPUB；--no-images 跳过嵌入并移除图片标签。
EPUB 没报错时，默认把输入目录和 down/img/ 一起压缩到 down/archive/知乎_<日期>.zip。
归档成功后默认 rmtree 掉输入目录和 image 目录；--no-cleanup 跳过删除。

用法：
    python markdown_to_epub.py <directory> [--no-images] [--no-archive] [--no-cleanup]
                                       [--output PATH] [--archive PATH] [--image-dir PATH]
"""
import argparse
import datetime
import hashlib
import html
import mimetypes
import os
import re
import shutil
import sys
import uuid
import zipfile

import yaml
from ebooklib import epub
from markdown import markdown


CSS = """
body { font-family: "Noto Serif CJK SC", "Source Han Serif SC", serif; line-height: 1.7; font-size: 1em; margin: 5%; }
.meta { font-size: 0.85em; color: #666; margin-bottom: 1em; }
.meta a { color: #666; }
img { max-width: 100%; height: auto; }
pre { background: #f5f5f5; padding: 0.8em; overflow-x: auto; font-family: "Source Code Pro", "Menlo", monospace; }
code { font-family: "Source Code Pro", "Menlo", monospace; }
h1 { font-size: 1.4em; line-height: 1.3; }
"""

IMG_TAG_RE = re.compile(r'<img\s+[^>]*?src="([^"]+)"[^>]*>', re.IGNORECASE)


def parse_frontmatter(text):
    """切 Frontmatter 和正文。解析失败返回 ({}, 原文)。"""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        fm = yaml.safe_load(parts[1]) or {}
        if not isinstance(fm, dict):
            return {}, text
    except yaml.YAMLError:
        return {}, text
    return fm, parts[2].lstrip("\n")


def parse_sort_time(fm):
    """取 modified / created 转 datetime，缺失返回 datetime.max（排到末尾）。"""
    for key in ("modified", "created"):
        v = fm.get(key)
        if isinstance(v, datetime.datetime):
            return v
        if isinstance(v, datetime.date):
            return datetime.datetime(v.year, v.month, v.day)
        if isinstance(v, str):
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.datetime.strptime(v, fmt)
                except ValueError:
                    continue
    return datetime.datetime.max


def format_created(fm):
    v = fm.get("created")
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, str) and len(v) >= 10:
        return v[:10]
    return "未知时间"


def build_meta_html(fm):
    """Frontmatter 渲染成章节顶部的小元信息块。"""
    if not fm:
        return ""
    url = fm.get("url") or "#"
    if url == "#":
        link_html = "无原文链接"
    else:
        link_html = f'<a href="{html.escape(url)}">原文</a>'
    author = html.escape(str(fm.get("author", "未知作者")))
    return (
        f'<p class="meta">{author}　|　{format_created(fm)}<br>'
        f'赞 {fm.get("upvote_num", 0)}　|　评论 {fm.get("comment_num", 0)}<br>'
        f'{link_html}</p><hr>'
    )


def process_images(html_text, md_dir, book, embed_enabled, image_registry):
    """
    embed_enabled=True：本地图片读字节、嵌进 EPUB、重写 src。http(s) 留着不动，缺文件替换为占位符。
    embed_enabled=False：直接把 <img> 标签整体移除。
    同一内容的图片只嵌一次（按 sha1 去重）。
    """
    if not embed_enabled:
        return IMG_TAG_RE.sub("", html_text)

    def replace(match):
        full_tag = match.group(0)
        src = match.group(1)
        if src.startswith(("http://", "https://")):
            return full_tag
        img_path = os.path.normpath(os.path.join(md_dir, src))
        if not os.path.exists(img_path):
            print(f"  警告: 图片不存在: {src}", file=sys.stderr)
            return "<em>[图片缺失]</em>"
        try:
            with open(img_path, "rb") as f:
                content = f.read()
        except OSError as e:
            print(f"  警告: 读图片失败 {src}: {e}", file=sys.stderr)
            return "<em>[图片读取失败]</em>"
        digest = hashlib.sha1(content).hexdigest()[:16]
        if digest in image_registry:
            internal = image_registry[digest]
        else:
            ext = os.path.splitext(img_path)[1].lower() or ".jpg"
            mime = mimetypes.types_map.get(ext, "image/jpeg")
            internal = f"images/{digest}{ext}"
            image_registry[digest] = internal
            book.add_item(
                epub.EpubImage(
                    uid=f"img_{digest}",
                    file_name=internal,
                    media_type=mime,
                    content=content,
                )
            )
        return full_tag.replace(src, internal)

    return IMG_TAG_RE.sub(replace, html_text)


def write_epub(md_dir, output_path, embed_enabled, book_title):
    md_files = sorted(
        f for f in os.listdir(md_dir)
        if f.endswith(".md") and os.path.isfile(os.path.join(md_dir, f))
    )
    if not md_files:
        print(f"错误: {md_dir} 里没有 .md 文件", file=sys.stderr)
        sys.exit(1)

    parsed = []
    for fname in md_files:
        fpath = os.path.join(md_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            print(f"警告: 跳过无法读取的文件 {fname}: {e}", file=sys.stderr)
            continue
        fm, body = parse_frontmatter(text)
        parsed.append((fname, fm, body))

    if not parsed:
        print(f"错误: {md_dir} 里没有可读的 .md 文件", file=sys.stderr)
        sys.exit(1)

    parsed.sort(key=lambda x: parse_sort_time(x[1]))

    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_title(book_title)
    book.set_language("zh-CN")
    book.add_author("知乎收藏夹归档")

    css_item = epub.EpubItem(
        uid="style_default",
        file_name="style/default.css",
        media_type="text/css",
        content=CSS.encode("utf-8"),
    )
    book.add_item(css_item)

    chapters = []
    image_registry = {}

    for idx, (fname, fm, body) in enumerate(parsed, start=1):
        title = fm.get("title") or os.path.splitext(fname)[0]
        title_safe = html.escape(str(title))
        body_html = markdown(body, extensions=["extra", "sane_lists"])
        meta_html = build_meta_html(fm)
        full_html = f'<h1>{title_safe}</h1>{meta_html}{body_html}'
        full_html = process_images(full_html, md_dir, book, embed_enabled, image_registry)

        chapter = epub.EpubHtml(
            title=str(title),
            file_name=f"chap_{idx:04d}.xhtml",
            lang="zh-CN",
        )
        chapter.content = full_html
        chapter.add_item(css_item)
        book.add_item(chapter)
        chapters.append(chapter)

    book.toc = chapters
    book.spine = ["nav"] + chapters
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    epub.write_epub(output_path, book)
    print(f"已生成: {output_path}")
    print(f"  章节数: {len(chapters)}")
    img_count = 0 if not embed_enabled else len(image_registry)
    print(f"  嵌入图片: {img_count}{'（已用 --no-images 禁用）' if not embed_enabled else ''}")


def add_dir_to_zip(z, dir_path):
    """把 dir_path 整个加进 ZIP，内部路径以 dir 的 basename 开头。返回加入的文件数。"""
    base = os.path.basename(dir_path.rstrip("/")) or "root"
    count = 0
    for root, _, files in os.walk(dir_path):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, dir_path)
            arcname = os.path.join(base, rel)
            z.write(full, arcname)
            count += 1
    return count


def make_archive(zip_path, input_dir, image_dir):
    """把 input_dir 和 image_dir 一起压缩到 zip_path。两者指向同一目录时只装一次。
    image_dir 不存在时警告并跳过。返回加入的文件总数。
    """
    os.makedirs(os.path.dirname(os.path.abspath(zip_path)), exist_ok=True)
    total = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        total += add_dir_to_zip(z, input_dir)
        if os.path.abspath(image_dir) == os.path.abspath(input_dir):
            pass  # 输入目录就是镜像目录，已经装过了
        elif os.path.isdir(image_dir):
            total += add_dir_to_zip(z, image_dir)
        else:
            print(f"  警告: 镜像目录不存在: {image_dir}，仅存档输入目录", file=sys.stderr)
    return total


def cleanup_dirs(dirs):
    """删除给定目录列表里的所有目录（按绝对路径去重，跳过 / 和空路径）。
    单个目录失败不影响其他目录。返回实际删掉的目录列表。
    """
    seen = set()
    deleted = []
    for d in dirs:
        if not d or d == "/":
            continue
        abs_d = os.path.abspath(d)
        if abs_d in seen or abs_d == "/":
            continue
        seen.add(abs_d)
        if not os.path.isdir(d):
            continue
        try:
            shutil.rmtree(d)
            deleted.append(d)
        except OSError as e:
            print(f"  警告: 清理 {d} 失败: {e}", file=sys.stderr)
    return deleted


def main():
    parser = argparse.ArgumentParser(
        description="把目录里的 Markdown 打包成 EPUB，成功后归档原始材料并清理"
    )
    parser.add_argument("directory", help="包含 .md 文件的目录")
    parser.add_argument("--no-images", action="store_true", help="不嵌入图片，移除 <img> 标签")
    parser.add_argument("--no-archive", action="store_true", help="EPUB 成功后不打包 ZIP 归档")
    parser.add_argument("--no-cleanup", action="store_true", help="归档成功后不删除原始目录")
    parser.add_argument("--output", help="EPUB 输出路径，默认 down/epub/知乎_<日期>.epub")
    parser.add_argument("--archive", help="ZIP 归档路径，默认 down/archive/知乎_<日期>.zip")
    parser.add_argument("--image-dir", help="ZIP 归档时一起打包的图片目录，默认 down/img")
    args = parser.parse_args()

    md_dir = args.directory.rstrip("/") or "/"
    if not os.path.isdir(md_dir):
        print(f"错误: 目录不存在: {md_dir}", file=sys.stderr)
        sys.exit(1)

    date_str = datetime.date.today().isoformat()
    output_path = args.output or os.path.join("down", "epub", f"知乎_{date_str}.epub")
    book_title = os.path.splitext(os.path.basename(output_path))[0] or "untitled"
    image_dir = args.image_dir or "down/img"

    # write_epub 内部失败会 sys.exit(1)，能走到下一行就说明 EPUB 没报错
    write_epub(md_dir, output_path, not args.no_images, book_title)

    # 归档跑过且成功才有 cleanup 的资格；--no-archive 模式下不归档也不清理
    archive_succeeded = False
    if not args.no_archive:
        archive_path = args.archive or os.path.join("down", "archive", f"知乎_{date_str}.zip")
        try:
            count = make_archive(archive_path, md_dir, image_dir)
            print(f"已存档: {archive_path}")
            print(f"  归档文件数: {count}")
            archive_succeeded = True
        except OSError as e:
            print(f"警告: 归档失败: {e}", file=sys.stderr)

    if archive_succeeded and not args.no_cleanup:
        deleted = cleanup_dirs([md_dir, image_dir])
        if deleted:
            print("已清理原始目录:")
            for d in deleted:
                print(f"  - {d}")


if __name__ == "__main__":
    main()
