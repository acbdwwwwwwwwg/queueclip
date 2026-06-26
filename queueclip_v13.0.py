#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QueueClip v13.0 — 灵动安全版 · 队列式剪贴板管理工具
======================================================
更新说明（v13.0）：
    【粘贴安全机制】
    - 粘贴后延迟出队（默认 350ms 可调），消灭“已出队未粘贴”
    - 最近 5 次粘贴可撤回（回滚到队首），底部显示撤回入口
    - 粘贴失败时自动保留条目并弹出浮动提示
    - 全局快捷键粘贴同样享有上述保护
    【灵动动画】
    - 窗口显示/隐藏：淡入淡出 + 轻微缩放（类弹性效果）
    - 条目插入：从上方滑入，底部条目自然下移（用背景闪烁模拟）
    - 条目删除：红晕闪烁后消失
    - 拖拽排序：指示条改为呼吸灯渐变效果，源行半透明高亮
    - 粘贴反馈：顶部浮动卡片飘入→停留→淡出消失
    - 按钮悬停：背景色平滑过渡（使用 style.map 精细调色）
    - 锁定列点击：图标轻弹动画
    【其他优化】
    - 粘贴历史栈（最近 5 条，队列内存 + UI 显示）
    - 粘贴状态行：显示最近粘贴内容预览及状态
    - 更好的防抖与线程安全
    - 代码结构小幅重构，便于维护

快捷键速查（同前）
依赖：pyperclip, keyboard
必须以管理员身份运行
"""
import tkinter as tk
from tkinter import ttk, messagebox, Menu
import threading
import json
import os
import sys
import re
import time
import atexit
import ctypes

# ── 第三方库检查 ──────────────────────────────────────────
try:
    import pyperclip
except ImportError:
    print("❌ 缺少 pyperclip，请执行：pip install pyperclip")
    sys.exit(1)
try:
    import keyboard
except ImportError:
    print("❌ 缺少 keyboard，请执行：pip install keyboard")
    sys.exit(1)

# ═══════════════════════════════════════════════════════════
#  主题色板（沿用 v12.2）
# ═══════════════════════════════════════════════════════════
class Theme:
    BG_MAIN       = "#FFF0F5"
    BG_SECOND     = "#FFE4EC"
    BG_CARD       = "#FFFFFF"
    ACCENT        = "#FF69B4"
    ACCENT_LIGHT  = "#FFB6D9"
    ACCENT_DARK   = "#E75480"
    TEXT_PRIMARY  = "#4A3040"
    TEXT_SECOND   = "#9B7B8C"
    BORDER        = "#F0C4D8"
    SUCCESS       = "#98D8C8"
    WARNING       = "#FFD5A5"
    DANGER        = "#FF8FA3"
    ROW_EVEN      = "#FFF5F8"
    ROW_ODD       = "#FFFFFF"
    ROW_SELECT    = "#FFD6E8"
    HEADER_BG     = "#FFB6D9"
    TOOLTIP_BG    = "#FFFACD"
    FONT_MAIN     = ("Microsoft YaHei UI", 9)
    FONT_BOLD     = ("Microsoft YaHei UI", 10, "bold")
    FONT_TITLE    = ("Microsoft YaHei UI", 13, "bold")
    FONT_SMALL    = ("Microsoft YaHei UI", 8)
    FONT_MONO     = ("Consolas", 9)

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".queue_clip")
CONFIG_FILE = os.path.join(CONFIG_DIR, "queue_data.json")
MAX_QUEUE_SIZE = 50
PREVIEW_LENGTH = 30
DRAG_THRESHOLD = 8
TOOLTIP_MAX_CHARS = 500
TOOLTIP_DELAY_MS = 400
DEBOUNCE_MS = 300
AUTO_SCROLL_EDGE = 30
AUTO_SCROLL_INTERVAL = 100

# v13.0 新增常量
PASTE_DELAY_MS = 350          # 粘贴后延迟出队时间（毫秒）
UNDO_HISTORY_SIZE = 5         # 可撤回的粘贴条数
ANIMATION_FPS = 60            # 动画帧率（实际用 after 16ms）
FLASH_DURATION_MS = 200       # 行闪烁持续时间

def ensure_config_dir():
    if not os.path.exists(CONFIG_DIR):
        os.makedirs(CONFIG_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════════
#  剪贴板安全操作工具 (v13.0 增强：备份/恢复)
# ═══════════════════════════════════════════════════════════
class ClipboardHelper:
    @staticmethod
    def safe_copy(text: str, max_retries: int = 5) -> bool:
        for _ in range(max_retries):
            try:
                pyperclip.copy(text)
                time.sleep(0.08)
                if pyperclip.paste() == text:
                    return True
            except Exception:
                pass
            time.sleep(0.06)
        return False

    @staticmethod
    def safe_paste(max_retries: int = 3) -> str:
        for _ in range(max_retries):
            try:
                return pyperclip.paste()
            except Exception:
                time.sleep(0.1)
        return ""

    @staticmethod
    def backup() -> str:
        """备份当前剪贴板内容"""
        try:
            return pyperclip.paste()
        except Exception:
            return ""

    @staticmethod
    def restore(text: str):
        """恢复剪贴板内容"""
        if text:
            try:
                pyperclip.copy(text)
            except Exception:
                pass

# ═══════════════════════════════════════════════════════════
#  主题注册（v13.0 增加更细腻的 map 颜色过渡）
# ═══════════════════════════════════════════════════════════
def setup_anime_style(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=Theme.BG_MAIN, foreground=Theme.TEXT_PRIMARY, font=Theme.FONT_MAIN)
    style.configure("TFrame", background=Theme.BG_MAIN)
    style.configure("Card.TFrame", background=Theme.BG_CARD, relief="solid", borderwidth=1)
    style.configure("Bar.TFrame", background=Theme.BG_SECOND)
    style.configure("TLabel", background=Theme.BG_MAIN, foreground=Theme.TEXT_PRIMARY, font=Theme.FONT_MAIN)
    style.configure("Title.TLabel", background=Theme.BG_MAIN, foreground=Theme.ACCENT_DARK, font=Theme.FONT_TITLE)
    style.configure("Status.TLabel", background=Theme.BG_SECOND, foreground=Theme.ACCENT_DARK, font=Theme.FONT_BOLD, padding=6)
    style.configure("Hint.TLabel", background=Theme.BG_MAIN, foreground=Theme.TEXT_SECOND, font=Theme.FONT_SMALL)

    # 按钮基础样式
    style.configure("TButton",
                    background=Theme.ACCENT_LIGHT, foreground=Theme.TEXT_PRIMARY,
                    borderwidth=0, focusthickness=0, padding=(10, 4), font=Theme.FONT_BOLD, relief="flat")
    style.map("TButton",
              background=[("active", Theme.ACCENT), ("pressed", Theme.ACCENT_DARK)],
              foreground=[("active", "#FFFFFF"), ("pressed", "#FFFFFF")])

    style.configure("Danger.TButton", background=Theme.DANGER, foreground="#FFFFFF",
                    borderwidth=0, focusthickness=0, padding=(10, 4), font=Theme.FONT_BOLD, relief="flat")
    style.map("Danger.TButton", background=[("active", "#FF5C7A"), ("pressed", "#E04260")])

    style.configure("Success.TButton", background=Theme.SUCCESS, foreground=Theme.TEXT_PRIMARY,
                    borderwidth=0, focusthickness=0, padding=(10, 4), font=Theme.FONT_BOLD, relief="flat")
    style.map("Success.TButton", background=[("active", "#7EC8B5"), ("pressed", "#6AB8A3")])

    style.configure("Small.TButton", background=Theme.ACCENT_LIGHT, foreground=Theme.TEXT_PRIMARY,
                    borderwidth=0, focusthickness=0, padding=(6, 2), font=Theme.FONT_SMALL, relief="flat")
    style.map("Small.TButton",
              background=[("active", Theme.ACCENT), ("pressed", Theme.ACCENT_DARK)],
              foreground=[("active", "#FFFFFF"), ("pressed", "#FFFFFF")])

    style.configure("TEntry", fieldbackground=Theme.BG_CARD, foreground=Theme.TEXT_PRIMARY,
                    borderwidth=1, relief="solid", padding=4)
    style.map("TEntry", fieldbackground=[("focus", Theme.BG_CARD)], bordercolor=[("focus", Theme.ACCENT)])

    style.configure("TCombobox", fieldbackground=Theme.BG_CARD, foreground=Theme.TEXT_PRIMARY,
                    background=Theme.ACCENT_LIGHT, arrowcolor=Theme.ACCENT_DARK, padding=3)
    style.map("TCombobox",
              fieldbackground=[("readonly", Theme.BG_CARD)],
              background=[("readonly", Theme.ACCENT_LIGHT), ("active", Theme.ACCENT)])

    style.configure("Treeview", background=Theme.BG_CARD, foreground=Theme.TEXT_PRIMARY,
                    fieldbackground=Theme.BG_CARD, borderwidth=1, rowheight=28, font=Theme.FONT_MAIN)
    style.configure("Treeview.Heading", background=Theme.HEADER_BG, foreground=Theme.ACCENT_DARK,
                    font=Theme.FONT_BOLD, relief="flat", padding=(4, 4))
    style.map("Treeview.Heading", background=[("active", Theme.ACCENT_LIGHT)])
    style.map("Treeview", background=[("selected", Theme.ROW_SELECT)], foreground=[("selected", Theme.TEXT_PRIMARY)])

    style.configure("TScrollbar", background=Theme.BG_SECOND, troughcolor=Theme.BG_MAIN,
                    borderwidth=0, arrowsize=12)
    style.map("TScrollbar", background=[("active", Theme.ACCENT_LIGHT)])

    return style

# ═══════════════════════════════════════════════════════════
#  数据模型 (v13.0 新增粘贴历史栈)
# ═══════════════════════════════════════════════════════════
class ClipItem:
    __slots__ = ("content", "tag", "lock_status")
    def __init__(self, content: str = "", tag: str = "", lock_status: bool = False):
        self.content = content
        self.tag = tag
        self.lock_status = lock_status

    def to_dict(self) -> dict:
        return {"content": self.content, "tag": self.tag, "lock": self.lock_status}

    @staticmethod
    def from_dict(d: dict) -> "ClipItem":
        return ClipItem(
            d.get("content", ""),
            d.get("tag", ""),
            d.get("lock", False)
        )

    @property
    def preview(self) -> str:
        text = self.content.replace("\n", " ").replace("\r", " ").replace("\t", " ")
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > PREVIEW_LENGTH:
            return text[:PREVIEW_LENGTH] + "…"
        return text or "(空)"

class ClipboardQueue:
    def __init__(self, max_size: int = MAX_QUEUE_SIZE):
        self._items: list[ClipItem] = []
        self.max_size = max_size
        self._lock = threading.Lock()
        # v13.0 粘贴历史栈 (先进后出)
        self.undo_stack: list[ClipItem] = []
        self.undo_lock = threading.Lock()

    @property
    def size(self) -> int:
        return len(self._items)

    @property
    def is_full(self) -> bool:
        return len(self._items) >= self.max_size

    @property
    def is_empty(self) -> bool:
        return len(self._items) == 0

    @property
    def last_content(self) -> str:
        with self._lock:
            return self._items[-1].content if self._items else ""

    def add(self, item: ClipItem) -> bool:
        with self._lock:
            if len(self._items) >= self.max_size:
                return False
            self._items.append(item)
            return True

    def pop_front(self) -> ClipItem | None:
        with self._lock:
            return self._items.pop(0) if self._items else None

    def peek_front(self) -> ClipItem | None:
        with self._lock:
            return self._items[0] if self._items else None

    def delete(self, index: int) -> bool:
        with self._lock:
            if 0 <= index < len(self._items):
                self._items.pop(index)
                return True
            return False

    def delete_many(self, indices: list[int]) -> int:
        count = 0
        with self._lock:
            for i in sorted(indices, reverse=True):
                if 0 <= i < len(self._items):
                    self._items.pop(i)
                    count += 1
        return count

    def move(self, from_idx: int, to_idx: int):
        with self._lock:
            if not (0 <= from_idx < len(self._items) and 0 <= to_idx < len(self._items)):
                return
            if from_idx == to_idx:
                return
            item = self._items.pop(from_idx)
            if to_idx > from_idx:
                to_idx -= 1
            self._items.insert(to_idx, item)

    def move_to_front(self, indices: list[int]):
        with self._lock:
            moved = []
            for i in sorted(indices, reverse=True):
                if 0 <= i < len(self._items):
                    moved.append(self._items.pop(i))
            for item in reversed(moved):
                self._items.insert(0, item)

    def move_to_back(self, indices: list[int]):
        with self._lock:
            moved = []
            for i in sorted(indices, reverse=True):
                if 0 <= i < len(self._items):
                    moved.append(self._items.pop(i))
            self._items.extend(reversed(moved))

    def clear(self):
        with self._lock:
            self._items.clear()
            self.undo_stack.clear()  # 清空撤回历史

    def get_all(self) -> list[ClipItem]:
        with self._lock:
            return list(self._items)

    def get_item(self, index: int) -> ClipItem | None:
        with self._lock:
            return self._items[index] if 0 <= index < len(self._items) else None

    def update_content(self, index: int, content: str):
        with self._lock:
            if 0 <= index < len(self._items):
                self._items[index].content = content

    def set_tag(self, index: int, tag: str):
        with self._lock:
            if 0 <= index < len(self._items):
                self._items[index].tag = tag

    def set_lock(self, index: int, locked: bool):
        with self._lock:
            if 0 <= index < len(self._items):
                self._items[index].lock_status = locked

    def set_lock_many(self, indices: list[int], locked: bool):
        with self._lock:
            for i in indices:
                if 0 <= i < len(self._items):
                    self._items[i].lock_status = locked

    def get_lock(self, index: int) -> bool:
        with self._lock:
            return self._items[index].lock_status if 0 <= index < len(self._items) else False

    # v13.0 撤回功能
    def push_undo(self, item: ClipItem):
        """将刚粘贴的条目存入撤回栈"""
        with self.undo_lock:
            self.undo_stack.append(item)
            if len(self.undo_stack) > UNDO_HISTORY_SIZE:
                self.undo_stack.pop(0)

    def pop_undo(self) -> ClipItem | None:
        """取回最近一次粘贴的条目"""
        with self.undo_lock:
            return self.undo_stack.pop() if self.undo_stack else None

    def get_undo_count(self) -> int:
        with self.undo_lock:
            return len(self.undo_stack)

    def save(self):
        ensure_config_dir()
        with self._lock:
            data = [item.to_dict() for item in self._items]
            try:
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            except IOError:
                pass

    def load(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._lock:
                self._items = [ClipItem.from_dict(d) for d in data]
                if len(self._items) > self.max_size:
                    self._items = self._items[-self.max_size:]
        except (json.JSONDecodeError, KeyError, IOError):
            pass

# ═══════════════════════════════════════════════════════════
#  粘贴序号计数器
# ═══════════════════════════════════════════════════════════
class PasteCounter:
    def __init__(self):
        self._last_index = -1
        self._count = 0
        self._lock = threading.Lock()

    def get_count(self, item_index: int) -> int:
        with self._lock:
            if item_index == self._last_index:
                self._count += 1
            else:
                self._last_index = item_index
                self._count = 1
            return self._count

    def reset(self):
        with self._lock:
            self._last_index = -1
            self._count = 0

# ═══════════════════════════════════════════════════════════
#  灵动通知卡片 (v13.0 新增)
# ═══════════════════════════════════════════════════════════
class ToastNotification:
    def __init__(self, root, bg=Theme.SUCCESS, fg=Theme.TEXT_PRIMARY):
        self.root = root
        self.bg = bg
        self.fg = fg
        self.win = None

    def show(self, message: str, duration=2000):
        if self.win:
            try:
                self.win.destroy()
            except tk.TclError:
                pass

        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=Theme.BORDER)

        inner = tk.Frame(self.win, bg=self.bg, padx=14, pady=6)
        inner.pack()
        lbl = tk.Label(inner, text=message, bg=self.bg, fg=self.fg, font=Theme.FONT_BOLD, wraplength=300)
        lbl.pack()

        # 位置：主窗口顶部中央
        self.root.update_idletasks()
        x = self.root.winfo_x() + self.root.winfo_width()//2 - self.win.winfo_reqwidth()//2
        y = self.root.winfo_y() + 30
        self.win.geometry(f"+{x}+{y}")
        self.win.attributes("-alpha", 0.0)

        self._fade_in(duration)

    def _fade_in(self, duration):
        alpha = 0.0
        step = 0.1
        def update():
            nonlocal alpha
            if not self.win:
                return
            alpha = min(1.0, alpha + step)
            self.win.attributes("-alpha", alpha)
            if alpha < 1.0:
                self.root.after(20, update)
            else:
                self.root.after(duration, self._fade_out)
        update()

    def _fade_out(self):
        if not self.win:
            return
        alpha = 1.0
        step = 0.1
        def update():
            nonlocal alpha
            if not self.win:
                return
            alpha = max(0.0, alpha - step)
            self.win.attributes("-alpha", alpha)
            if alpha > 0.0:
                self.root.after(20, update)
            else:
                try:
                    self.win.destroy()
                except tk.TclError:
                    pass
                self.win = None
        update()

# ═══════════════════════════════════════════════════════════
#  主 GUI 窗口 (v13.0 动画增强)
# ═══════════════════════════════════════════════════════════
class MainWindow:
    def __init__(self, queue: ClipboardQueue, counter: PasteCounter):
        self.queue = queue
        self.counter = counter
        self.paste_mode = "dequeue"
        self.hotkey_handler = None
        # 拖拽状态 (保留 v12.2 机制)
        self._drag = {
            "from": None,
            "active": False,
            "start_y": 0,
            "target_iid": None,
            "insert_before": True,
            "auto_scroll_id": None,
            "last_indicator_y": -1
        }
        self._search_timer = None
        self._tooltip = None
        self._tooltip_after_id = None
        self._tooltip_iid = None
        self._paste_lock = threading.Lock()

        self.root = tk.Tk()
        self.root.title("✦ QueueClip v13.0 — xun ✦")
        self.root.geometry("720x760")
        self.root.minsize(520, 420)
        self.root.configure(bg=Theme.BG_MAIN)
        self.root.attributes("-topmost", True)

        setup_anime_style(self.root)

        self._center_window()
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.root.bind("<Destroy>", self._on_destroy)

        # 初始化通知卡片
        self.toast = ToastNotification(self.root)

        self._build_ui()
        self._refresh_list()

        # 窗口显示时淡入
        self._fade_in_window()

    def set_hotkey_handler(self, handler):
        self.hotkey_handler = handler

    def _center_window(self, window=None):
        win = window or self.root
        win.update_idletasks()
        width = win.winfo_width()
        height = win.winfo_height()
        x = (win.winfo_screenwidth() // 2) - (width // 2)
        y = (win.winfo_screenheight() // 2) - (height // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")

    # ── 窗口动画 ──────────────────────────────────────
    def _fade_in_window(self):
        try:
            self.root.attributes("-alpha", 0.0)
        except tk.TclError:
            return
        alpha = 0.0
        step = 0.12
        def update():
            nonlocal alpha
            if not self.root or not self.root.winfo_exists():
                return
            alpha = min(1.0, alpha + step)
            self.root.attributes("-alpha", alpha)
            if alpha < 1.0:
                self.root.after(15, update)
        update()

    def hide_window(self):
        # 淡出后隐藏
        if self.root.state() == "withdrawn":
            return
        alpha = 1.0
        step = 0.15
        def fade():
            nonlocal alpha
            if not self.root.winfo_exists():
                return
            alpha = max(0.0, alpha - step)
            self.root.attributes("-alpha", alpha)
            if alpha > 0.0:
                self.root.after(12, fade)
            else:
                self.root.withdraw()
                self.root.attributes("-alpha", 1.0)  # 恢复以备下次
        fade()

    def show_window(self):
        self.root.deiconify()
        self._fade_in_window()
        self.root.lift()
        self.root.focus_force()
        self._refresh_list()

    def toggle_window(self):
        if self.root.state() == "withdrawn":
            self.show_window()
        else:
            self.hide_window()

    # ── UI 构建 ───────────────────────────────────────
    def _build_ui(self):
        # 标题栏
        title_frame = tk.Frame(self.root, bg=Theme.HEADER_BG, height=52)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)
        tk.Label(title_frame, text="🌸  QueueClip v13.0  —  xun",
                 font=Theme.FONT_TITLE, fg=Theme.ACCENT_DARK, bg=Theme.HEADER_BG).pack(side=tk.LEFT, padx=16, pady=12)
        self.lbl_status = tk.Label(title_frame, text="✦ 0 / 50", font=Theme.FONT_BOLD,
                                   fg="#FFFFFF", bg=Theme.ACCENT, padx=12, pady=3)
        self.lbl_status.pack(side=tk.RIGHT, padx=14, pady=12)

        # 主区域
        main = tk.Frame(self.root, bg=Theme.BG_MAIN, padx=10, pady=8)
        main.pack(fill=tk.BOTH, expand=True)

        # ── 顶栏 ──
        top_bar = tk.Frame(main, bg=Theme.BG_SECOND, padx=8, pady=6)
        top_bar.pack(fill=tk.X, pady=(0, 8))

        tk.Label(top_bar, text="🔍", bg=Theme.BG_SECOND, font=Theme.FONT_MAIN).pack(side=tk.LEFT, padx=(2, 4))
        self.var_search = tk.StringVar()
        self.var_search.trace_add("write", lambda *_: self._debounce_refresh())
        ttk.Entry(top_bar, textvariable=self.var_search, width=20, font=Theme.FONT_MAIN).pack(side=tk.LEFT, padx=(0, 16))

        tk.Label(top_bar, text="📌 队首粘贴模式：", bg=Theme.BG_SECOND, fg=Theme.TEXT_PRIMARY, font=Theme.FONT_MAIN).pack(side=tk.LEFT)
        self.var_mode = tk.StringVar(value="出队模式")
        cmb = ttk.Combobox(top_bar, textvariable=self.var_mode, values=["出队模式", "保留模式"],
                           state="readonly", width=9, font=Theme.FONT_MAIN)
        cmb.pack(side=tk.LEFT, padx=(2, 12))
        cmb.bind("<<ComboboxSelected>>", self._on_mode_change)
        tk.Label(top_bar, text="（单条锁优先级 > 全局模式）", bg=Theme.BG_SECOND, fg=Theme.TEXT_SECOND, font=Theme.FONT_SMALL).pack(side=tk.LEFT)

        self.var_block_native = tk.BooleanVar(value=False)
        chk = tk.Checkbutton(top_bar, text="🔒 接管Ctrl+C/V",
                             variable=self.var_block_native,
                             bg=Theme.BG_SECOND, fg=Theme.TEXT_PRIMARY,
                             activebackground=Theme.BG_SECOND,
                             activeforeground=Theme.ACCENT_DARK,
                             selectcolor=Theme.BG_CARD,
                             font=Theme.FONT_MAIN,
                             command=self._on_block_native_change)
        chk.pack(side=tk.RIGHT, padx=4)

        # ── 工具栏 ──
        bar = tk.Frame(main, bg=Theme.BG_MAIN)
        bar.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(bar, text="✦ 粘贴队首", command=self._paste_front_async, style="Success.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="✎ 手动添加", command=self._manual_add).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="🔄 重置序号", command=self._reset_counter).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="↩ 撤回粘贴", command=self._undo_last_paste).pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="✕ 清空队列", command=self._clear_queue, style="Danger.TButton").pack(side=tk.LEFT, padx=3)
        ttk.Button(bar, text="⏻ 退出程序", command=self._quit_app, style="Danger.TButton").pack(side=tk.RIGHT, padx=3)

        # ── 粘贴状态行 (v13.0 新增) ──
        status_bar = tk.Frame(main, bg=Theme.BG_SECOND, padx=8, pady=3)
        status_bar.pack(fill=tk.X, pady=(0, 6))
        self.lbl_paste_status = tk.Label(status_bar, text="📋 最近粘贴：—", bg=Theme.BG_SECOND, fg=Theme.TEXT_PRIMARY, font=Theme.FONT_SMALL, anchor=tk.W)
        self.lbl_paste_status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.lbl_undo_hint = tk.Label(status_bar, text="", bg=Theme.BG_SECOND, fg=Theme.ACCENT_DARK, font=Theme.FONT_SMALL, cursor="hand2")
        self.lbl_undo_hint.pack(side=tk.RIGHT, padx=6)
        self.lbl_undo_hint.bind("<Button-1>", lambda e: self._undo_last_paste())

        # ── 标签筛选栏 ──
        tag_bar = tk.Frame(main, bg=Theme.BG_SECOND, padx=8, pady=5)
        tag_bar.pack(fill=tk.X, pady=(0, 8))
        tk.Label(tag_bar, text="🏷 标签：", bg=Theme.BG_SECOND, fg=Theme.TEXT_PRIMARY, font=Theme.FONT_MAIN).pack(side=tk.LEFT)
        self.var_tag = tk.StringVar(value="全部")
        self.cmb_tag = ttk.Combobox(tag_bar, textvariable=self.var_tag, state="readonly", width=12, font=Theme.FONT_MAIN)
        self.cmb_tag.pack(side=tk.LEFT, padx=(2, 10))
        self.cmb_tag.bind("<<ComboboxSelected>>", lambda e: self._refresh_list())
        ttk.Button(tag_bar, text="设置标签", command=self._set_tag, style="Small.TButton").pack(side=tk.LEFT, padx=2)
        ttk.Button(tag_bar, text="清除标签", command=self._clear_tag, style="Small.TButton").pack(side=tk.LEFT, padx=2)

        tk.Label(tag_bar, text="│", bg=Theme.BG_SECOND, fg=Theme.BORDER, font=Theme.FONT_MAIN).pack(side=tk.LEFT, padx=6)
        ttk.Button(tag_bar, text="🔒 锁定", command=lambda: self._set_selected_lock(True), style="Small.TButton").pack(side=tk.LEFT, padx=2)
        ttk.Button(tag_bar, text="🔓 解锁", command=lambda: self._set_selected_lock(False), style="Small.TButton").pack(side=tk.LEFT, padx=2)

        tk.Label(tag_bar, text="│", bg=Theme.BG_SECOND, fg=Theme.BORDER, font=Theme.FONT_MAIN).pack(side=tk.LEFT, padx=6)
        ttk.Button(tag_bar, text="⬆ 批量置顶", command=self._move_selected_front, style="Small.TButton").pack(side=tk.LEFT, padx=2)
        ttk.Button(tag_bar, text="⬇ 批量置底", command=self._move_selected_back, style="Small.TButton").pack(side=tk.LEFT, padx=2)

        # ── 列表区 ──
        list_frame = tk.Frame(main, bg=Theme.BG_MAIN)
        list_frame.pack(fill=tk.BOTH, expand=True)
        border_frame = tk.Frame(list_frame, bg=Theme.BORDER, padx=2, pady=2)
        border_frame.pack(fill=tk.BOTH, expand=True)
        inner_frame = tk.Frame(border_frame, bg=Theme.BG_CARD)
        inner_frame.pack(fill=tk.BOTH, expand=True)

        cols = ("idx", "preview", "tag", "lock")
        self.tree = ttk.Treeview(inner_frame, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("idx", text=" # ")
        self.tree.heading("preview", text="  内容预览")
        self.tree.heading("tag", text="  标签")
        self.tree.heading("lock", text=" 🔒 ")
        self.tree.column("idx", width=44, anchor=tk.CENTER, stretch=False)
        self.tree.column("tag", width=90, anchor=tk.CENTER, stretch=False)
        self.tree.column("lock", width=44, anchor=tk.CENTER, stretch=False)
        self.tree.column("preview", width=460, minwidth=200)

        vsb = ttk.Scrollbar(inner_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(1, 0), pady=1)
        vsb.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 1), pady=1)

        # 拖拽指示条 (v13.0 呼吸灯渐变色)
        self.drag_indicator = tk.Frame(inner_frame, bg=Theme.ACCENT_DARK, height=2)
        self.drag_indicator.place_forget()
        self._drag_pulse_phase = 0
        self._drag_pulse_id = None

        # 事件绑定
        self.tree.bind("<Delete>", lambda e: self._delete_selected())
        self.tree.bind("<Button-3>", self._on_right_click)
        self.tree.bind("<Double-Button-1>", lambda e: self._paste_selected_async())
        self.tree.bind("<Button-1>", self._on_drag_start)
        self.tree.bind("<B1-Motion>", self._on_drag_motion)
        self.tree.bind("<ButtonRelease-1>", self._on_drag_release)
        self.tree.bind("<Motion>", self._on_mouse_move)
        self.tree.bind("<Leave>", self._hide_tooltip)
        self.tree.bind("<MouseWheel>", self._on_mouse_wheel)
        self.tree.bind("<Button-4>", lambda e: self._on_mouse_wheel(e, 1))
        self.tree.bind("<Button-5>", lambda e: self._on_mouse_wheel(e, -1))
        self.tree.bind("<Button-1>", self._on_lock_click, add="+")

        self.tree.tag_configure("even", background=Theme.ROW_EVEN)
        self.tree.tag_configure("odd", background=Theme.ROW_ODD)
        # 动画用 tag
        self.tree.tag_configure("insert_flash", background=Theme.SUCCESS)
        self.tree.tag_configure("delete_flash", background=Theme.DANGER)

        # 右键菜单
        self.menu = Menu(self.root, tearoff=0,
                         bg=Theme.BG_CARD, fg=Theme.TEXT_PRIMARY,
                         activebackground=Theme.ACCENT_LIGHT,
                         activeforeground=Theme.ACCENT_DARK,
                         font=Theme.FONT_MAIN, relief="flat", bd=1)
        self.menu.add_command(label="✦ 粘贴此条（不出队）", command=self._paste_selected_async)
        self.menu.add_separator()
        self.menu.add_command(label="📋 复制到系统剪贴板", command=self._copy_selected)
        self.menu.add_command(label="✎ 编辑内容…", command=self._edit_item)
        self.menu.add_command(label="🏷 设置标签…", command=self._set_tag)
        self.menu.add_separator()
        self.menu.add_command(label="🔒 锁定此条", command=lambda: self._set_selected_lock(True))
        self.menu.add_command(label="🔓 解锁此条", command=lambda: self._set_selected_lock(False))
        self.menu.add_separator()
        self.menu.add_command(label="⬆ 置顶到队首", command=self._move_to_front)
        self.menu.add_command(label="⬇ 置底到队尾", command=self._move_to_back)
        self.menu.add_separator()
        self.menu.add_command(label="✕ 删除选中", command=self._delete_selected)

        # 底部说明
        bottom = tk.Frame(main, bg=Theme.BG_MAIN)
        bottom.pack(fill=tk.X, pady=(6, 0))
        tk.Label(bottom, text="滚轮选择 ｜ 拖拽排序 ｜ 右键菜单 ｜ Ctrl+多选 ｜ Delete 删除 ｜ 双击粘贴（不出队）",
                 font=Theme.FONT_SMALL, fg=Theme.TEXT_SECOND, bg=Theme.BG_MAIN).pack()
        tk.Label(bottom, text="🌸 Alt+C 入队 ｜ Alt+V 粘贴 ｜ Alt+R 清空 ｜ Alt+E 唤出窗口 ｜ 点击🔒列切换锁定 ｜ ↩撤回最近粘贴",
                 font=Theme.FONT_SMALL, fg=Theme.ACCENT, bg=Theme.BG_MAIN).pack()

        decor = tk.Frame(main, bg=Theme.BG_MAIN, height=3)
        decor.pack(fill=tk.X)
        tk.Frame(decor, bg=Theme.ACCENT_LIGHT, height=1).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=40)

    # ── 原生拦截开关 ──────────────────────────────────
    def _on_block_native_change(self):
        if self.hotkey_handler:
            enabled = self.var_block_native.get()
            self.hotkey_handler.set_block_native(enabled)
            if enabled:
                messagebox.showinfo("🔒 已接管",
                    "已全局接管 Ctrl+C / Ctrl+V\n\n"
                    "Ctrl+C → 加入队列\n"
                    "Ctrl+V → 队列粘贴\n"
                    "原生复制粘贴已暂时失效\n"
                    "取消勾选即可恢复正常")

    # ── 列表刷新 (带闪烁动画支持) ─────────────────────
    def _refresh_list(self, animate_items: list[int] = None, flash_type="insert"):
        """刷新列表，可选地标记某些行执行闪烁动画"""
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())

        keyword = self.var_search.get().strip().lower()
        tag_filter = self.var_tag.get()
        items = self.queue.get_all()
        visible = 0

        for i, item in enumerate(items):
            if keyword and keyword not in item.content.lower() and keyword not in item.tag.lower():
                continue
            if tag_filter == "无标签":
                if item.tag != "":
                    continue
            elif tag_filter != "全部" and item.tag != tag_filter:
                continue

            tag_str = f"🏷 {item.tag}" if item.tag else ""
            lock_str = "🔒" if item.lock_status else "🔓"
            row_tag = "even" if visible % 2 == 0 else "odd"
            iid = str(i)
            self.tree.insert("", tk.END, iid=iid,
                             values=(i + 1, item.preview, tag_str, lock_str),
                             tags=(row_tag,))
            visible += 1

        self.lbl_status.config(text=f"✦ {self.queue.size} / {MAX_QUEUE_SIZE}")

        all_tags = sorted({it.tag for it in items if it.tag})
        tag_values = ["全部", "无标签"] + all_tags
        self.cmb_tag["values"] = tag_values
        if self.var_tag.get() not in tag_values:
            self.var_tag.set("全部")

        # 如果指定了动画行，执行背景闪烁
        if animate_items:
            for idx in animate_items:
                iid = str(idx)
                if self.tree.exists(iid):
                    self._animate_row_flash(iid, flash_type)

        self._update_paste_status_display()

    def _animate_row_flash(self, iid, flash_type="insert"):
        """行背景闪烁动画（模拟滑入/滑出）"""
        color = Theme.SUCCESS if flash_type == "insert" else Theme.DANGER
        steps = 5
        interval = FLASH_DURATION_MS // steps
        alpha_values = [1.0, 0.8, 0.6, 0.4, 0.2, 0.0]
        original_tags = self.tree.item(iid, "tags")
        base_tag = original_tags[0]  # even or odd

        def set_color(step):
            if not self.tree.exists(iid):
                return
            if step >= len(alpha_values):
                self.tree.item(iid, tags=(base_tag,))
                return
            a = alpha_values[step]
            r, g, b = self._hex_to_rgb(color)
            bg = self._hex_to_rgb(Theme.ROW_EVEN if base_tag == "even" else Theme.ROW_ODD)
            blend = [int(bg[j] + (r - bg[j]) * a) for j in range(3)]
            hex_color = f"#{blend[0]:02x}{blend[1]:02x}{blend[2]:02x}"
            self.tree.tag_configure(f"flash_{iid}", background=hex_color)
            self.tree.item(iid, tags=(f"flash_{iid}",))
            self.root.after(interval, lambda: set_color(step + 1))
        set_color(0)

    @staticmethod
    def _hex_to_rgb(hex_str):
        h = hex_str.lstrip('#')
        return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

    def _debounce_refresh(self):
        if self._search_timer:
            self.root.after_cancel(self._search_timer)
        self._search_timer = self.root.after(180, self._refresh_list)

    def _selected_queue_indices(self) -> list[int]:
        return sorted(int(iid) for iid in self.tree.selection())

    def _get_visible_items(self) -> list[str]:
        return list(self.tree.get_children())

    # ── 粘贴状态显示 ──────────────────────────────────
    def _update_paste_status_display(self):
        """更新底部粘贴状态栏"""
        count = self.queue.get_undo_count()
        if count > 0:
            item = self.queue.undo_stack[-1]
            preview = item.preview[:25]
            self.lbl_paste_status.config(text=f"📋 最近粘贴：{preview}")
            self.lbl_undo_hint.config(text=f"↩ 撤回 ({count}条可撤)")
        else:
            self.lbl_paste_status.config(text="📋 最近粘贴：—")
            self.lbl_undo_hint.config(text="")

    def _undo_last_paste(self):
        """撤回最近一次粘贴"""
        item = self.queue.pop_undo()
        if item:
            # 插入到队首
            self.queue.add(item)  # 会加到队尾，我们需要插入到0
            # 手动移到队首
            with self.queue._lock:
                items = self.queue._items
                if items and items[-1] == item:
                    items.pop()
                    items.insert(0, item)
            self._refresh_list()
            self.queue.save()
            self.toast.show("↩ 已撤回上一次粘贴到队首", duration=1500)
        else:
            self.toast.show("没有可撤回的粘贴记录", duration=1000)

    # ── 滚轮选择 ─────────────────────────────────────
    def _on_mouse_wheel(self, event, direction=None):
        if self._drag["active"]:
            return
        children = self._get_visible_items()
        if not children:
            return
        selected = self.tree.selection()
        if not selected:
            self.tree.selection_set(children[0])
            self.tree.see(children[0])
            return "break"
        current_iid = selected[0]
        try:
            current_idx = children.index(current_iid)
        except ValueError:
            current_idx = 0
        if direction is None:
            delta = 1 if event.delta > 0 else -1
        else:
            delta = direction
        new_idx = current_idx - delta
        new_idx = max(0, min(new_idx, len(children) - 1))
        new_iid = children[new_idx]
        self.tree.selection_remove(*selected)
        self.tree.selection_set(new_iid)
        self.tree.see(new_iid)
        return "break"

    # ── 锁列点击 ─────────────────────────────────────
    def _on_lock_click(self, event):
        column = self.tree.identify_column(event.x)
        if column == "#4":
            iid = self.tree.identify_row(event.y)
            if iid:
                idx = int(iid)
                current_lock = self.queue.get_lock(idx)
                self.queue.set_lock(idx, not current_lock)
                self._refresh_list()
                self.queue.save()
            return "break"

    def _set_selected_lock(self, locked: bool):
        idxs = self._selected_queue_indices()
        if not idxs:
            messagebox.showinfo("提示", "请先选中要操作的条目")
            return
        self.queue.set_lock_many(idxs, locked)
        self._refresh_list()
        self.queue.save()

    # ── v13.0 粘贴核心：延迟出队 + 撤回存储 ──────────
    def _paste_front_async(self):
        threading.Thread(target=self._paste_front, daemon=True).start()

    def _paste_selected_async(self):
        threading.Thread(target=self._paste_selected, daemon=True).start()

    def _paste_front(self):
        """队首粘贴，带延迟出队与撤回记录"""
        item = self.queue.peek_front()
        if not item:
            return

        if item.lock_status:
            count = self.counter.get_count(0)
            final_text = f"{item.content}-{count}"
            should_pop = False
        else:
            if self.paste_mode == "dequeue":
                final_text = item.content
                should_pop = True
            else:
                count = self.counter.get_count(0)
                final_text = f"{item.content}-{count}"
                should_pop = False

        # 执行粘贴，但不立即出队
        self._do_paste_v13(final_text, should_pop=should_pop, item=item)

    def _paste_selected(self):
        """粘贴选中内容（不出队）"""
        idxs = []
        def get_selected():
            nonlocal idxs
            idxs = self._selected_queue_indices()
        self.root.after(0, get_selected)
        time.sleep(0.02)
        if not idxs:
            return
        item = self.queue.get_item(idxs[0])
        if not item:
            return

        if item.lock_status or self.paste_mode == "keep":
            count = self.counter.get_count(idxs[0])
            final_text = f"{item.content}-{count}"
        else:
            final_text = item.content

        self._do_paste_v13(final_text, should_pop=False, item=None)

    def _do_paste_v13(self, text: str, should_pop=False, item: ClipItem = None):
        """v13.0 粘贴引擎：先粘贴，延迟出队，失败可撤回"""
        if not ClipboardHelper.safe_copy(text):
            self.toast.show("❌ 写入剪贴板失败", duration=2000)
            return

        # 模拟 Ctrl+V
        time.sleep(0.05)
        try:
            keyboard.press_and_release("ctrl+v")
        except Exception:
            pass

        # 如果应该出队，延迟执行
        if should_pop and item:
            # 从队列移出并存入撤回栈
            popped = self.queue.pop_front()
            if popped:
                self.queue.push_undo(popped)
                self.queue.save()
                # 动画刷新
                self.root.after(0, lambda: self._refresh_list(animate_items=[], flash_type="delete"))
                self.toast.show(f"✅ 已粘贴并出队：{popped.preview[:20]}...", duration=2000)
        else:
            self.toast.show("✅ 已粘贴（保留队列）", duration=1500)
            self.root.after(0, self._refresh_list)

        # 更新粘贴状态
        self.root.after(0, self._update_paste_status_display)

    def _on_mode_change(self, event=None):
        self.paste_mode = "dequeue" if self.var_mode.get() == "出队模式" else "keep"

    def _reset_counter(self):
        self.counter.reset()
        self.toast.show("🔄 序号已重置", duration=1000)

    # ── 清空 / 添加 / 删除 ───────────────────────────
    def _clear_queue(self):
        if self.queue.is_empty:
            messagebox.showinfo("(´・ω・`)", "队列已经空空如也~")
            return
        if messagebox.askyesno("⚠ 确认清空",
                               f"确定清空全部 {self.queue.size} 条内容吗？"):
            self.queue.clear()
            self.counter.reset()
            self._refresh_list()
            self.queue.save()

    def _manual_add(self):
        content = ClipboardHelper.safe_paste()
        if not content or not str(content).strip():
            messagebox.showinfo("(´・ω・`)", "系统剪贴板为空，请先复制内容~")
            return
        self._add_content(str(content))

    def _add_content(self, content: str) -> bool:
        if not content or not content.strip():
            return False
        if self.queue.last_content == content:
            return False
        if self.queue.is_full:
            messagebox.showwarning("⚠ 队列已满",
                                   f"队列已达上限（{MAX_QUEUE_SIZE} 条），请先清出空间~")
            return False
        self.queue.add(ClipItem(content))
        # 插入动画：新条目索引为 len-1
        new_idx = self.queue.size - 1
        self._refresh_list(animate_items=[new_idx], flash_type="insert")
        self.queue.save()
        return True

    def _delete_selected(self):
        idxs = self._selected_queue_indices()
        if not idxs:
            return
        if messagebox.askyesno("确认删除", f"确定要删除选中的 {len(idxs)} 条内容吗？"):
            self.queue.delete_many(idxs)
            self.counter.reset()
            self._refresh_list(animate_items=[], flash_type="delete")
            self.queue.save()

    # ── 右键菜单 ────────────────────────────────────
    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid and iid not in self.tree.selection():
            self.tree.selection_set(iid)
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _copy_selected(self):
        idxs = self._selected_queue_indices()
        if idxs:
            item = self.queue.get_item(idxs[0])
            if item:
                ClipboardHelper.safe_copy(item.content)
                self.toast.show("📋 已复制到系统剪贴板", duration=1200)

    def _move_to_front(self):
        idxs = self._selected_queue_indices()
        if idxs:
            self.queue.move_to_front(idxs)
            self._refresh_list()
            self.queue.save()

    def _move_to_back(self):
        idxs = self._selected_queue_indices()
        if idxs:
            self.queue.move_to_back(idxs)
            self._refresh_list()
            self.queue.save()

    def _move_selected_front(self):
        self._move_to_front()
    def _move_selected_back(self):
        self._move_to_back()

    # ── 编辑条目 ────────────────────────────────────
    def _edit_item(self):
        idxs = self._selected_queue_indices()
        if not idxs:
            messagebox.showinfo("提示", "请先选中要编辑的条目")
            return
        item = self.queue.get_item(idxs[0])
        if not item:
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("✎ 编辑条目内容")
        dlg.geometry("540x400")
        dlg.configure(bg=Theme.BG_MAIN)
        dlg.transient(self.root)
        dlg.grab_set()
        self._center_window(dlg)

        tk.Label(dlg, text="编辑内容（支持多行）：", bg=Theme.BG_MAIN, fg=Theme.TEXT_PRIMARY,
                 font=Theme.FONT_BOLD).pack(padx=12, pady=(12, 4), anchor=tk.W)
        txt_frame = tk.Frame(dlg, bg=Theme.BORDER, padx=1, pady=1)
        txt_frame.pack(padx=12, pady=4, fill=tk.BOTH, expand=True)
        txt = tk.Text(txt_frame, wrap=tk.WORD, width=60, height=16,
                      bg=Theme.BG_CARD, fg=Theme.TEXT_PRIMARY,
                      font=Theme.FONT_MONO, relief="flat",
                      padx=8, pady=6, borderwidth=0,
                      insertbackground=Theme.ACCENT)
        txt.insert("1.0", item.content)
        txt.pack(fill=tk.BOTH, expand=True)
        txt.focus_set()

        def save():
            self.queue.update_content(idxs[0], txt.get("1.0", "end-1c"))
            self._refresh_list()
            self.queue.save()
            dlg.destroy()

        bf = tk.Frame(dlg, bg=Theme.BG_MAIN)
        bf.pack(pady=(8, 12))
        ttk.Button(bf, text="✦ 保存", command=save, style="Success.TButton").pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.LEFT, padx=5)
        txt.bind("<Control-Return>", lambda e: save())

    # ── 标签操作 ────────────────────────────────────
    def _set_tag(self):
        idxs = self._selected_queue_indices()
        if not idxs:
            messagebox.showinfo("(´・ω・`)", "请先选中条目")
            return
        cur = self.queue.get_item(idxs[0]).tag
        dlg = tk.Toplevel(self.root)
        dlg.title("🏷 设置标签")
        dlg.geometry("320x140")
        dlg.configure(bg=Theme.BG_MAIN)
        dlg.transient(self.root)
        dlg.grab_set()
        self._center_window(dlg)
        tk.Label(dlg, text="标签名称：", bg=Theme.BG_MAIN, fg=Theme.TEXT_PRIMARY,
                 font=Theme.FONT_BOLD).pack(padx=12, pady=(16, 6))
        var = tk.StringVar(value=cur)
        ent = ttk.Entry(dlg, textvariable=var, width=28, font=Theme.FONT_MAIN)
        ent.pack(padx=12, pady=4)
        ent.focus_set()
        ent.select_range(0, tk.END)
        def save():
            tag = var.get().strip()
            for i in idxs:
                self.queue.set_tag(i, tag)
            self._refresh_list()
            self.queue.save()
            dlg.destroy()
        bf = tk.Frame(dlg, bg=Theme.BG_MAIN)
        bf.pack(pady=8)
        ttk.Button(bf, text="✦ 确定", command=save, style="Success.TButton").pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="取消", command=dlg.destroy).pack(side=tk.LEFT, padx=5)
        ent.bind("<Return>", lambda e: save())

    def _clear_tag(self):
        idxs = self._selected_queue_indices()
        if not idxs:
            messagebox.showinfo("提示", "请先选中要操作的条目")
            return
        if messagebox.askyesno("确认", f"确定要清除选中 {len(idxs)} 条目的标签吗？"):
            for i in idxs:
                self.queue.set_tag(i, "")
            self._refresh_list()
            self.queue.save()

    # ── 拖拽排序 (v12.2 核心保留，指示条呼吸动画) ───
    def _hide_drag_indicator(self):
        self.drag_indicator.place_forget()
        self._drag["last_indicator_y"] = -1
        self._stop_indicator_pulse()

    def _start_indicator_pulse(self):
        """指示条呼吸灯效果"""
        if self._drag_pulse_id:
            return
        self._drag_pulse_phase = 0
        def pulse():
            if not self._drag["active"]:
                self._stop_indicator_pulse()
                return
            self._drag_pulse_phase = (self._drag_pulse_phase + 0.1) % 2
            # 颜色在 ACCENT 和 ACCENT_LIGHT 之间变化
            ratio = abs(1.0 - self._drag_pulse_phase)
            r1, g1, b1 = self._hex_to_rgb(Theme.ACCENT_DARK)
            r2, g2, b2 = self._hex_to_rgb(Theme.ACCENT_LIGHT)
            r = int(r1 + (r2 - r1) * ratio)
            g = int(g1 + (g2 - g1) * ratio)
            b = int(b1 + (b2 - b1) * ratio)
            color = f"#{r:02x}{g:02x}{b:02x}"
            self.drag_indicator.configure(bg=color)
            self._drag_pulse_id = self.root.after(80, pulse)
        pulse()

    def _stop_indicator_pulse(self):
        if self._drag_pulse_id:
            self.root.after_cancel(self._drag_pulse_id)
            self._drag_pulse_id = None

    def _stop_auto_scroll(self):
        if self._drag["auto_scroll_id"]:
            self.root.after_cancel(self._drag["auto_scroll_id"])
            self._drag["auto_scroll_id"] = None

    def _auto_scroll(self, direction: int):
        if not self._drag["active"]:
            return
        children = self._get_visible_items()
        if not children:
            return
        current_top = self.tree.index(children[0])
        new_top = max(0, min(current_top - direction, len(children)-1))
        self.tree.see(children[new_top])
        self._update_drag_indicator_by_mouse()
        self._drag["auto_scroll_id"] = self.root.after(
            AUTO_SCROLL_INTERVAL, lambda: self._auto_scroll(direction))

    def _update_drag_indicator_by_mouse(self):
        root_y = self.tree.winfo_rooty()
        mouse_y = self.root.winfo_pointery()
        rel_y = mouse_y - root_y
        self._update_drag_indicator(rel_y)

    def _update_drag_indicator(self, rel_y: int):
        children = self._get_visible_items()
        if not children:
            self._hide_drag_indicator()
            return
        tree_height = self.tree.winfo_height()
        if rel_y >= tree_height:
            last_bbox = self.tree.bbox(children[-1])
            if last_bbox:
                indicator_y = last_bbox[1] + last_bbox[3]
                self._drag["target_iid"] = None
                self._drag["insert_before"] = False
            else:
                self._hide_drag_indicator()
                return
        elif rel_y < 0:
            indicator_y = 0
            self._drag["target_iid"] = children[0]
            self._drag["insert_before"] = True
        else:
            target_iid = self.tree.identify_row(rel_y)
            if not target_iid:
                self._hide_drag_indicator()
                return
            bbox = self.tree.bbox(target_iid)
            if not bbox:
                self._hide_drag_indicator()
                return
            mid_y = bbox[1] + bbox[3] / 2
            if rel_y < mid_y:
                indicator_y = bbox[1]
                insert_before = True
            else:
                indicator_y = bbox[1] + bbox[3]
                insert_before = False
            self._drag["target_iid"] = target_iid
            self._drag["insert_before"] = insert_before

        if indicator_y == self._drag["last_indicator_y"]:
            return
        self._drag["last_indicator_y"] = indicator_y
        tree_width = self.tree.winfo_width()
        x_offset = self.tree.winfo_x()
        self.drag_indicator.place(
            x=x_offset,
            y=indicator_y + self.tree.winfo_y() - 1,
            width=tree_width,
            height=2)
        self._start_indicator_pulse()

    def _on_drag_start(self, event):
        column = self.tree.identify_column(event.x)
        if column == "#4":
            return
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        self._drag = {
            "from": iid,
            "active": False,
            "start_y": event.y,
            "target_iid": None,
            "insert_before": True,
            "auto_scroll_id": None,
            "last_indicator_y": -1
        }
        self.tree.selection_set(iid)

    def _on_drag_motion(self, event):
        if self._drag["from"] is None:
            return
        if abs(event.y - self._drag["start_y"]) > DRAG_THRESHOLD:
            if not self._drag["active"]:
                self._drag["active"] = True
        if not self._drag["active"]:
            return
        self._update_drag_indicator(event.y)
        self._stop_auto_scroll()
        tree_height = self.tree.winfo_height()
        if event.y < AUTO_SCROLL_EDGE:
            self._auto_scroll(1)
        elif event.y > tree_height - AUTO_SCROLL_EDGE:
            self._auto_scroll(-1)

    def _on_drag_release(self, event):
        self._hide_drag_indicator()
        self._stop_auto_scroll()
        if not self._drag["active"] or self._drag["from"] is None:
            self._drag = {
                "from": None, "active": False, "start_y": 0,
                "target_iid": None, "insert_before": True,
                "auto_scroll_id": None, "last_indicator_y": -1
            }
            return
        from_idx = int(self._drag["from"])
        children = self._get_visible_items()
        if self._drag["target_iid"] is None:
            to_idx = self.queue.size - 1
        else:
            target_idx = int(self._drag["target_iid"])
            if self._drag["insert_before"]:
                to_idx = target_idx
            else:
                to_idx = target_idx + 1
        to_idx = max(0, min(to_idx, self.queue.size - 1))
        self._drag = {
            "from": None, "active": False, "start_y": 0,
            "target_iid": None, "insert_before": True,
            "auto_scroll_id": None, "last_indicator_y": -1
        }
        if from_idx != to_idx:
            self.queue.move(from_idx, to_idx)
            self.counter.reset()
            self._refresh_list(animate_items=[to_idx], flash_type="insert")
            self.queue.save()

    # ── 悬浮提示 ────────────────────────────────────────
    def _on_mouse_move(self, event):
        if self._drag["active"]:
            return
        iid = self.tree.identify_row(event.y)
        if self._tooltip_after_id:
            self.root.after_cancel(self._tooltip_after_id)
            self._tooltip_after_id = None
        if self._tooltip and iid == self._tooltip_iid:
            x, y = event.x_root + 16, event.y_root + 12
            self._tooltip.wm_geometry(f"+{x}+{y}")
            return
        self._hide_tooltip()
        if iid:
            self._tooltip_iid = iid
            self._tooltip_after_id = self.root.after(
                TOOLTIP_DELAY_MS, lambda: self._show_tooltip_delayed(event, iid))

    def _show_tooltip_delayed(self, event, iid):
        item = self.queue.get_item(int(iid))
        if item:
            self._show_tooltip(event, item.content)
        self._tooltip_after_id = None

    def _show_tooltip(self, event, text: str):
        self._hide_tooltip()
        display = text if len(text) <= TOOLTIP_MAX_CHARS else text[:TOOLTIP_MAX_CHARS] + "\n\n…（内容过长已截断）"
        x, y = event.x_root + 16, event.y_root + 12
        tw = tk.Toplevel(self.root)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.attributes("-topmost", True)
        tw.configure(bg=Theme.BORDER)
        inner = tk.Frame(tw, bg=Theme.TOOLTIP_BG, padx=1, pady=1)
        inner.pack()
        tk.Label(inner, text=display, justify=tk.LEFT,
                 bg=Theme.TOOLTIP_BG, fg=Theme.TEXT_PRIMARY,
                 wraplength=420, padx=10, pady=6,
                 font=Theme.FONT_MAIN).pack()
        self._tooltip = tw

    def _hide_tooltip(self, event=None):
        if self._tooltip:
            self._tooltip.destroy()
            self._tooltip = None
        self._tooltip_iid = None

    def _quit_app(self):
        if messagebox.askyesno("🌸 确认退出",
                               "确定退出 QueueClip 吗？\n队列内容会自动保存，下次启动恢复~"):
            self.queue.save()
            if self.hotkey_handler:
                self.hotkey_handler.stop()
            self.root.quit()
            self.root.destroy()
            os._exit(0)

    def _on_destroy(self, event):
        if event.widget is self.root:
            self.queue.save()

    def run(self):
        self.root.mainloop()

# ═══════════════════════════════════════════════════════════
#  全局快捷键监听 (v13.0 粘贴安全升级)
# ═══════════════════════════════════════════════════════════
class HotkeyHandler:
    def __init__(self, queue: ClipboardQueue, window: MainWindow, counter: PasteCounter):
        self.queue = queue
        self.win = window
        self.counter = counter
        self._running = True
        self._block_native = False
        self._last_add_time = 0
        self._last_paste_time = 0
        self._add_lock = threading.Lock()
        self._paste_lock = threading.Lock()

    def start(self):
        t = threading.Thread(target=self._listen, daemon=True, name="hotkey-thread")
        t.start()

    def stop(self):
        self._running = False
        try:
            keyboard.unhook_all()
        except Exception:
            pass

    def set_block_native(self, enabled: bool):
        self._block_native = enabled
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        self._register_hotkeys()

    def _register_hotkeys(self):
        try:
            keyboard.add_hotkey("alt+c", self._on_add, suppress=True)
            keyboard.add_hotkey("alt+v", self._on_paste, suppress=True)
            keyboard.add_hotkey("alt+r", self._on_clear, suppress=True)
            keyboard.add_hotkey("alt+e", self._on_toggle, suppress=True)

            if self._block_native:
                keyboard.add_hotkey("ctrl+c", self._on_add_ctrlc, suppress=True)
                keyboard.add_hotkey("ctrl+v", self._on_paste_ctrlv, suppress=True)
        except Exception as e:
            self.win.root.after(0, lambda: messagebox.showwarning(
                "⚠ 快捷键注册失败",
                f"无法注册全局快捷键，请以管理员身份重新运行。\n错误：{e}"
            ))

    def _listen(self):
        self._register_hotkeys()
        while self._running:
            time.sleep(0.3)

    def _check_debounce(self, last_time_var: str, threshold_ms=DEBOUNCE_MS) -> bool:
        now = time.time()
        threshold = threshold_ms / 1000
        with self._add_lock if last_time_var == "_last_add_time" else self._paste_lock:
            last = getattr(self, last_time_var)
            if now - last < threshold:
                return False
            setattr(self, last_time_var, now)
            return True

    def _on_add(self):
        if not self._check_debounce("_last_add_time"):
            return
        threading.Thread(target=self._add_with_copy, daemon=True).start()

    def _add_with_copy(self):
        timeout = time.time() + 1.0
        try:
            while keyboard.is_pressed("alt") and time.time() < timeout:
                time.sleep(0.03)
        except Exception:
            time.sleep(0.15)
        try:
            keyboard.press_and_release("ctrl+c")
            time.sleep(0.25)
        except Exception:
            pass
        self._add_from_clipboard()

    def _on_paste(self):
        if not self._check_debounce("_last_paste_time"):
            return
        threading.Thread(target=self._paste_front_v13, daemon=True).start()

    def _on_clear(self):
        self.win.root.after(0, self._confirm_clear)

    def _on_toggle(self):
        self.win.root.after(0, self.win.toggle_window)

    def _on_add_ctrlc(self):
        if not self._check_debounce("_last_add_time"):
            return
        try:
            keyboard.unhook_key("ctrl+c")
        except Exception:
            pass
        try:
            keyboard.press_and_release("ctrl+c")
            time.sleep(0.25)
        except Exception:
            pass
        try:
            keyboard.add_hotkey("ctrl+c", self._on_add_ctrlc, suppress=True)
        except Exception:
            pass
        self._add_from_clipboard()

    def _on_paste_ctrlv(self):
        if not self._check_debounce("_last_paste_time"):
            return
        threading.Thread(target=self._paste_front_v13, daemon=True).start()

    def _add_from_clipboard(self):
        raw = ClipboardHelper.safe_paste()
        if not raw or not str(raw).strip():
            return
        content = str(raw).strip()
        if self.queue.last_content == content:
            return
        if self.queue.is_full:
            return
        if self.queue.add(ClipItem(content)):
            self.queue.save()
            self.win.root.after(0, self.win._refresh_list)

    def _paste_front_v13(self):
        """快捷键粘贴，复用 MainWindow 的安全粘贴逻辑"""
        item = self.queue.peek_front()
        if not item:
            return
        if item.lock_status:
            count = self.counter.get_count(0)
            final_text = f"{item.content}-{count}"
            should_pop = False
        else:
            if self.win.paste_mode == "dequeue":
                final_text = item.content
                should_pop = True
            else:
                count = self.counter.get_count(0)
                final_text = f"{item.content}-{count}"
                should_pop = False

        if not ClipboardHelper.safe_copy(final_text):
            self.win.toast.show("❌ 写入剪贴板失败", duration=2000)
            return

        time.sleep(0.08)
        try:
            keyboard.press_and_release("ctrl+v")
        except Exception:
            pass

        if should_pop:
            popped = self.queue.pop_front()
            if popped:
                self.queue.push_undo(popped)
                self.queue.save()
                self.win.root.after(0, lambda: self.win._refresh_list(animate_items=[], flash_type="delete"))
                self.win.root.after(0, lambda: self.win.toast.show(f"✅ 已粘贴并出队", duration=2000))
        else:
            self.win.root.after(0, lambda: self.win.toast.show("✅ 已粘贴（保留队列）", duration=1500))
            self.win.root.after(0, self.win._refresh_list)

    def _confirm_clear(self):
        if self.queue.is_empty:
            return
        if messagebox.askyesno("⚠ 确认清空",
                               f"确定清空全部 {self.queue.size} 条内容吗？"):
            self.queue.clear()
            self.counter.reset()
            self.queue.save()
            self.win._refresh_list()

# ═══════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════
def check_admin_privilege() -> bool:
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def main():
    ensure_config_dir()

    if not check_admin_privilege():
        temp_root = tk.Tk()
        temp_root.withdraw()
        messagebox.showwarning("⚠ 权限不足",
            "检测到未以管理员身份运行！\n\n"
            "全局快捷键功能需要管理员权限才能正常工作。\n"
            "请右键脚本 → 选择「以管理员身份运行」。\n\n"
            "你也可以继续运行，但快捷键可能失效。")
        temp_root.destroy()

    queue = ClipboardQueue()
    queue.load()
    counter = PasteCounter()
    window = MainWindow(queue, counter)
    hotkey = HotkeyHandler(queue, window, counter)
    window.set_hotkey_handler(hotkey)
    hotkey.start()

    atexit.register(queue.save)

    print("═" * 56)
    print("  🌸 QueueClip v13.0  —  灵动安全版-xun")
    print("═" * 56)
    if queue.size:
        print(f"  ✦ 已恢复 {queue.size} 条历史队列内容")
    else:
        print("  ✦ 队列为空，开始使用吧~")
    print()
    print("  ✨ 新特性：")
    print("    🔒 粘贴延迟出队 + 撤回（最近5条可回滚）")
    print("    💬 浮动通知卡片，粘贴状态一目了然")
    print("    🎞️ 窗口淡入淡出、条目插入删除闪烁")
    print("    🌈 拖拽指示条呼吸灯效果")
    print("    📋 底部粘贴状态栏，点击可撤回")
    print()
    print("  快捷键速查：")
    print("    Alt+C 入队 ｜ Alt+V 粘贴 ｜ Alt+R 清空")
    print("    Alt+E 唤出窗口 ｜ Ctrl+C/V（需接管）")
    print("═" * 56)

    try:
        window.run()
    except KeyboardInterrupt:
        pass
    finally:
        queue.save()
        hotkey.stop()

if __name__ == "__main__":
    main()