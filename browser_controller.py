#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模块 1：BrowserController —— 封装 Playwright 的所有浏览器操作（PRD 第三节 模块1）

拟人化增强：
- 持久化登录态：使用 launch_persistent_context 复用 edge_profile 用户数据目录
- Stealth 指纹伪装：隐藏 navigator.webdriver 等自动化特征
- 贝塞尔曲线鼠标轨迹：模拟真实人类的鼠标移动后再点击
"""

import io
import os
import random
import time

from PIL import Image
from playwright.sync_api import sync_playwright

import config

try:
    from playwright_stealth import Stealth
    _HAS_STEALTH = True
except Exception:
    _HAS_STEALTH = False


class BrowserController:
    def __init__(self, channel=None, headless=False,
                 viewport_width=None, viewport_height=None,
                 use_stealth=True):
        self.channel = channel or config.BROWSER_CHANNEL
        self.headless = headless
        self.viewport_width = viewport_width or config.VIEWPORT_WIDTH
        self.viewport_height = viewport_height or config.VIEWPORT_HEIGHT
        self.device_scale_factor = getattr(config, "DEVICE_SCALE_FACTOR", 1)
        self.is_mobile = getattr(config, "IS_MOBILE", False)
        self.user_agent = getattr(config, "USER_AGENT", None)
        self.use_stealth = use_stealth
        self._pw = None
        self._context = None
        self.page = None
        self.last_screenshot_path = None
        self._start()

    def _start(self):
        # 持久化上下文：复用 edge_profile 登录态，无需每次重新登录
        self._pw = sync_playwright().start()
        context_kwargs = dict(
            user_data_dir=config.PROFILE_DIR,
            channel=self.channel,
            headless=self.headless,
            viewport={"width": self.viewport_width, "height": self.viewport_height},
            is_mobile=self.is_mobile,
            has_touch=self.is_mobile,
        )
        # deviceScaleFactor 只在 >1 时显式传入；默认 1 不传，避免触发有头模式截图闪动
        if self.device_scale_factor and self.device_scale_factor != 1:
            context_kwargs["device_scale_factor"] = self.device_scale_factor
        if self.user_agent:
            context_kwargs["user_agent"] = self.user_agent
        self._context = self._pw.chromium.launch_persistent_context(**context_kwargs)
        # 指纹伪装（未安装 playwright-stealth 时自动跳过，不影响主流程）
        if self.use_stealth and _HAS_STEALTH:
            try:
                Stealth().apply_stealth_sync(self._context)
            except Exception:
                pass
        self.page = (self._context.pages[0] if self._context.pages
                     else self._context.new_page())
        # headed 模式下主动把外层窗口调小到接近手机宽度，避免左右留白条
        if not self.headless:
            self._resize_browser_to_viewport()

    def _resize_browser_to_viewport(self):
        # headed 模式：把浏览器外层窗口调小到接近手机宽度，避免 viewport 很小但窗口还 1920x1080。
        # 窗口尺寸按 CSS 视口大小设置（不再乘 deviceScaleFactor），保证截图和窗口一致、不闪动。
        if not self.page:
            return
        try:
            self.page.set_viewport_size({
                "width": self.viewport_width, "height": self.viewport_height})
        except Exception:
            pass
        # Chromium 89+ 可通过 CDP 调整窗口大小
        try:
            client = self._context.new_cdp_session(self.page)
        except Exception:
            client = None
        if client is None:
            return
        # 边框余量：Windows 标题栏 + 边框大概要多几十像素
        margin = 48
        try:
            # Playwright sync API: send('Browser.getWindowForTarget')
            win = client.send("Browser.getWindowForTarget")
            wid = win.get("windowId")
            bounds = win.get("bounds") or {}
            if wid is None:
                return
            desired_w = self.viewport_width + margin * 2
            desired_h = self.viewport_height + margin * 4
            client.send("Browser.setWindowBounds", {
                "windowId": wid,
                "bounds": {
                    "windowState": "normal",
                    "width": desired_w,
                    "height": desired_h,
                    "left": max(80, (bounds.get("left") or 200)),
                    "top": max(40, (bounds.get("top") or 100)),
                }
            })
        except Exception as e:
            print(f"[INFO] 调整浏览器窗口尺寸失败（不影响运行）: {e}")

    def navigate(self, url):
        # 打开指定 URL，等待 networkidle；失败回退 domcontentloaded，最多重试 3 轮
        last_err = None
        for _ in range(3):
            try:
                self.page.goto(url, wait_until="networkidle", timeout=60000)
                return self.page
            except Exception as e:
                last_err = e
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
                return self.page
            except Exception as e:
                last_err = e
        raise (last_err if last_err else RuntimeError(f"导航失败: {url}"))

    def reload(self):
        # 刷新当前页（保留登录态，cookie 在 persistent context 中），用于死循环恢复
        try:
            self.page.reload(wait_until="domcontentloaded", timeout=30000)
            return True
        except Exception:
            try:
                self.page.reload(timeout=30000)
                return True
            except Exception:
                return False

    def screenshot(self, full_page=False):
        # 截取当前页面截图，返回 PIL.Image，并保存到 ./logs/ 目录；
        # 同时把保存路径记录到 self.last_screenshot_path，供日志台账关联截图。
        data = self.page.screenshot(full_page=full_page)
        os.makedirs(config.LOG_DIR, exist_ok=True)
        timestamp = int(time.time() * 1000)
        path = os.path.join(config.LOG_DIR, f"debug_page_{timestamp}.png")
        with open(path, "wb") as f:
            f.write(data)
        self.last_screenshot_path = path
        return Image.open(io.BytesIO(data))

    def click(self, x, y):
        # 先做拟人化鼠标移动，再在正确的文档上下文里（iframe 内 / 主文档）
        # 直接用 elementFromPoint 定位可点击祖先并派发 touch + click，
        # 避免"拿到坐标再回主文档用 page.mouse 穿透 iframe"在移动端模拟下失效。
        self._human_move(x, y)

        # 先看主文档 elementFromPoint 命中什么
        try:
            hit = self.page.evaluate(
                "([x,y]) => { const e = document.elementFromPoint(x,y); "
                "return e ? e.tagName : null; }", [x, y])
        except Exception:
            hit = None

        # 命中 iframe：切到 frame 内部上下文，直接对内部元素派发点击
        if hit in ("IFRAME", "FRAME"):
            frame, ox, oy = self._frame_at(x, y)
            if frame:
                try:
                    info = frame.evaluate(self._CLICK_JS, [x - ox, y - oy])
                except Exception as e:
                    print(f"[CLICK] frame 内点击异常: {e}")
                    info = None
                if info and info.get("ok"):
                    print(f"[CLICK] frame 内点击: 命中 {info['hit']} -> <{info['tag']}> "
                          f"({info['w']}x{info['h']}) clicked={info.get('clicked')}")
                    if info.get("clicked"):
                        return True
            # 回退：主文档坐标真实点击
            return self._real_click(x, y)

        # 主文档内：直接定位并派发点击
        try:
            info = self.page.evaluate(self._CLICK_JS, [x, y])
        except Exception as e:
            print(f"[CLICK] 点击异常: {e}")
            return self._real_click(x, y)
        if info and info.get("ok"):
            print(f"[CLICK] 点击: 命中 {info['hit']} -> <{info['tag']}> "
                  f"({info['w']}x{info['h']}) clicked={info.get('clicked')}")
            if info.get("clicked"):
                return True
        return self._real_click(x, y)

    def _real_click(self, x, y):
        # 回退：用 Playwright 真实输入点击（移动端 touch tap + mouse click）
        ok = False
        try:
            if self.is_mobile:
                self.page.touchscreen.tap(x, y)
            self.page.mouse.click(x, y)
            ok = True
        except Exception as e:
            print(f"[CLICK] 真实点击失败: {e}")
        return ok

    def _human_move(self, x, y):
        # 从视口随机起点，沿贝塞尔曲线移动到目标坐标（不点击）
        sx = random.uniform(self.viewport_width * 0.05, self.viewport_width * 0.5)
        sy = random.uniform(self.viewport_height * 0.1, self.viewport_height * 0.5)
        try:
            self.page.mouse.move(sx, sy)
        except Exception:
            pass
        self.page.wait_for_timeout(int(random.uniform(50, 200)))
        for px, py in self._bezier_points((sx, sy), (x, y)):
            try:
                self.page.mouse.move(px, py)
            except Exception:
                pass
            self.page.wait_for_timeout(int(random.uniform(4, 12)))
        self.page.wait_for_timeout(int(random.uniform(50, 200)))

    # 在给定文档上下文里，从 (x,y) 反查可点击祖先，派发 touch + click 并返回结果
    _CLICK_JS = """(args) => {
      const [x, y] = args;
      const el = document.elementFromPoint(x, y);
      if (!el) return {ok: false, reason: 'no_element'};
      let t = el;
      const CLICKABLE = ['A','BUTTON','INPUT','LABEL','SELECT'];
      while (t && t !== document.body && !CLICKABLE.includes(t.tagName)) {
        t = t.parentElement;
      }
      if (!t || t === document.body) t = el;
      const r = t.getBoundingClientRect();
      const cx = r.left + r.width / 2;
      const cy = r.top + r.height / 2;
      const fireTouch = (type) => {
        try {
          const touch = new Touch({identifier: 1, target: t, clientX: cx, clientY: cy});
          const opts = {bubbles: true, cancelable: true, view: window};
          if (type === 'touchstart') {
            opts.touches = [touch]; opts.targetTouches = [touch]; opts.changedTouches = [touch];
          } else {
            opts.touches = []; opts.targetTouches = []; opts.changedTouches = [touch];
          }
          t.dispatchEvent(new TouchEvent(type, opts));
        } catch (e) {}
      };
      fireTouch('touchstart');
      fireTouch('touchend');
      let clicked = false;
      try { t.click(); clicked = true; } catch (e) {}
      return {
        ok: true, clicked: clicked,
        tag: t.tagName, hit: el.tagName,
        w: Math.round(r.width), h: Math.round(r.height),
        cls: (typeof t.className === 'string' ? t.className : '').slice(0, 60)
      };
    }"""

    def _frame_at(self, x, y):
        # 找到覆盖 (x,y) 的 iframe 对应的 frame 和其左上角偏移 (ox, oy)
        try:
            iframes = self.page.query_selector_all("iframe, frame")
        except Exception:
            return None, 0, 0
        for el in iframes:
            try:
                box = el.bounding_box()
            except Exception:
                continue
            if box and box["x"] <= x <= box["x"] + box["width"] \
                    and box["y"] <= y <= box["y"] + box["height"]:
                try:
                    frame = el.content_frame()
                except Exception:
                    continue
                if frame:
                    return frame, box["x"], box["y"]
        return None, 0, 0

    def _bezier_points(self, start, end, num_points=45, spread=90):
        # 生成从 start 到 end 的三次贝塞尔曲线轨迹点（控制点随机偏移）
        x0, y0 = start
        x1, y1 = end
        dx, dy = x1 - x0, y1 - y0
        cx1 = x0 + dx * random.uniform(0.2, 0.4) + random.uniform(-spread, spread)
        cy1 = y0 + dy * random.uniform(0.2, 0.4) + random.uniform(-spread, spread)
        cx2 = x0 + dx * random.uniform(0.6, 0.8) + random.uniform(-spread, spread)
        cy2 = y0 + dy * random.uniform(0.6, 0.8) + random.uniform(-spread, spread)
        pts = []
        for i in range(num_points + 1):
            t = i / num_points
            mt = 1 - t
            x = mt ** 3 * x0 + 3 * mt ** 2 * t * cx1 + 3 * mt * t ** 2 * cx2 + t ** 3 * x1
            y = mt ** 3 * y0 + 3 * mt ** 2 * t * cy1 + 3 * mt * t ** 2 * cy2 + t ** 3 * y1
            pts.append((x, y))
        return pts

    def wait(self, ms):
        self.page.wait_for_timeout(ms)

    def wait_for_network_idle(self, timeout=30000):
        # 等待所有网络请求完成，超时返回 False
        try:
            self.page.wait_for_load_state("networkidle", timeout=timeout)
            return True
        except Exception:
            return False

    def find_text_element_center(self, keywords):
        # 兜底：直接用 Playwright 渲染结果，在 DOM/可见文本中找关键词并返回中心坐标。
        # 当 OCR 因视频/iframe/渲染时序识别为空时走这条。返回 (x, y) 或 None。
        if not self.page:
            return None
        js = """(keywords) => {
          const seen = new Set();
          const walker = document.createTreeWalker(
            document.body,
            NodeFilter.SHOW_TEXT,
            { acceptNode: (n) => (n.nodeValue && n.nodeValue.trim().length)
              ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT }
          );
          const targets = [];
          let node;
          while ((node = walker.nextNode())) {
            const txt = node.nodeValue.replace(/\\s+/g, '');
            if (!txt) continue;
            const hit = keywords.find(k => txt.indexOf(k.replace(/\\s+/g, '')) !== -1);
            if (!hit) continue;
            const range = document.createRange();
            range.selectNodeContents(node);
            const rects = range.getClientRects();
            if (!rects || rects.length === 0) continue;
            const r = rects[0];
            if (r.width <= 0 || r.height <= 0) continue;
            // 过滤被 CSS 移出屏幕的隐藏元素（如 top:-999999px）
            if (r.top < 0 || r.left < 0 || r.top >= window.innerHeight || r.left >= window.innerWidth) continue;
            const key = txt + '|' + r.left + ',' + r.top;
            if (seen.has(key)) continue;
            seen.add(key);
            targets.push({
              x: r.left + r.width / 2,
              y: r.top + r.height / 2,
              hit: hit,
              text: node.nodeValue.trim(),
            });
          }
          // 兜底：找包含关键词的 button/a/li/span 等元素
          if (targets.length === 0) {
            for (const sel of ['button','a','span','li','div','label']) {
              const els = document.querySelectorAll(sel);
              for (const el of els) {
                const raw = (el.innerText || el.textContent || '').replace(/\\s+/g, '');
                if (!raw) continue;
                const hit = keywords.find(k => raw.indexOf(k.replace(/\\s+/g, '')) !== -1);
                if (!hit) continue;
                const r = el.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0) continue;
                // 过滤被 CSS 移出屏幕的隐藏元素（如 top:-999999px）
                if (r.top < 0 || r.left < 0 || r.top >= window.innerHeight || r.left >= window.innerWidth) continue;
                targets.push({
                  x: r.left + r.width / 2,
                  y: r.top + r.height / 2,
                  hit: hit,
                  text: (el.innerText || el.textContent || '').trim().slice(0, 40),
                });
              }
              if (targets.length) break;
            }
          }
          return targets;
        }"""
        try:
            results = self.page.evaluate(js, list(keywords))
        except Exception as e:
            print(f"[DOM] find_text_element_center 异常: {e}")
            return None
        if not results:
            return None
        # 从下到上优先（推进按钮通常在页面底部、正文在上方），取最靠下的命中
        results.sort(key=lambda r: r.get("y", 0), reverse=True)
        best = results[0]
        print(f"[DOM] 通过渲染层定位到关键词: \"{best['hit']}\" -> 匹配 \"{best['text']}\" @ ({int(best['x'])}, {int(best['y'])})")
        return (int(best["x"]), int(best["y"])), best

    def find_next_button(self):
        # 用 DOM class 特征定位"换页/继续"按钮（跨 iframe），返回 (x, y) 主文档坐标。
        # 解决"下一页/继续/下一步"等文字变化但 class 恒为 next-btn 的情况。
        hints = list(getattr(config, "NEXT_BUTTON_CLASS_HINTS", ["next-btn", "next"]))
        return self._find_by_class(hints)

    def _find_by_class(self, hints):
        js = """(hints) => {
          const out = [];
          const els = document.querySelectorAll('button, a, div, span, input');
          for (const el of els) {
            const cls = (typeof el.className === 'string' ? el.className : '');
            if (!hints.some(h => cls.indexOf(h) !== -1)) continue;
            const r = el.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) continue;
            if (r.top < 0 || r.left < 0 || r.top >= window.innerHeight || r.left >= window.innerWidth) continue;
            out.push({
              x: Math.round(r.left + r.width / 2),
              y: Math.round(r.top + r.height / 2),
              cls: cls.slice(0, 50),
              w: Math.round(r.width), h: Math.round(r.height),
              tag: el.tagName
            });
            if (out.length >= 5) break;
          }
          return out;
        }"""
        all_results = []
        try:
            all_results.extend(self.page.evaluate(js, list(hints)) or [])
        except Exception:
            pass
        # 遍历 iframe，把内部坐标映射回主文档坐标
        try:
            frames = self.page.frames
        except Exception:
            frames = []
        for frame in frames:
            if frame == self.page.main_frame:
                continue
            box = None
            try:
                fe = frame.frame_element()
                box = fe.bounding_box()
            except Exception:
                box = None
            try:
                inner = frame.evaluate(js, list(hints)) or []
            except Exception:
                inner = []
            ox = (box or {}).get("x", 0) if box else 0
            oy = (box or {}).get("y", 0) if box else 0
            for r in inner:
                r["x"] = int(r["x"] + ox)
                r["y"] = int(r["y"] + oy)
                all_results.append(r)
        if not all_results:
            return None
        # 从下到上优先，取最靠下的 next-btn（页面底部通常是当前可点的翻页按钮）
        all_results.sort(key=lambda r: r.get("y", 0), reverse=True)
        best = all_results[0]
        print(f"[DOM] class 定位翻页按钮: <{best['tag']}> ({best['w']}x{best['h']}) "
              f"@ ({best['x']},{best['y']}) cls={best['cls']}")
        return (int(best["x"]), int(best["y"])), best

    def detect_video(self):
        # 跨 iframe 检测 <video> 元素状态，返回 {has_video, paused, playing}。
        # 用于识别"视频播放器页"（OCR 识别不到播放按钮/播放中无文字按钮）。
        js = """() => {
          const vids = Array.from(document.querySelectorAll('video'));
          if (vids.length === 0) return {has_video: false, paused: null, playing: null};
          const v = vids[0];
          return {has_video: true, paused: v.paused, playing: !v.paused && !v.ended};
        }"""
        try:
            r = self.page.evaluate(js)
            if r and r.get("has_video"):
                return r
        except Exception:
            pass
        try:
            frames = self.page.frames
        except Exception:
            frames = []
        for frame in frames:
            if frame == self.page.main_frame:
                continue
            try:
                r = frame.evaluate(js)
            except Exception:
                continue
            if r and r.get("has_video"):
                return r
        return {"has_video": False, "paused": None, "playing": None}

    def try_play_video(self):
        # 尝试点击视频播放按钮 / 调用 video.play()，返回播放后的状态。
        # 多数浏览器禁止无用户手势自动播放，可能仍失败，此时需提醒用户手动点。
        js = """() => {
          const vids = Array.from(document.querySelectorAll('video'));
          if (vids.length === 0) return {found: false, playing: false};
          const v = vids[0];
          // 点击常见播放按钮（vjs / 自定义 play 按钮）
          const btns = document.querySelectorAll(
            '[class*="play"], [class*="Play"], .vjs-big-play-button, [class*="btn-play"]');
          for (const b of btns) {
            const r = b.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) { try { b.click(); } catch (e) {} break; }
          }
          try { v.play(); } catch (e) {}
          return {found: true, playing: !v.paused && !v.ended};
        }"""
        try:
            r = self.page.evaluate(js)
            if r and r.get("found"):
                return r
        except Exception:
            pass
        try:
            frames = self.page.frames
        except Exception:
            frames = []
        for frame in frames:
            if frame == self.page.main_frame:
                continue
            try:
                r = frame.evaluate(js)
            except Exception:
                continue
            if r and r.get("found"):
                return r
        return {"found": False, "playing": False}

    def _matches_progress_api(self, url, post_data=""):
        # 用本地配置的 API 特征（config.PROGRESS_API_MARKS）判断请求是否属于"推进信号"。
        # url_marks 全部命中 URL 即算；若配置了 body_marks，还需全部命中 POST body。
        for mark in config.PROGRESS_API_MARKS:
            try:
                url_marks = mark.get("url_marks") or []
                if not url_marks or not all(m in url for m in url_marks):
                    continue
                body_marks = mark.get("body_marks") or []
                if not body_marks or all(m in post_data for m in body_marks):
                    return mark.get("name", "进度")
            except Exception:
                continue
        return None

    def _user_enter_pressed(self):
        # 非阻塞检测终端是否按下 Enter（Windows msvcrt）。
        # 用于"等待用户手动操作"期间：平台可能不发进度 API、URL 也不变，
        # 脚本干等超时太慢，用户按 Enter 即可立即唤醒重新识别页面内容。
        try:
            import msvcrt
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b"\r", b"\n"):
                    return True
        except Exception:
            pass
        return False

    def wait_for_progress(self, timeout_ms=120000, prev_url=None):
        # 等待"翻页/推进"信号，用于判断人工介入后页面是否真的变了。
        # 信号 1：命中本地配置的推进 API 特征（翻页 / 答题提交，见 config_platform.py）
        # 信号 2：页面 URL 变化
        # 信号 3：用户按 Enter（平台不发 API、URL 不变时手动唤醒重新识别）
        # 用 page.on("request") 注册事件 + page.wait_for_timeout 驱动事件循环轮询。
        # （注意：Page 没有 wait_for_request 方法，之前误用导致监听完全失效）
        self._progress_hit = False

        def _on_request(req):
            try:
                url = req.url or ""
                if self._matches_progress_api(url, req.post_data or ""):
                    self._progress_hit = True
            except Exception:
                pass

        try:
            self.page.on("request", _on_request)
        except Exception:
            pass
        deadline = time.time() + timeout_ms / 1000.0
        try:
            while time.time() < deadline:
                if self._progress_hit:
                    return True, "progress_api"
                if prev_url and (self.get_current_url() or "") != prev_url:
                    return True, "url_changed"
                if self._user_enter_pressed():
                    print("[唤醒] 用户按 Enter，立即重新识别当前页面。")
                    return True, "user_enter"
                # 用 page.wait_for_timeout 驱动事件循环，让 page.on 回调被触发
                self.page.wait_for_timeout(500)
            return False, "timeout"
        finally:
            try:
                self.page.remove_listener("request", _on_request)
            except Exception:
                pass

    def wait_for_video_playing(self, timeout_ms=120000):
        # 轮询检测视频是否开始播放（用户手动点了播放按钮）
        deadline = time.time() + timeout_ms / 1000.0
        while time.time() < deadline:
            v = self.detect_video()
            if v.get("playing"):
                return True
            self.page.wait_for_timeout(2000)
        return False

    def get_current_url(self):
        return self.page.url

    def get_viewport_size(self):
        return (self.viewport_width, self.viewport_height)

    def images_changed(self, img1, img2, threshold=8.0):
        # 降采样后比较两张截图的灰度差异，判断"页面内容是否显著变化"。
        # 降采样能容忍动画/视频帧的微小变化，只对"封面→内容"这种显著变化敏感。
        # 用作点击验证的兜底信号（URL 不变、API 没发时，靠内容变化判断点击生效）。
        try:
            small1 = img1.resize((48, 48), Image.LANCZOS).convert("L")
            small2 = img2.resize((48, 48), Image.LANCZOS).convert("L")
            d1 = list(small1.getdata())
            d2 = list(small2.getdata())
            diff = sum(abs(a - b) for a, b in zip(d1, d2)) / len(d1)
            return diff > threshold
        except Exception:
            return False

    def click_and_verify(self, x, y, before_image=None, prev_url=None, timeout_ms=6000):
        # 点击并用 expect_request 包裹（监听在点击同时生效），验证是否推进。
        # 关键：不能用"点击后再 wait_for_request"，否则请求已在监听注册前发出、会错过。
        def _is_progress(req):
            try:
                url = req.url or ""
                print(f"[网络] 请求: {url[:100]}")
                name = self._matches_progress_api(url, req.post_data or "")
                if name:
                    print(f"[网络] -> 匹配进度信号({name})")
                    return True
                return False
            except Exception as e:
                print(f"[网络] 请求判断异常: {e}")
                return False

        matched = False
        try:
            with self.page.expect_request(_is_progress, timeout=timeout_ms):
                self.click(x, y)
            matched = True
        except Exception:
            matched = False

        if matched:
            return True, "progress_api"
        # URL 变化兜底
        if prev_url and (self.get_current_url() or "") != prev_url:
            return True, "url_changed"
        # 截图内容变化兜底（页面变了但 URL 不变、API 没发）
        if before_image is not None:
            after_img = self.screenshot()
            if self.images_changed(before_image, after_img):
                return True, "content_changed"
        return False, "no_change"

    def close(self):
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
        self._context = self._pw = None
