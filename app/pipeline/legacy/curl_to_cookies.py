#!/usr/bin/env python3
"""
从 cookie.txt 里保存的浏览器 cURL 请求中提取 Cookie 头，合并写入 Cookies.json。

cookie.txt 通常是浏览器 DevTools 里 "Copy as cURL" 粘贴出来的整段内容，
Linux/Mac 单引号格式或 Windows cmd 双引号格式都能识别。多次运行是幂等的：
新 cookie 覆盖同名 key，原有其他 cookie 保留。
"""
import json
import os
import shlex
import sys

INPUT_FILE = "cookie.txt"
OUTPUT_FILE = "Cookies.json"


def parse_cookies_from_curl(curl_text):
    """
    用 shlex 切 token，扫 -H / --header 后面的值，匹配 cookie 头（大小写不敏感）。
    多个 cookie 头按出现顺序合并，后面覆盖前面（HTTP 服务器语义）。
    """
    try:
        tokens = shlex.split(curl_text, posix=True)
    except ValueError as e:
        raise ValueError(f"curl 文本解析失败，可能是引号未闭合: {e}")

    cookies = {}
    i = 0
    while i < len(tokens) - 1:
        if tokens[i] in ("-H", "--header"):
            header = tokens[i + 1]
            if ":" in header:
                name, _, value = header.partition(":")
                if name.strip().lower() == "cookie":
                    for pair in value.strip().split(";"):
                        pair = pair.strip()
                        if not pair or "=" not in pair:
                            continue
                        # 用 partition 而不是 split，因为 value 里可能含 '='（某些签名 cookie 会）
                        k, _, v = pair.partition("=")
                        cookies[k.strip()] = v.strip()
            i += 2
            continue
        i += 1
    return cookies


def load_existing_cookies(path):
    """读已有 Cookies.json，不存在或损坏就从空 dict 起步并给一行警告。"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"警告: 读取 {path} 失败 ({e})，按空 dict 处理。")
        return {}
    if not isinstance(data, dict):
        print(f"警告: {path} 内容不是 JSON 对象，按空 dict 处理。")
        return {}
    return data


def main():
    if not os.path.exists(INPUT_FILE):
        print(f"错误: 找不到 {INPUT_FILE}。请把浏览器 Copy as cURL 的内容保存到这个文件后重试。")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        curl_text = f.read()

    try:
        new_cookies = parse_cookies_from_curl(curl_text)
    except ValueError as e:
        print(f"错误: {e}")
        sys.exit(1)

    if not new_cookies:
        print(f"错误: 在 {INPUT_FILE} 里没找到任何 cookie 头。请确认这是浏览器 Copy as cURL 的完整内容。")
        sys.exit(1)

    existing = load_existing_cookies(OUTPUT_FILE)
    merged = {**existing, **new_cookies}

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=4)

    overwritten = len(set(new_cookies) & set(existing))
    preserved = len(existing) - overwritten
    print(f"已写入 {OUTPUT_FILE}:")
    print(f"  新增 {len(new_cookies) - overwritten} 个，覆盖 {overwritten} 个，保留原有 {preserved} 个，总计 {len(merged)} 个")


if __name__ == "__main__":
    main()
