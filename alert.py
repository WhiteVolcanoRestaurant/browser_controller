#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人工介入提醒模块（可独立定位 / 调用）。

集中封装"需要人工介入"时的声音提醒、弹窗提醒、启动自检，以及弹窗中
"不再弹窗"的持久化逻辑。所有提醒都在独立线程或异步方式执行，不阻塞调用方。

对外接口：
    print_enter_hint()      # 打印 Enter 唤醒提示 + 按配置触发声音/弹窗提醒
    notify_human_intervention()  # 只触发提醒（声音/弹窗），不打印 Enter 提示
    startup_alert_test()    # 启动时的一次性提醒自检（可当场调整音量/取消弹窗）

相关开关都在 config.py 的 HUMAN_ALERT_* 中配置。
"""

import os
import sys
import threading

import config


def print_enter_hint():
    # 需人工介入提示的通用补充：说明按 Enter 可立即唤醒脚本重新识别（无需等超时）。
    # 对应的等待逻辑在 browser.wait_for_progress 里监听 Enter（返回 user_enter）。
    print("手动完成后按 Enter 可立即唤醒脚本重新识别当前页面（无需等待超时），")
    print("或等待脚本自动检测到页面变化后继续（Ctrl+C 退出）。")
    # 可选增强：终端提示可能被遗漏，按配置用提示音/弹窗主动引起注意。
    notify_human_intervention()


def notify_human_intervention():
    """需要人工介入时的主动提醒（声音 / 弹窗）。由 HUMAN_ALERT_* 配置控制，默认关闭。"""
    if not config.HUMAN_ALERT_ENABLE:
        return
    if config.HUMAN_ALERT_SOUND:
        _play_alert_sound()
    if config.HUMAN_ALERT_POPUP:
        # 弹窗在独立线程中弹出，避免阻塞主循环的人工等待/轮询；用户关闭后线程自然结束。
        threading.Thread(target=_show_alert_popup, daemon=True).start()


def _play_alert_sound():
    """播放柔和提示音：Windows 用系统自带的通知音效（异步播放、不阻塞），
    其他平台降级为终端响铃字符 \\a。音量柔和、无刺耳高频。"""
    if sys.platform == "win32":
        try:
            import winsound
            media = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Media")
            # 依次尝试常见系统通知音效文件；SND_ASYNC 异步播放，不影响主流程。
            for name in ("Windows Notify.wav", "Windows Notification.wav",
                         "Windows User Account Control.wav"):
                path = os.path.join(media, name)
                if os.path.exists(path):
                    winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                    return
        except Exception:
            pass
    try:
        sys.stdout.write("\a")
        sys.stdout.flush()
    except Exception:
        pass


def _show_alert_popup():
    """弹出提示窗：告知需人工介入，并提供"不再弹窗"选择。
    - Windows 用原生 MessageBoxW 的 是/否 按钮：点"否"即不再弹窗（写回 config.py 持久化）；
    - 其他平台回退到 tkinter 对话框（含"不再弹窗"复选框）。
    弹窗始终提示可到 config.py（HUMAN_ALERT_POPUP）手动修改恢复。
    任一步失败静默降级为终端响铃，不影响主流程。"""
    if sys.platform == "win32":
        try:
            import ctypes
            # MB_YESNO=0x4 | MB_ICONINFORMATION=0x40 | MB_SETFOREGROUND=0x10000
            # 返回 IDYES(6)=继续弹窗 / IDNO(7)=不再弹窗
            res = ctypes.windll.user32.MessageBoxW(
                0,
                "脚本需要你的介入，请切换到终端查看提示后手动完成本页，\n"
                "完成后按 Enter 唤醒脚本。\n\n"
                "点击\"是\"  = 这次知道了，以后继续弹窗提醒；\n"
                "点击\"否\"  = 以后不再弹窗（写入 config.py：HUMAN_ALERT_POPUP=False）。\n\n"
                "如需恢复，随时编辑 config.py 将该值改回 True。",
                "需要人工介入",
                0x4 | 0x40 | 0x10000)
            if res == 7:  # IDNO
                _disable_popup_persist()
            return
        except Exception:
            pass  # 原生弹窗失败时回退到 tkinter（如无交互桌面）
    _show_alert_popup_tk()


def _show_alert_popup_tk():
    """tkinter 兜底版提示窗（非 Windows / 原生 MessageBox 不可用）。
    注意：tkinter 在 daemon 线程反复创建 Tk 会资源耗尽导致后续弹不出来，
    因此仅作为兜底路径，Windows 下优先走上面的原生 MessageBoxW。"""
    try:
        import tkinter as tk
        root = tk.Tk()
        root.title("需要人工介入")
        root.attributes("-topmost", True)
        root.resizable(False, False)
        msg = "脚本需要你的介入，请切换到终端查看提示后手动完成本页，\n完成后按 Enter 唤醒脚本。"
        tk.Label(root, text=msg, justify="left", padx=18, pady=(16, 8)).pack()
        disable_var = tk.IntVar(value=0)
        tk.Checkbutton(root,
                       text="不再弹窗（写入 config.py：HUMAN_ALERT_POPUP = False）",
                       variable=disable_var, anchor="w").pack(fill="x", padx=18)
        tk.Label(root,
                 text="提示：可随时编辑 config.py 修改 HUMAN_ALERT_POPUP 重新开启弹窗提醒。",
                 fg="#888888", justify="left", padx=18, pady=(2, 10)).pack(anchor="w")

        def on_ok():
            if disable_var.get():
                _disable_popup_persist()
            root.destroy()

        tk.Button(root, text="我知道了，手动处理", command=on_ok, width=24).pack(pady=(0, 12))
        root.mainloop()
    except Exception:
        try:
            sys.stdout.write("\a")
            sys.stdout.flush()
        except Exception:
            pass


def _disable_popup_persist():
    """把 config.HUMAN_ALERT_POPUP 改为 False：本进程立即生效，并写回 config.py 长期关闭。
    如需恢复，将 config.py 中 HUMAN_ALERT_POPUP 改回 True 即可。"""
    config.HUMAN_ALERT_POPUP = False
    try:
        cfg_path = os.path.join(config.BASE_DIR, "config.py")
        with open(cfg_path, "r", encoding="utf-8") as f:
            text = f.read()
        new_text = text.replace("HUMAN_ALERT_POPUP = True", "HUMAN_ALERT_POPUP = False", 1)
        if new_text != text:
            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write(new_text)
    except Exception as e:
        print(f"[提醒] 本进程已停止弹窗；但写回 config.py 失败：{e}。"
              "如需永久关闭，请手动编辑 config.py 将 HUMAN_ALERT_POPUP 改为 False。")


def startup_alert_test():
    """启动时的一次性提醒自检：播一次音、弹一次窗，通过一问一答确认有效。
    若没听到/没看到，输出音量与弹窗调整指引，并可当场重新试听。（自检可在 config.py 中关闭）"""
    print("\n[提醒自检] 即将播放一次提示音、弹出一次提示窗，"
          "用于确认'人工介入提醒'确实有效。在 cmd 窗口和在 VSC 终端中运行效果可能略有差别。")
    if config.HUMAN_ALERT_SOUND:
        _play_alert_sound()
    if config.HUMAN_ALERT_POPUP:
        threading.Thread(target=_show_alert_popup, daemon=True).start()
    try:
        import time
        time.sleep(1.5)  # 留出时间让弹窗/提示音先呈现，再询问
    except Exception:
        pass
    try:
        ans = input("刚才是否听到提示音、看到弹窗？(y=正常 / N=没听到) ").strip().lower()
    except EOFError:
        return
    if ans in ("n", "no", "没", "没有"):
        _prompt_volume_guide()


def _prompt_volume_guide():
    """给出音量/弹窗调整指引，并支持当场重新试听。"""
    print("\n[音量/弹窗引导] 可按以下方式调整后重新试听：")
    print(" - 提示音音量跟着系统'通知'音效走：打开 设置→系统→声音，")
    print("   把'通知'音量滑块调高/调低；或在系统音量混合器里调整。")
    print(" - 换更小声/更柔的音效：可修改 alert.py 的 _play_alert_sound() 里")
    print("   的候选 wav 文件名，换成系统 Media 目录下其他更小的音效。")
    print(" - 弹窗：确认 设置→系统→通知→本程序 通知未被拦截；")
    print("   或把 config.HUMAN_ALERT_POPUP 改为 False 只保留声音提醒。")
    try:
        again = input("调整完成后，输入 y 重新试听一次，或直接回车跳过：").strip().lower()
    except EOFError:
        return
    if again in ("y", "yes", "重新试听"):
        startup_alert_test()  # 重新试听（循环直到用户满意或跳过）