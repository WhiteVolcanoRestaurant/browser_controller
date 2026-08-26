#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_flow.py —— 一键测试脚本：自动启动本地 HTTP 服务器并跑通 test_page.html 全流程。

之前测试需要先手动在命令行开一个服务器（如 python -m http.server 8000）再跑 main.py，
现在本脚本一条命令自动完成：
    起服务器 -> 打开 http://127.0.0.1:<port>/test_page.html -> 跑完整流程 -> 关服务器

用法：
    python test_flow.py              # 默认（VLM 与 main.py 一致：启动时健康检查，不可用自动降级）
    python test_flow.py --no-vlm     # 跳过 VLM，需要思考的页面（如多选题）转人工
    python test_flow.py --port 8000  # 指定服务器端口（默认自动选空闲端口）

注意：
- 首次运行会打开 Edge 浏览器（复用 edge_profile 登录态目录）。
- 测试页第 5 页是"多选题"：有 Ollama 时 VLM 自动作答；无 VLM 时会停住等人工作答，
  脚本检测到翻页后自动继续。
- 走到"已完成"页即判定流程跑通，自动退出；Ctrl+C 随时停止，服务器会自动关闭。
"""

import argparse
import functools
import os
import sys
import threading
import time
import urllib.request

from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
TEST_PAGE = "test_page.html"

# 与 main.py 保持一致：导入前重定向 PaddleOCR 模型缓存目录，
# 避免 Windows 中文用户名导致底层 C++ 引擎加载模型失败。
os.environ["USERPROFILE"] = PROJECT_ROOT
os.environ["HOME"] = PROJECT_ROOT


class TestFinished(BaseException):
    """测试完成信号（继承 BaseException 而非 Exception）。

    main.py 主循环里有 `except Exception` 的异常恢复逻辑（会重新导航页面），
    用普通 Exception 会被它吞掉、导致测试收不了尾；用 BaseException 才能
    一路穿透到 test_flow.py（main.main 的 finally 仍会正常关闭浏览器）。
    """


class QuietHandler(SimpleHTTPRequestHandler):
    # 不打印每个静态文件请求，避免测试日志被 http.server 刷屏
    def log_message(self, fmt, *args):
        pass


def start_server(port=0):
    handler = functools.partial(QuietHandler, directory=PROJECT_ROOT)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def wait_until_ready(url, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def parse_args():
    parser = argparse.ArgumentParser(
        description="自动化测试：自动起服务器 + 跑 test_page.html 全流程")
    parser.add_argument("--no-vlm", action="store_true",
                        help="跳过 VLM（同 main.py 的 --no-vlm）")
    parser.add_argument("--port", type=int, default=0,
                        help="服务器端口（默认自动选空闲端口）")
    return parser.parse_args()


def main():
    args = parse_args()

    # 1. 启动本地静态服务器
    httpd = start_server(args.port)
    port = httpd.server_address[1]
    test_url = f"http://127.0.0.1:{port}/{TEST_PAGE}"
    print("=" * 60)
    print("[测试] 本地服务器已启动: ", test_url)
    print("[测试] 即将打开浏览器跑完整流程（Ctrl+C 随时停止）")
    print("=" * 60)

    if not wait_until_ready(test_url):
        print("[错误] 本地服务器启动失败，请检查端口占用。")
        httpd.shutdown()
        sys.exit(1)

    # 2. 导入主流程（顺带完成 USERPROFILE 重定向），跑完整流程
    import main as flow_main

    # 测试页走不到"真实课程详情页 URL 特征"（/course/detail），
    # 把特征覆盖为本地服务器地址，让"是否在详情页"判断按详情页处理，
    # 否则语义兜底会把测试页误判成"课程列表页"转人工。
    import config
    config.COURSE_DETAIL_URL_MARK = "127.0.0.1"

    # 走到"已完成"页时 main.py 会等待用户打开"下一节"，
    # 测试场景没有下一节，改为直接抛 TestFinished 结束测试。
    def _test_finished(browser, prev_detail_url):
        raise TestFinished("测试页已走到「已完成」，全流程跑通")

    flow_main._wait_for_next_lesson = _test_finished

    try:
        flow_main.main(test_url, enable_vlm=not args.no_vlm)
        print("[测试] 主流程正常结束。")
    except TestFinished as e:
        print(f"\n[测试] 成功：{e}")
    except KeyboardInterrupt:
        print("\n[测试] 用户中断，已停止。")
    finally:
        httpd.shutdown()
        print("[测试] 本地服务器已关闭。")


if __name__ == "__main__":
    main()
