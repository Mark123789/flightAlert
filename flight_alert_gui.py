from queue import Empty, Queue
import os
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from datetime import datetime
import sys
import logging

from app_logging import configure_logging
from monitoring import MonitorService, run_monitor
from settings import CABINS, display_date, load_config, normalize_config, save_config
from locations import get_readable_location

DEFAULT_SLEEP_TIME = 600
DEFAULT_PRICE_STEP = 50
logger = logging.getLogger(__name__)


def parse_monitor_config(
        dates_text: str, place_from_text: str, place_to_text: str,
        flight_way_text: str, sleep_time_text: str, price_step_text: str,
        sckey_text: str, search_type=1, grade=1, return_date_text="",
        adults_text="1", children_text="0", babies_text="0",
        allow_expired=False) -> dict:
    """GUI 和 CLI 共用配置规范化及校验。"""
    try:
        interval, threshold = int(sleep_time_text), int(price_step_text)
        counts = [int(value) for value in (adults_text, children_text, babies_text)]
    except (ValueError, TypeError) as exc:
        raise ValueError("检查间隔、价格阈值和乘客人数必须是整数") from exc
    return normalize_config({
        "dateToGo": [day.strip() for day in dates_text.replace("，", ",").split(",") if day.strip()],
        "placeFrom": place_from_text, "placeTo": place_to_text,
        "flightWay": flight_way_text, "sleepTime": interval, "priceStep": threshold,
        "SCKEY": sckey_text, "searchType": search_type, "grade": grade,
        "returnDate": return_date_text,
        "passengerList": [{"passengerType": kind, "passengerCount": count}
                          for kind, count in zip(("Adult", "Child", "Baby"), counts)],
    }, allow_expired=allow_expired)


class FlightAlertApp:
    def __init__(self, root):
        self.root = root
        self.root.title("航班价格监控")
        self.root.geometry("960x780")
        self.root.minsize(900, 760)
        
        # 设置自定义主题色
        self.bg_color = "#f5f5f5"
        self.accent_color = "#1E90FF"  # 蓝色
        self.text_color = "#333333"
        self.highlight_color = "#FFD700"  # 金色
        self.font_family = self._select_font_family()
        
        # 确保配置目录存在
        self.config_dir = self._get_config_dir()
        self.log_path = configure_logging(self.config_dir)
        
        # 配置样式
        self._setup_styles()
        
        # 变量初始化
        self.dates_var = tk.StringVar()
        self.place_from_var = tk.StringVar()
        self.place_to_var = tk.StringVar()
        self.flight_way_var = tk.StringVar(value="Oneway")
        self.sleep_time_var = tk.StringVar(value=str(DEFAULT_SLEEP_TIME))
        self.price_step_var = tk.StringVar(value=str(DEFAULT_PRICE_STEP))
        self.sckey_var = tk.StringVar()
        self.search_type_var = tk.StringVar(value="国内")
        self.grade_var = tk.StringVar(value="经济舱")
        self.return_date_var = tk.StringVar()
        self.adults_var = tk.StringVar(value="1")
        self.children_var = tk.StringVar(value="0")
        self.babies_var = tk.StringVar(value="0")
        
        # 监控状态
        self.running = False
        self.monitor_thread = None
        self.service = None
        self.closing = False
        self._events = Queue()
        self._generation = 0
        self._poll_after_id = None
        self._finish_after_id = None
        self._finish_message = "监控已停止"
        self.stop_event = threading.Event()
        self.config = None
        self.last_check_time = None
        
        # 创建UI
        self._create_ui()
        
        # 加载配置（如果存在）
        self._load_config()
        self._log(f"日志文件: {self.log_path}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_after_id = self.root.after(100, self._poll_events)
    
    def _get_config_dir(self):
        """获取配置文件目录"""
        # 在Windows上，使用用户的应用数据目录
        if sys.platform.startswith('win'):
            app_data = os.environ.get('APPDATA', '')
            if app_data:
                return os.path.join(app_data, 'flightAlert')
        
        # 在其他系统或备选方案：使用当前可执行文件所在目录
        return os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
    
    def _select_font_family(self):
        """按平台选择更稳妥的中文字体名称。"""
        if sys.platform.startswith('win'):
            return "微软雅黑"
        if sys.platform == 'darwin':
            return "PingFang SC"
        return "Noto Sans CJK SC"

    def _font(self, size: int, weight: str = None):
        """返回Tkinter字体元组，集中控制字体和字号。"""
        if weight:
            return (self.font_family, size, weight)
        return (self.font_family, size)

    def _setup_styles(self):
        """设置自定义样式"""
        style = ttk.Style()
        style.theme_use('clam')

        # 配置主题色
        style.configure("TFrame", background=self.bg_color)
        style.configure("TLabel", background=self.bg_color, foreground=self.text_color, font=self._font(10))
        style.configure("TButton", background=self.accent_color, foreground="white", font=self._font(10))
        style.map(
            "TButton",
            background=[("active", self.highlight_color), ("disabled", "#cccccc")],
            foreground=[("active", self.text_color), ("disabled", "#666666")]
        )

        # 标题样式
        style.configure("Title.TLabel", font=self._font(16, "bold"), foreground=self.accent_color)

        # 子标题样式
        style.configure("Subtitle.TLabel", font=self._font(12), foreground=self.text_color)

        # 标签框样式
        style.configure("TLabelframe", background=self.bg_color)
        style.configure(
            "TLabelframe.Label",
            background=self.bg_color,
            foreground=self.accent_color,
            font=self._font(11, "bold")
        )

        # 笔记本样式
        style.configure("TNotebook", background=self.bg_color, tabposition='n')
        style.configure(
            "TNotebook.Tab",
            background="#e0e0e0",
            foreground=self.text_color,
            padding=[10, 5],
            font=self._font(10)
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.accent_color)],
            foreground=[("selected", "white")]
        )

        # 输入框样式
        style.configure("TEntry", fieldbackground="white", foreground=self.text_color, font=self._font(10))

        # 按钮样式
        style.configure("Primary.TButton", font=self._font(10, "bold"))
        style.configure("Secondary.TButton", background="#f0f0f0", foreground=self.text_color)

        # 开始按钮
        style.configure("Start.TButton", background="#4CAF50", foreground="white", font=self._font(10, "bold"))
        style.map("Start.TButton", background=[("active", "#66BB6A"), ("disabled", "#A5D6A7")])

        # 停止按钮
        style.configure("Stop.TButton", background="#F44336", foreground="white", font=self._font(10, "bold"))
        style.map("Stop.TButton", background=[("active", "#EF5350"), ("disabled", "#FFCDD2")])

    def _create_ui(self):
        # 创建带标签的笔记本
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 配置标签页
        config_frame = ttk.Frame(notebook)
        notebook.add(config_frame, text="配置设置")
        
        # 监控标签页
        monitor_frame = ttk.Frame(notebook)
        notebook.add(monitor_frame, text="价格监控")
        
        # 创建配置UI
        self._create_config_ui(config_frame)
        
        # 创建监控UI
        self._create_monitor_ui(monitor_frame)
    
    def _create_config_ui(self, parent):
        ttk.Label(parent, text="航班含税日历价格监控", style="Title.TLabel").pack(
            anchor=tk.W, padx=30, pady=(18, 10))
        form = ttk.Frame(parent)
        form.pack(fill=tk.X, padx=30, pady=5)
        form.columnconfigure(1, weight=1)

        def label(text, row):
            ttk.Label(form, text=text).grid(row=row, column=0, sticky=tk.W, padx=(0, 15), pady=4)

        def entry(text, variable, row, **kwargs):
            label(text, row)
            widget = ttk.Entry(form, textvariable=variable, **kwargs)
            widget.grid(row=row, column=1, sticky=tk.EW, pady=4)
            return widget

        entry("出发日期（多个日期用逗号分隔）:", self.dates_var, 0)
        entry("出发城市代码:", self.place_from_var, 1)
        entry("到达城市代码:", self.place_to_var, 2)
        label("航线范围 / 航程类型:", 3)
        modes = ttk.Frame(form)
        modes.grid(row=3, column=1, sticky=tk.W, pady=4)
        ttk.Combobox(modes, textvariable=self.search_type_var, values=["国内", "国际"],
                     width=10, state="readonly").pack(side=tk.LEFT, padx=(0, 12))
        ttk.Combobox(modes, textvariable=self.flight_way_var, values=["Oneway", "Roundtrip"],
                     width=12, state="readonly").pack(side=tk.LEFT)
        self.return_date_entry = entry("固定返程日期（往返必填）:", self.return_date_var, 4)
        label("舱等:", 5)
        ttk.Combobox(form, textvariable=self.grade_var, values=list(CABINS.values()),
                     state="readonly").grid(row=5, column=1, sticky=tk.EW, pady=4)
        label("乘客人数（国内固定 1 成人）:", 6)
        passengers = ttk.Frame(form)
        passengers.grid(row=6, column=1, sticky=tk.W, pady=4)
        self.passenger_entries = []
        for text, variable in (("成人", self.adults_var), ("儿童", self.children_var),
                               ("婴儿", self.babies_var)):
            ttk.Label(passengers, text=text).pack(side=tk.LEFT, padx=(0, 4))
            widget = ttk.Entry(passengers, textvariable=variable, width=5)
            widget.pack(side=tk.LEFT, padx=(0, 12))
            self.passenger_entries.append(widget)
        entry("检查间隔（秒）:", self.sleep_time_var, 7)
        entry("含税价格变动阈值（元）:", self.price_step_var, 8)
        entry("PushPlus 推送令牌:", self.sckey_var, 9, show="*")
        for text in (
                "日期支持 YYYYMMDD 或 YYYY-MM-DD；单程 Oneway，往返 Roundtrip。",
                "每个出发日期与同一个固定返程日期配对。金额为 CNY 含税日历报价，实际购买价以订单页为准。",
                "国际航线与往返模式已接入，覆盖情况以查询结果为准。缺失报价不会触发价格变化提醒。",
                "PushPlus 令牌留空仅记录价格；输入遮蔽不代表配置文件已加密。"):
            ttk.Label(parent, text=text, foreground="#666666", font=self._font(9),
                      wraplength=840).pack(anchor=tk.W, padx=30, pady=2)
        ttk.Label(parent, text=f"配置保存位置: {self.config_dir}", font=self._font(9),
                  wraplength=840).pack(anchor=tk.W, padx=30, pady=8)
        buttons = ttk.Frame(parent)
        buttons.pack(fill=tk.X, padx=30, pady=12)
        ttk.Button(buttons, text="保存配置", command=self._save_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons, text="加载配置", command=self._load_config).pack(side=tk.LEFT, padx=5)
        self.flight_way_var.trace_add("write", self._update_trip_inputs)
        self.search_type_var.trace_add("write", self._update_trip_inputs)
        self._update_trip_inputs()

    def _update_trip_inputs(self, *_):
        self.return_date_entry.config(
            state="normal" if self.flight_way_var.get() == "Roundtrip" else "disabled")
        domestic = self.search_type_var.get() == "国内"
        if domestic:
            self.adults_var.set("1")
            self.children_var.set("0")
            self.babies_var.set("0")
        for widget in self.passenger_entries:
            widget.config(state="disabled" if domestic else "normal")

    def _create_monitor_ui(self, parent):
        # 控制按钮框架
        controls_frame = ttk.Frame(parent)
        controls_frame.pack(fill=tk.X, padx=20, pady=20)

        # 标题
        ttk.Label(controls_frame, text="航班价格监控", style="Title.TLabel").pack(side=tk.LEFT)

        # 按钮放在右边
        buttons_frame = ttk.Frame(controls_frame)
        buttons_frame.pack(side=tk.RIGHT)

        self.start_button = ttk.Button(buttons_frame, text="开始监控", style="Start.TButton", command=self._start_monitoring, width=12)
        self.start_button.pack(side=tk.LEFT, padx=5)

        self.stop_button = ttk.Button(buttons_frame, text="停止监控", style="Stop.TButton", command=self._stop_monitoring, width=12, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)

        # 状态框架
        status_frame = ttk.LabelFrame(parent, text="当前状态")
        status_frame.pack(fill=tk.X, padx=20, pady=10)

        self.status_label = ttk.Label(
            status_frame,
            text=self._status_text("准备就绪，等待开始监控"),
            font=self._font(10),
            justify=tk.LEFT,
            wraplength=820
        )
        self.status_label.pack(fill=tk.X, padx=15, pady=10, anchor=tk.W)

        # 价格框架
        prices_frame = ttk.LabelFrame(parent, text="当前价格")
        prices_frame.pack(fill=tk.X, padx=20, pady=10)

        self.prices_text = scrolledtext.ScrolledText(prices_frame, height=6, wrap=tk.WORD, font=self._font(10))
        self.prices_text.pack(fill=tk.X, padx=10, pady=10)
        self.prices_text.config(state=tk.DISABLED)
        self._set_prices_text(self._empty_prices_text())

        # 日志框架
        log_frame = ttk.LabelFrame(parent, text="活动日志")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)

        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, font=self._font(10))
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.log_text.config(state=tk.DISABLED)

        # 添加欢迎信息
        self._log("欢迎使用航班价格监控系统！")
        self._log("请在配置页面设置监控参数，然后点击开始监控按钮")

    def _build_config_from_inputs(self, *, allow_expired=False) -> dict:
        """读取GUI输入并构建已验证、已规范化的配置。"""
        regions = {"国内": 1, "国际": 2}
        cabins = {name: code for code, name in CABINS.items()}
        if self.search_type_var.get() not in regions or self.grade_var.get() not in cabins:
            raise ValueError("请选择有效的航线范围和舱等")
        return parse_monitor_config(
            self.dates_var.get(),
            self.place_from_var.get(),
            self.place_to_var.get(),
            self.flight_way_var.get(),
            self.sleep_time_var.get(),
            self.price_step_var.get(),
            self.sckey_var.get(),
            search_type=regions[self.search_type_var.get()],
            grade=cabins[self.grade_var.get()],
            return_date_text=self.return_date_var.get(),
            adults_text=self.adults_var.get(), children_text=self.children_var.get(),
            babies_text=self.babies_var.get(), allow_expired=allow_expired
        )

    def _format_dates(self, dates) -> str:
        return ", ".join(dates) if dates else "未配置"

    def _format_route(self, config: dict) -> str:
        place_from = config.get("placeFrom", "")
        place_to = config.get("placeTo", "")
        from_display = get_readable_location(place_from)
        to_display = get_readable_location(place_to)
        return f"{from_display}({place_from}) → {to_display}({place_to})"

    def _notification_state(self, config: dict) -> str:
        if config.get("SCKEY"):
            return "已启用 PushPlus 通知"
        return "未填写 PushPlus 令牌，仅监控价格，不发送通知"

    def _status_text(self, phase: str, detail: str = "", config: dict = None) -> str:
        """生成监控状态摘要，避免用户只能从日志判断当前状态。"""
        active_config = config or self.config
        lines = [f"状态: {phase}"]
        if active_config:
            lines.append(f"路线: {self._format_route(active_config)}")
            lines.append(f"监控日期: {self._format_dates(active_config.get('dateToGo', []))}")
            lines.append(self._query_description(active_config))
            lines.append(f"通知: {self._notification_state(active_config)}")
        else:
            lines.append("路线/日期: 未开始监控")
        if self.last_check_time:
            lines.append(f"上次检查: {self.last_check_time}")
        if detail:
            lines.append(detail)
        return "\n".join(lines)

    def _empty_prices_text(self) -> str:
        return "尚未获取价格。\n请先在“配置设置”页填写参数，然后点击“开始监控”。"

    def _price_header_text(self, config: dict) -> str:
        return "\n".join([
            f"路线: {self._format_route(config)}",
            f"监控日期: {self._format_dates(config.get('dateToGo', []))}",
            self._query_description(config),
            f"通知: {self._notification_state(config)}"
        ])

    def _query_description(self, config):
        region = "国内" if config.get("searchType", 1) == 1 else "国际"
        text = f"{region} · {CABINS.get(config.get('grade', 1), '经济舱')} · CNY 含税日历价"
        if config.get("flightWay") == "Roundtrip":
            text += f" · 返程 {display_date(config['returnDate'])}"
        return text

    def _fill_config_inputs(self, config):
        # 完整校验后才改变界面；过期日期保留给用户修改。
        config = normalize_config(config, allow_expired=True)
        self.dates_var.set(",".join(config.get("dateToGo", [])))
        self.place_from_var.set(config.get("placeFrom", ""))
        self.place_to_var.set(config.get("placeTo", ""))
        self.flight_way_var.set(config.get("flightWay", "Oneway"))
        self.search_type_var.set("国内" if config.get("searchType", 1) == 1 else "国际")
        self.grade_var.set(CABINS[config["grade"]])
        self.return_date_var.set(config.get("returnDate", ""))
        self.sleep_time_var.set(str(config.get("sleepTime", 600)))
        self.price_step_var.set(str(config.get("priceStep", 50)))
        self.sckey_var.set(config.get("SCKEY", ""))
        counts = {item["passengerType"]: item["passengerCount"] for item in
                  config.get("passengerList", [{"passengerType": "Adult", "passengerCount": 1}])}
        self.adults_var.set(str(counts.get("Adult", 1)))
        self.children_var.set(str(counts.get("Child", 0)))
        self.babies_var.set(str(counts.get("Baby", 0)))
        self._update_trip_inputs()

    def _save_config(self):
        """保存配置到文件"""
        try:
            config = self._build_config_from_inputs(allow_expired=True)
            config_path = os.path.join(self.config_dir, "config.json")
            save_config(config_path, config)
            self._fill_config_inputs(config)

            self._log(f"配置保存成功: {config_path}")
            if not config["SCKEY"]:
                self._log("未填写 PushPlus 推送令牌；后续监控只记录价格，不发送通知")
            messagebox.showinfo("成功", "配置保存成功")
        except ValueError as e:
            self._log(f"配置验证失败: {str(e)}")
            messagebox.showerror("错误", str(e))
        except Exception as e:
            self._log(f"保存配置出错: {str(e)}")
            messagebox.showerror("错误", f"保存配置失败: {str(e)}")

    def _load_config(self):
        try:
            config_path = os.path.join(self.config_dir, 'config.json')
            
            if not os.path.exists(config_path):
                self._log("未找到配置文件")
                return
            
            config = load_config(config_path, allow_expired=True)
            
            self._fill_config_inputs(config)

            self._log(f"配置加载成功: {config_path}")
        except Exception as e:
            self._log(f"加载配置出错: {str(e)}")
            messagebox.showerror("错误", f"加载配置失败: {str(e)}")
    
    def _start_monitoring(self):
        if self.closing or self.running or (self.monitor_thread and self.monitor_thread.is_alive()):
            return
        try:
            config = self._build_config_from_inputs()
            service = MonitorService(config)
            self._fill_config_inputs(config)
            self.config, self.service = config, service
            self.stop_event.clear()
            self.last_check_time = None
            self._finish_message = "监控已停止"
            self.running = True
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            self._update_status(self._status_text("价格监控进行中，准备检查"))
            self._update_prices_display(
                f"正在准备获取价格...\n{self._price_header_text(config)}")
            # 后台只发送普通数据，不读取或调用任何 Tk 对象。
            self._generation += 1
            generation, events = self._generation, self._events
            self.monitor_thread = threading.Thread(
                target=run_monitor,
                args=(service, self.stop_event,
                      lambda event: events.put((generation, event))),
                name="flight-monitor", daemon=False)
            self.monitor_thread.start()
            self._log(f"价格监控已启动 - 路线: {self._format_route(config)}")
            if not config["SCKEY"]:
                self._log("未填写 PushPlus 推送令牌；本次监控不会发送微信通知")
        except Exception as exc:
            self.running = False
            self.stop_event.set()
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            logger.exception("启动监控失败")
            self._log(f"启动监控失败: {exc}", persist=False)
            self._update_status(self._status_text("启动监控失败", str(exc)))
            messagebox.showerror("错误", f"启动监控失败: {exc}")

    def _stop_monitoring(self):
        if not self.running:
            return
        self.running = False
        self.stop_event.set()
        self._finish_message = "监控已停止"
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.DISABLED)
        self._update_status(self._status_text("正在停止，等待当前请求结束"))
        self._finish_stop()

    def _finish_stop(self):
        if self.monitor_thread and self.monitor_thread.is_alive():
            if self._finish_after_id is None:
                self._finish_after_id = self.root.after(100, self._poll_worker_exit)
            return
        if self._finish_after_id is not None:
            self.root.after_cancel(self._finish_after_id)
            self._finish_after_id = None
        if self.closing:
            if self._poll_after_id is not None:
                self.root.after_cancel(self._poll_after_id)
                self._poll_after_id = None
            self.root.destroy()
            return
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self._update_status(self._status_text(self._finish_message))

    def _poll_worker_exit(self):
        self._finish_after_id = None
        self._finish_stop()

    def _on_close(self):
        if self.closing:
            return
        self.closing = True
        self.running = False
        self.stop_event.set()
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.DISABLED)
        self._update_status(self._status_text("正在关闭，等待当前请求结束"))
        # 关闭阶段不再消费界面更新事件，只等待后台退出。
        if self._poll_after_id is not None:
            self.root.after_cancel(self._poll_after_id)
            self._poll_after_id = None
        self._finish_stop()

    def _poll_events(self):
        self._poll_after_id = None
        if self.closing:
            return
        try:
            # 限制每次处理量，避免大量日志占用整个事件循环。
            for _ in range(100):
                generation, event = self._events.get_nowait()
                if generation == self._generation:
                    self._handle_monitor_event(event)
        except Empty:
            pass
        self._poll_after_id = self.root.after(100, self._poll_events)

    def _handle_monitor_event(self, event):
        if event.kind in ("log", "error"):
            self._log(str(event.data), persist=False)
        elif event.kind == "result":
            result = event.data
            self.config = dict(self.config, dateToGo=result.active_dates)
            if result.calendar is None:
                self._update_prices_display("全部监控日期已过期。")
                return
            self.last_check_time = result.calendar.observed_at
            lines = [self._price_header_text(self.config), ""]
            for day in result.active_dates:
                price = result.calendar.prices.get(day)
                text = (f"含税日历价 CNY {price:g}" if price is not None
                        else "暂无有效含税报价（不代表无航班）")
                lines.append(f"{display_date(day)}: {text}")
            self._update_prices_display("\n".join(lines))
        elif event.kind == "phase" and self.running:
            self._update_status(self._status_text(str(event.data)))
        elif event.kind == "waiting" and self.running:
            remaining, retrying = event.data
            action = "重试" if retrying else "下次检查"
            self._update_status(self._status_text(
                "请求失败，等待重试" if retrying else "等待下次检查",
                f"{action}将在 {remaining} 秒后进行"))
        elif event.kind == "finished":
            self.running = False
            self.stop_event.set()
            self._finish_message = str(event.data)
            self._log(self._finish_message)
            self._finish_stop()

    def _log(self, message, *, persist=True):
        """仅由主线程调用；后台日志通过 MonitorEvent 传入。"""
        if persist:
            logger.info(message)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._update_log(f"[{timestamp}] {message}\n")

    def _update_log(self, message):
        """在主线程更新日志文本框。"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def _update_status(self, status):
        """在主线程更新状态标签。"""
        self.status_label.config(text=status)
    
    def _update_prices_display(self, text):
        """在主线程更新价格文本框。"""
        self._set_prices_text(text)
    
    def _set_prices_text(self, text):
        """设置价格文本框内容（从主线程调用）"""
        self.prices_text.config(state=tk.NORMAL)
        self.prices_text.delete(1.0, tk.END)
        self.prices_text.insert(tk.END, text)
        self.prices_text.config(state=tk.DISABLED)


def resource_path(relative_path):
    """获取资源的绝对路径，适用于开发环境和PyInstaller打包环境"""
    try:
        # PyInstaller创建临时文件夹并将路径存储在_MEIPASS中
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    
    return os.path.join(base_path, relative_path)


if __name__ == "__main__":
    root = tk.Tk()
    
    # 设置图标
    try:
        icon_path = resource_path("icon.ico")
        if os.path.exists(icon_path):
            root.iconbitmap(icon_path)
    except (FileNotFoundError, OSError, tk.TclError):
        pass

    try:
        app = FlightAlertApp(root)
    except OSError as exc:
        messagebox.showerror("启动失败", f"无法初始化配置或日志目录: {exc}")
        root.destroy()
        sys.exit(1)
    root.mainloop()
