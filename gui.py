import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import serial
import serial.tools.list_ports
import threading
import pyautogui
import pyperclip
import time
import re
import platform 
from pynput import keyboard

class BalanceApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"梅特勒天平助手 by LLX ({platform.system()}版)")
        self.root.geometry("500x450")
        self.root.resizable(False, False)
        
        # --- 核心变量 ---
        self.ser = None
        self.is_running = False
        
        # 配置项变量
        self.output_mode_var = tk.StringVar(value="type")
        self.suffix_var = tk.StringVar(value="enter")
        self.hotkey_str_var = tk.StringVar(value="F9")

        # --- 1. 基础快捷键映射 ---
        self.hotkey_map = {
            "F1": keyboard.Key.f1, "F2": keyboard.Key.f2, "F3": keyboard.Key.f3,
            "F4": keyboard.Key.f4, "F5": keyboard.Key.f5, "F6": keyboard.Key.f6,
            "F7": keyboard.Key.f7, "F8": keyboard.Key.f8, "F9": keyboard.Key.f9,
            "F10": keyboard.Key.f10, "F11": keyboard.Key.f11, "F12": keyboard.Key.f12,
            "Home": keyboard.Key.home, "End": keyboard.Key.end
        }

        # --- 2. 跨平台按键适配 (关键修改) ---
        # 如果不是 macOS，尝试添加 Insert 键
        if platform.system() != "Darwin":
            try:
                self.hotkey_map["Insert"] = keyboard.Key.insert
            except AttributeError:
                pass # 防御性编程：万一 pynput 版本不支持

        # 当前生效的快捷键对象 (默认 F9)
        self.current_target_key = self.hotkey_map.get("F9", keyboard.Key.f9)

        # --- 构建界面 ---
        self.setup_ui()

        # --- 初始化 ---
        self.refresh_ports()
        
        # 启动全局监听器 (永不重启，稳定防崩)
        self.start_global_listener()

    def setup_ui(self):
        """构建界面布局"""
        # 1. 连接设置
        frame_conn = ttk.LabelFrame(self.root, text="连接设置", padding=10)
        frame_conn.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_conn, text="端口:").grid(row=0, column=0, padx=5, sticky="e")
        self.combo_ports = ttk.Combobox(frame_conn, width=22, state="readonly")
        self.combo_ports.grid(row=0, column=1, padx=5, sticky="w")
        ttk.Button(frame_conn, text="刷新", command=self.refresh_ports, width=6).grid(row=0, column=2, padx=5)

        ttk.Label(frame_conn, text="波特率:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.combo_baud = ttk.Combobox(frame_conn, width=10, values=["9600", "1200", "2400", "4800", "19200"], state="readonly")
        self.combo_baud.current(0)
        self.combo_baud.grid(row=1, column=1, padx=5, sticky="w")
        
        self.btn_connect = ttk.Button(frame_conn, text="打开连接", command=self.toggle_connection, width=12)
        self.btn_connect.grid(row=1, column=2, padx=5, sticky="ew")

        # 2. 功能设置
        frame_settings = ttk.LabelFrame(self.root, text="功能设置", padding=10)
        frame_settings.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame_settings, text="输出模式:").grid(row=0, column=0, padx=5, sticky="e")
        rb_type = ttk.Radiobutton(frame_settings, text="模拟键入", variable=self.output_mode_var, value="type", command=self.toggle_suffix_state)
        rb_type.grid(row=0, column=1, padx=5, sticky="w")
        rb_clip = ttk.Radiobutton(frame_settings, text="复制到剪切板", variable=self.output_mode_var, value="clipboard", command=self.toggle_suffix_state)
        rb_clip.grid(row=0, column=2, padx=5, sticky="w")

        ttk.Label(frame_settings, text="键入后缀:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.combo_suffix = ttk.Combobox(frame_settings, width=15, textvariable=self.suffix_var, values=["回车 (Enter)", "Tab", "无 (None)"], state="readonly")
        self.combo_suffix.grid(row=1, column=1, padx=5, sticky="w", columnspan=2)
        self.suffix_map = {"回车 (Enter)": "enter", "Tab": "tab", "无 (None)": "none"}
        self.combo_suffix.current(0)

        # 快捷键设置
        ttk.Label(frame_settings, text="触发快捷键:").grid(row=2, column=0, padx=5, sticky="e")
        self.combo_hotkey = ttk.Combobox(frame_settings, width=15, textvariable=self.hotkey_str_var, values=list(self.hotkey_map.keys()), state="readonly")
        self.combo_hotkey.grid(row=2, column=1, padx=5, sticky="w", columnspan=2)
        self.combo_hotkey.bind("<<ComboboxSelected>>", self.on_hotkey_changed)

        # 3. 日志区
        frame_bottom = ttk.Frame(self.root, padding=5)
        frame_bottom.pack(fill="both", expand=True, padx=10)

        self.status_label = ttk.Label(frame_bottom, text=f"就绪。请连接串口，然后按 F9 键录入。", foreground="gray")
        self.status_label.pack(anchor="w", pady=(5, 0))

        self.log_area = scrolledtext.ScrolledText(frame_bottom, height=8, state='disabled', font=("Consolas", 11))
        self.log_area.pack(fill="both", expand=True, pady=5)

    # --- 逻辑处理 ---
    def toggle_suffix_state(self):
        if self.output_mode_var.get() == "type":
            self.combo_suffix.config(state="readonly")
        else:
            self.combo_suffix.config(state="disabled")

    def log(self, msg):
        def _log():
            self.log_area.config(state='normal')
            self.log_area.insert(tk.END, msg + "\n")
            self.log_area.see(tk.END)
            self.log_area.config(state='disabled')
        self.root.after(0, _log)

    def update_status(self, msg, color="black"):
        self.root.after(0, lambda: self.status_label.config(text=msg, foreground=color))

    def refresh_ports(self):
        ports = serial.tools.list_ports.comports()
        port_list = [p.device for p in ports]
        self.combo_ports['values'] = port_list
        if port_list:
            self.combo_ports.current(0)
            self.log(f"已找到 {len(port_list)} 个设备")
        else:
            self.combo_ports.set("")
            self.log("未找到可用端口")

    def toggle_connection(self):
        if not self.is_running:
            port = self.combo_ports.get()
            baud = self.combo_baud.get()
            if not port:
                 messagebox.showwarning("提示", "请先选择一个端口")
                 return
            try:
                self.ser = serial.Serial(port, int(baud), timeout=3)
                self.is_running = True
                self.btn_connect.config(text="断开连接")
                self.log(f"成功连接到 {port}")
                self.update_status(f"已连接。按下 {self.hotkey_str_var.get()} 键以录入。", "green")
            except Exception as e:
                self.log(f"连接失败: {e}")
                messagebox.showerror("连接错误", f"无法打开端口\n{e}\n\n请检查驱动是否安装。")
        else:
            self.is_running = False
            if self.ser and self.ser.is_open:
                self.ser.close()
            self.btn_connect.config(text="打开连接")
            self.log("连接已断开")
            self.update_status("已断开。", "gray")

    def start_global_listener(self):
        """启动唯一的全局键盘监听器"""
        def on_release(key):
            if key == self.current_target_key:
                if self.is_running:
                    threading.Thread(target=self.read_weight_task, daemon=True).start()
        
        self.listener = keyboard.Listener(on_release=on_release)
        self.listener.daemon = True 
        self.listener.start()
        self.log(f"键盘监听服务已启动 ({platform.system()}模式)")

    def on_hotkey_changed(self, event=None):
        new_str = self.hotkey_str_var.get()
        new_key = self.hotkey_map.get(new_str)
        if new_key:
            self.current_target_key = new_key
            self.log(f"快捷键已切换为: {new_str}")
            if self.is_running:
                self.update_status(f"已连接。按下 {new_str} 键以录入。", "green")

    def read_weight_task(self):
        try:
            self.log(">>> 发送指令 'S'...")
            if self.ser and self.ser.is_open:
                self.ser.reset_input_buffer()
                self.ser.write(b'S\r\n')
                
                line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                if not line:
                    self.log("超时: 天平未响应")
                    return

                self.log(f"收到: {line}")
                match = re.search(r"(-?\d+\.\d+)", line)
                
                if match:
                    weight = match.group(1)
                    mode = self.output_mode_var.get()
                    
                    if mode == "type":
                        self.log(f"键入: {weight}")
                        time.sleep(0.1)
                        pyautogui.typewrite(weight)
                        
                        suffix = self.suffix_map.get(self.combo_suffix.get(), "none")
                        if suffix == "enter":
                            pyautogui.press('enter')
                        elif suffix == "tab":
                            pyautogui.press('tab')
                            
                    elif mode == "clipboard":
                        pyperclip.copy(weight)
                        self.log(f"已复制: {weight}")
                else:
                    self.log("错误: 数据中无数字")
            else:
                self.log("串口意外断开")
                self.root.after(0, self.toggle_connection)

        except Exception as e:
            self.log(f"异常: {e}")

    def on_close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.root.destroy()

if __name__ == "__main__":
    # --- 3. Windows 高分屏模糊修复 (关键修改) ---
    if platform.system() == "Windows":
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass # 老版本 Windows 可能不支持，忽略

    root = tk.Tk()
    app = BalanceApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()