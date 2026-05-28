import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import numpy as np
import scipy.io.wavfile as wav
from scipy import signal
from scipy.ndimage import uniform_filter1d
import os
import threading
import csv
import wave
import math
import sys
import gc
import ctypes

# 高DPI対応
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

# ==========================================
#  機能1: 音イベントカウンター (CF表示なし版)
# ==========================================
class EventCounterTab:
    def __init__(self, parent):
        self.frame = tk.Frame(parent)
        self.frame.pack(fill="both", expand=True)

        self.is_running = False
        self.cache = {} 
        self.loading_file = None 
        
        # --- 設定エリア ---
        frame_top = tk.LabelFrame(self.frame, text="設定・操作", padx=5, pady=5)
        frame_top.pack(fill="x", padx=10, pady=5)

        # 1行目: フォルダ選択
        frame_folder = tk.Frame(frame_top)
        frame_folder.pack(fill="x", pady=2)
        tk.Label(frame_folder, text="対象フォルダ:").pack(side="left")
        self.folder_path_var = tk.StringVar()
        tk.Entry(frame_folder, textvariable=self.folder_path_var, width=50).pack(side="left", padx=5)
        tk.Button(frame_folder, text="フォルダ選択...", command=self.select_folder).pack(side="left")

        # 2行目: 日時入力
        frame_date = tk.Frame(frame_top)
        frame_date.pack(fill="x", pady=5)
        
        tk.Label(frame_date, text="日時 (ファイル名用):").pack(side="left")
        self.entry_month = tk.Entry(frame_date, width=3)
        self.entry_month.pack(side="left", padx=(5, 0))
        tk.Label(frame_date, text="月").pack(side="left")
        self.entry_day = tk.Entry(frame_date, width=3)
        self.entry_day.pack(side="left", padx=(5, 0))
        tk.Label(frame_date, text="日").pack(side="left")
        
        tk.Label(frame_date, text="   時間:").pack(side="left")
        self.entry_start = tk.Entry(frame_date, width=3)
        self.entry_start.pack(side="left", padx=(5, 0))
        tk.Label(frame_date, text="時 〜").pack(side="left")
        self.entry_end = tk.Entry(frame_date, width=3)
        self.entry_end.pack(side="left", padx=(5, 0))
        tk.Label(frame_date, text="時").pack(side="left")

        # 3行目: 操作ボタン
        frame_params = tk.Frame(frame_top)
        frame_params.pack(fill="x", pady=5)

        # --- 内部設定値 ---
        self.default_k = 0.4        # 感度係数
        self.default_dist = 0.1     # 最小間隔
        self.default_crest = 3.5    # ノイズ除去比

        # ボタン群
        self.btn_run = tk.Button(frame_params, text="一括解析開始", command=self.start_batch_analysis, bg="#dddddd", width=12, height=2)
        self.btn_run.pack(side="left", padx=15)

        self.btn_stop = tk.Button(frame_params, text="中止", command=self.stop_batch_analysis, bg="#ffcccc", width=8, height=2, state="disabled")
        self.btn_stop.pack(side="left", padx=5)

        self.btn_save = tk.Button(frame_params, text="CSV保存", command=self.save_to_csv, bg="#ccffcc", width=8, height=2)
        self.btn_save.pack(side="left", padx=5)

        # --- メインエリア ---
        paned = tk.PanedWindow(self.frame, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=10, pady=5)

        # 左側：リスト
        frame_left = tk.Frame(paned)
        paned.add(frame_left, width=400)
        
        # 合計表示ラベル
        self.result_label = tk.Label(frame_left, text="解析結果一覧 (合計: 0 回)", font=("MS Gothic", 9, "bold"))
        self.result_label.pack(anchor="w", pady=(0, 2))
        
        self.tree = ttk.Treeview(frame_left, columns=("File", "Count", "Status"), show="headings")
        self.tree.heading("File", text="ファイル名")
        self.tree.heading("Count", text="検知回数")
        self.tree.heading("Status", text="状態")
        
        self.tree.column("File", width=250)
        self.tree.column("Count", width=70, anchor="center")
        self.tree.column("Status", width=120, anchor="center")
        
        scrollbar = ttk.Scrollbar(frame_left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self.on_file_select)

        # 右側：グラフ
        frame_right = tk.Frame(paned, bg="white", bd=2, relief="sunken")
        paned.add(frame_right)

        self.canvas_width = 100
        self.canvas_height = 100
        self.canvas = tk.Canvas(frame_right, bg="white")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self.on_canvas_resize)

        self.progress = ttk.Progressbar(self.frame, mode="determinate")
        self.progress.pack(fill="x", padx=10, pady=5)
        self.status_label = tk.Label(self.frame, text="待機中")
        self.status_label.pack(anchor="w", padx=10)

        self.current_graph_data = None

    def on_canvas_resize(self, event):
        self.canvas_width = event.width
        self.canvas_height = event.height
        if self.current_graph_data:
            self.draw_graph_fast(*self.current_graph_data)

    def update_total_label(self):
        """合計回数を計算して表示更新"""
        total = 0
        for item_id in self.tree.get_children():
            val = self.tree.set(item_id, "Count")
            if val.isdigit():
                total += int(val)
        self.result_label.config(text=f"解析結果一覧 (合計: {total} 回)")

    def select_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.folder_path_var.set(folder)
            self.cache = {} 
            for item in self.tree.get_children():
                self.tree.delete(item)
            
            files = [f for f in os.listdir(folder) if f.lower().endswith(".wav")]
            files.sort()
            for f in files:
                self.tree.insert("", "end", values=(f, "-", "待機"))
            self.status_label.config(text=f"{len(files)} 個のファイルが見つかりました")
            self.update_total_label()

    def start_batch_analysis(self):
        # フォルダチェック
        folder = self.folder_path_var.get()
        if not folder:
            messagebox.showwarning("確認", "対象フォルダを選択してください")
            return

        self.cache = {}
        self.is_running = True
        self.btn_run.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.btn_save.config(state="disabled")
        threading.Thread(target=self.run_batch_thread, daemon=True).start()

    def stop_batch_analysis(self):
        self.is_running = False
        self.status_label.config(text="中止しています...")

    def run_batch_thread(self):
        folder = self.folder_path_var.get()
        if not folder: 
            self.frame.after(0, self._finish_analysis_ui)
            return

        k_val = self.default_k
        min_dist_sec = self.default_dist
        crest_th = self.default_crest

        items = self.tree.get_children()
        total = len(items)
        
        self.frame.after(0, lambda: self.progress.configure(maximum=total))

        for idx, item_id in enumerate(items):
            if not self.is_running: break

            file_name = self.tree.item(item_id, "values")[0]
            full_path = os.path.join(folder, file_name)
            
            if idx % 5 == 0:
                self.frame.after(0, lambda t=f"解析中 ({idx+1}/{total}): {file_name}": self.status_label.config(text=t))
            
            try:
                if idx % 5 == 0: gc.collect()

                peaks, envelope, threshold, sr, measured_cf, is_fallback = self.analyze_single_file(full_path, k_val, min_dist_sec, crest_th)
                self.cache[full_path] = (peaks, envelope, threshold, sr, measured_cf)
                
                count = len(peaks)
                status_text = "完了(救)" if is_fallback else "完了"
                
                # 結果更新（メインスレッドに依頼）
                self.frame.after(0, lambda i=item_id, c=count, s=status_text: self._update_tree_item(i, c, s))

            except ValueError as e:
                msg = "長すぎ" if str(e) == "Over30Min" else "Err"
                self.frame.after(0, lambda i=item_id, s=msg: self._update_tree_item(i, "-", s))
            except RuntimeError as e:
                msg = "破損" if str(e) == "ReadError" else ("空" if str(e) == "Empty Data" else "Err")
                self.frame.after(0, lambda i=item_id, s=msg: self._update_tree_item(i, "-", s))
            except Exception as e:
                self.frame.after(0, lambda i=item_id: self._update_tree_item(i, "Err", "Err"))
                print(f"Batch Error: {e}")

            self.frame.after(0, lambda v=idx+1: self.progress.configure(value=v))

        self.frame.after(0, self._finish_analysis_ui)

    def _update_tree_item(self, item_id, count, status):
        self.tree.set(item_id, "Count", str(count))
        self.tree.set(item_id, "Status", status)
        self.update_total_label()

    def _finish_analysis_ui(self):
        if self.is_running:
            self.status_label.config(text="すべての解析が完了しました")
            messagebox.showinfo("完了", "一括解析が終了しました")
        else:
            self.status_label.config(text="解析を中止しました")
            messagebox.showinfo("中止", "解析を中断しました")
        
        self.reset_buttons()

    def reset_buttons(self):
        self.is_running = False
        self.btn_run.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.btn_save.config(state="normal")

    def analyze_single_file(self, filepath, k, min_dist_sec, crest_th):
        is_fallback = False
        try:
            sr, data = wav.read(filepath, mmap=True)
            if len(data) < sr * 0.1: raise ValueError("Too short")
        except Exception:
            is_fallback = True
            try:
                with wave.open(filepath, 'rb') as f:
                    sr = f.getframerate()
                    n_frames = f.getnframes()
                    
                    if n_frames / sr > 1800: raise ValueError("Over30Min")

                    width = f.getsampwidth()
                    channels = f.getnchannels()
                    buffer = f.readframes(n_frames)
                    
                    if width == 2:
                        if len(buffer) % 2 != 0: buffer = buffer[:-1]
                        data = np.frombuffer(buffer, dtype=np.int16)
                    elif width == 4:
                        if len(buffer) % 4 != 0: buffer = buffer[:-(len(buffer)%4)]
                        data = np.frombuffer(buffer, dtype=np.int32)
                    elif width == 1:
                        data = np.frombuffer(buffer, dtype=np.uint8)
                    elif width == 3:
                        rem = len(buffer) % 3
                        if rem != 0: buffer = buffer[:-rem]
                        temp_data = np.frombuffer(buffer, dtype=np.int8)
                        data = temp_data[2::3].astype(np.int16) * 256
                        del temp_data
                    else:
                        raise ValueError(f"Unsupported width: {width}")
                    del buffer
                    
                    if channels > 1:
                        rem = len(data) % channels
                        if rem != 0: data = data[:-rem]
                        if len(data) > 0:
                            data = data.reshape(-1, channels)
                            data = data.mean(axis=1, dtype=np.float32)
            except ValueError as ve:
                raise ve
            except Exception:
                try:
                    file_size = os.path.getsize(filepath)
                    if file_size > 500 * 1024 * 1024: raise ValueError("Over30Min")

                    with open(filepath, 'rb') as f:
                        raw_bytes = f.read()
                    header_size = 44
                    if len(raw_bytes) > header_size:
                        content = raw_bytes[header_size:]
                        del raw_bytes
                        if len(content) % 2 != 0: content = content[:-1]
                        data = np.frombuffer(content, dtype=np.int16)
                        sr = 44100
                        is_fallback = True
                    else:
                        raise RuntimeError("Empty Data")
                except ValueError as ve:
                    raise ve
                except:
                    raise RuntimeError("ReadError")

        if 'data' not in locals() or len(data) == 0:
            raise RuntimeError("Empty Data")

        duration_sec = len(data) / sr
        if duration_sec > 1800:
            if 'data' in locals(): del data
            gc.collect()
            raise ValueError("Over30Min")

        if data.ndim > 1: 
            data = data.mean(axis=1, dtype=np.float32)
        elif data.dtype != np.float32:
            data = data.astype(np.float32)

        max_val = np.max(np.abs(data))
        if max_val == 0:
            return [], np.zeros(len(data), dtype=np.float32), np.zeros(len(data), dtype=np.float32), sr, 0.0, is_fallback

        data *= (1.0 / max_val)

        nyquist = 0.5 * sr
        low_cut, high_cut = 15000, 20000
        
        try:
            if nyquist > high_cut:
                sos = signal.butter(4, [low_cut, high_cut], btype='bandpass', fs=sr, output='sos')
                data_filt = signal.sosfiltfilt(sos, data)
            elif nyquist > low_cut:
                sos = signal.butter(4, low_cut, btype='highpass', fs=sr, output='sos')
                data_filt = signal.sosfiltfilt(sos, data)
            else:
                data_filt = data 
        except:
            data_filt = data

        if data is not data_filt: del data
        gc.collect()

        window_len = int(sr * 0.02)
        envelope = uniform_filter1d(np.abs(data_filt), size=window_len, mode='constant', cval=0.0)
        del data_filt

        sd_val = np.std(envelope)
        if sd_val < 0.0005:
            return [], envelope, np.zeros_like(envelope), sr, 0.0, is_fallback
            
        env_mean = np.mean(envelope)
        env_max = np.max(envelope)
        crest_factor = env_max / env_mean if env_mean > 0 else 0

        if crest_factor < crest_th:
            return [], envelope, np.zeros_like(envelope) + env_mean, sr, crest_factor, is_fallback

        local_window = int(sr * 0.5) 
        local_mean = uniform_filter1d(envelope, size=local_window, mode='reflect')
        
        offset = env_max * (k / 10.0)
        threshold_arr = local_mean + offset
        
        min_distance = int(sr * min_dist_sec)
        peaks, _ = signal.find_peaks(envelope, height=threshold_arr, distance=min_distance, prominence=0.0056175)
        
        return peaks, envelope, threshold_arr, sr, crest_factor, is_fallback
    
    def save_to_csv(self):
        items = self.tree.get_children()
        if not items: return

        m = self.entry_month.get().strip()
        d = self.entry_day.get().strip()
        s = self.entry_start.get().strip()
        e = self.entry_end.get().strip()

        default_name = "result.csv"
        if m and d and s and e:
            default_name = f"{m}月{d}日{s}時-{e}時.csv"
        
        save_path = filedialog.asksaveasfilename(
            initialfile=default_name,
            defaultextension=".csv", 
            filetypes=[("CSV Files", "*.csv")]
        )
        if not save_path: return

        try:
            with open(save_path, mode="w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["ファイル名", "検知回数", "状態"])
                
                total_count = 0
                for item_id in items:
                    vals = self.tree.item(item_id, "values")
                    writer.writerow(vals)
                    count_str = vals[1]
                    if count_str.isdigit():
                        total_count += int(count_str)
                
                writer.writerow(["合計", str(total_count), ""])

            messagebox.showinfo("成功", "保存しました")
        except Exception as e:
            messagebox.showerror("エラー", str(e))

    def on_file_select(self, event):
        selected = self.tree.selection()
        if not selected: return
        
        item_id = selected[0]
        file_name = self.tree.item(item_id, "values")[0]
        
        if self.loading_file == file_name: return
        self.loading_file = file_name

        self.canvas.delete("all")
        self.canvas.create_text(self.canvas_width//2, self.canvas_height//2, 
                                text="解析中...お待ちください", font=("MS Gothic", 12), fill="blue")

        threading.Thread(target=self._process_selection_thread, args=(item_id, file_name), daemon=True).start()

    def _process_selection_thread(self, item_id, file_name):
        folder = self.folder_path_var.get()
        if not folder: 
            self.loading_file = None
            return
        full_path = os.path.join(folder, file_name)

        try:
            gc.collect()

            if full_path in self.cache:
                data_args = self.cache[full_path]
                peaks = data_args[0]
                is_fallback = False
            else:
                k_val = self.default_k
                min_dist_sec = self.default_dist
                crest_th = self.default_crest
                
                peaks, envelope, threshold, sr, cf, is_fallback = self.analyze_single_file(full_path, k_val, min_dist_sec, crest_th)
                data_args = (peaks, envelope, threshold, sr, cf)
                self.cache[full_path] = data_args

            count = len(peaks)
            status_text = "完了(救)" if is_fallback else "完了"
            
            def _update_single_ui_result():
                self.tree.set(item_id, "Count", str(count))
                current_status = self.tree.item(item_id, "values")[2]
                if current_status == "待機" or "Err" in current_status or "破損" in current_status:
                     self.tree.set(item_id, "Status", status_text)
                self.update_total_label()

            self.frame.after(0, _update_single_ui_result)
            self.frame.after(0, lambda: self._update_graph_ui(file_name, data_args))

        except ValueError as e:
            msg = "長すぎ" if str(e) == "Over30Min" else "Err"
            self.frame.after(0, lambda: self._handle_error_ui(item_id, msg, f"エラー: {e}"))
        except RuntimeError as e:
            msg = "破損" if str(e) == "ReadError" else "空"
            self.frame.after(0, lambda: self._handle_error_ui(item_id, msg, f"エラー: {e}"))
        except Exception as e:
            self.frame.after(0, lambda: self._handle_error_ui(item_id, "Err", f"エラー: {e}"))
        
        finally:
            if self.loading_file == file_name:
                self.loading_file = None

    def _handle_error_ui(self, item_id, status_txt, canvas_msg):
        self.tree.set(item_id, "Status", status_txt)
        self.tree.set(item_id, "Count", "-")
        self.canvas.delete("all")
        self.canvas.create_text(self.canvas_width//2, self.canvas_height//2, text=canvas_msg, fill="red")
        self.update_total_label()

    def _update_graph_ui(self, file_name, data_args):
        selected = self.tree.selection()
        if selected:
            current_selected_file = self.tree.item(selected[0], "values")[0]
            if current_selected_file == file_name:
                self.current_graph_data = (file_name, *data_args)
                self.draw_graph_fast(file_name, *data_args)

    # --- Canvasを使った軽量グラフ描画 ---
    def draw_graph_fast(self, filename, peaks, envelope, threshold, sr, cf):
        self.canvas.delete("all")
        
        w = self.canvas_width
        h = self.canvas_height
        margin_left = 40
        margin_bottom = 30
        margin_top = 30
        margin_right = 10
        
        graph_w = w - margin_left - margin_right
        graph_h = h - margin_bottom - margin_top
        
        if graph_w <= 0 or graph_h <= 0: return

        total_points = len(envelope)
        display_points = 5000 
        step = max(1, total_points // display_points)
        
        env_disp = envelope[::step]
        
        if isinstance(threshold, (int, float)):
             thresh_disp = np.full_like(env_disp, threshold)
        elif isinstance(threshold, np.ndarray):
            thresh_disp = threshold[::step]
        else:
             thresh_disp = np.full_like(env_disp, 0)

        max_y = max(np.max(env_disp), np.max(thresh_disp)) * 1.1
        if max_y == 0: max_y = 1.0
        
        max_time = total_points / sr

        def time_to_x(t_sec):
            return margin_left + (t_sec / max_time) * graph_w

        def val_to_y(v):
            return margin_top + graph_h - (v / max_y) * graph_h

        # 軸
        self.canvas.create_line(margin_left, margin_top, margin_left, h - margin_bottom, fill="black") 
        self.canvas.create_line(margin_left, h - margin_bottom, w - margin_right, h - margin_bottom, fill="black") 

        # 目盛り
        for i in range(6):
            t = (max_time / 5) * i
            x = time_to_x(t)
            self.canvas.create_line(x, h - margin_bottom, x, h - margin_bottom + 5, fill="black")
            self.canvas.create_text(x, h - margin_bottom + 15, text=f"{t:.1f}s", font=("MS Gothic", 8))
            if i > 0:
                self.canvas.create_line(x, margin_top, x, h - margin_bottom, fill="#eeeeee", dash=(2, 2)) 

        for i in range(6):
            v = (max_y / 5) * i
            y = val_to_y(v)
            self.canvas.create_line(margin_left - 5, y, margin_left, y, fill="black")
            self.canvas.create_text(margin_left - 20, y, text=f"{v:.2f}", font=("MS Gothic", 8))
            if i > 0:
                self.canvas.create_line(margin_left, y, w - margin_right, y, fill="#eeeeee", dash=(2, 2))

        # 波形
        points = []
        for i, val in enumerate(env_disp):
            t = (i * step) / sr
            x = time_to_x(t)
            y = val_to_y(val)
            points.extend([x, y])
        
        if len(points) >= 4:
            self.canvas.create_line(points, fill="#1f77b4", width=1.0)

        # しきい値
        t_points = []
        for i, val in enumerate(thresh_disp):
            t = (i * step) / sr
            x = time_to_x(t)
            y = val_to_y(val)
            t_points.extend([x, y])

        if len(t_points) >= 4:
            self.canvas.create_line(t_points, fill="green", width=1.0, dash=(4, 4))

        # ピーク
        for p in peaks:
            t = p / sr
            if p < len(envelope):
                val = envelope[p]
                px = time_to_x(t)
                py = val_to_y(val)
                
                size = 3 
                self.canvas.create_line(px - size, py - size, px + size, py + size, fill="red", width=1.5)
                self.canvas.create_line(px - size, py + size, px + size, py - size, fill="red", width=1.5)

        # 【変更点】CF表示を削除し、ファイル名のみ表示
        title_text = f"{filename}"
        self.canvas.create_text(w/2, 15, text=title_text, font=("MS Gothic", 10, "bold"), fill="black")
        
        self.canvas.create_text(w - 60, 15, text="Env", fill="#1f77b4", font=("", 8), anchor="e")
        self.canvas.create_text(w - 10, 15, text="Thresh", fill="green", font=("", 8), anchor="e")


# ==========================================
#  機能2: WAV分割ツール (変更なし)
# ==========================================
class SplitterTab:
    def __init__(self, parent):
        self.frame = tk.Frame(parent)
        self.frame.pack(fill="both", expand=True)

        frame_file = tk.LabelFrame(self.frame, text="1. 対象ファイル選択", padx=10, pady=10)
        frame_file.pack(fill="x", padx=20, pady=15)

        self.file_path_var = tk.StringVar()
        entry_file = tk.Entry(frame_file, textvariable=self.file_path_var, width=50)
        entry_file.pack(side="left", padx=5)
        
        btn_browse = tk.Button(frame_file, text="参照...", command=self.select_file)
        btn_browse.pack(side="left")

        frame_setting = tk.LabelFrame(self.frame, text="2. 分割設定", padx=10, pady=10)
        frame_setting.pack(fill="x", padx=20, pady=5)

        tk.Label(frame_setting, text="分割単位 (分):").pack(side="left")
        
        self.minutes_entry = tk.Entry(frame_setting, width=10)
        self.minutes_entry.insert(0, "1")
        self.minutes_entry.pack(side="left", padx=5)
        
        tk.Label(frame_setting, text="※ 0.5 と入力すれば30秒になります", fg="gray").pack(side="left", padx=10)

        self.btn_run = tk.Button(self.frame, text="分割開始", command=self.start_split_thread, bg="#dddddd", height=2)
        self.btn_run.pack(fill="x", padx=40, pady=30)

        self.status_var = tk.StringVar(value="待機中")
        lbl_status = tk.Label(self.frame, textvariable=self.status_var, anchor="w")
        lbl_status.pack(fill="x", padx=40)

        self.progress = ttk.Progressbar(self.frame, mode="determinate")
        self.progress.pack(fill="x", padx=40, pady=5)

    def select_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("WAV files", "*.wav")])
        if file_path:
            self.file_path_var.set(file_path)

    def start_split_thread(self):
        threading.Thread(target=self.run_split, daemon=True).start()

    def run_split(self):
        input_path = self.file_path_var.get()
        minutes_str = self.minutes_entry.get()

        if not input_path or not os.path.exists(input_path):
            messagebox.showerror("エラー", "ファイルを選択してください。")
            return

        try:
            split_minutes = float(minutes_str)
            if split_minutes <= 0: raise ValueError
        except ValueError:
            messagebox.showerror("エラー", "分割単位には正の数値を入力してください。")
            return

        self.btn_run.config(state="disabled")
        
        try:
            base_name = os.path.basename(input_path)
            file_root, _ = os.path.splitext(base_name)
            output_dir = os.path.join(os.path.dirname(input_path), f"{file_root}_split")
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)

            with wave.open(input_path, 'rb') as wav_in:
                params = wav_in.getparams()
                n_frames = params.nframes
                framerate = params.framerate
                
                frames_per_split = int(split_minutes * 60 * framerate)
                total_splits = math.ceil(n_frames / frames_per_split)
                
                self.progress["maximum"] = total_splits
                self.progress["value"] = 0

                for i in range(total_splits):
                    self.status_var.set(f"保存中 ({i+1}/{total_splits})...")
                    self.frame.update_idletasks()

                    output_filename = os.path.join(output_dir, f"{file_root}_{i+1:03d}.wav")
                    data = wav_in.readframes(frames_per_split)
                    if not data: break

                    with wave.open(output_filename, 'wb') as wav_out:
                        wav_out.setparams(params)
                        n_frames_current = len(data) // (params.nchannels * params.sampwidth)
                        wav_out.setnframes(n_frames_current)
                        wav_out.writeframes(data)
                    
                    self.progress["value"] = i + 1
            
            self.status_var.set("完了！")
            messagebox.showinfo("成功", f"分割が完了しました。\n保存先: {output_dir}")

        except Exception as e:
            messagebox.showerror("エラー", f"予期せぬエラー:\n{e}")
        finally:
            self.btn_run.config(state="normal")
            self.progress["value"] = 0

# ==========================================
#  メインアプリ
# ==========================================
class MainApp:
    def __init__(self, root):
        self.root = root
        self.root.title("音声解析 & 分割ツール (Safe & NoCF)")
        self.root.geometry("1000x800")

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)

        tab1_frame = ttk.Frame(notebook)
        notebook.add(tab1_frame, text=" 音イベント解析 ")
        self.counter_tab = EventCounterTab(tab1_frame)

        tab2_frame = ttk.Frame(notebook)
        notebook.add(tab2_frame, text=" WAV分割 ")
        self.splitter_tab = SplitterTab(tab2_frame)

    def on_closing(self):
        self.root.destroy()
        sys.exit()

if __name__ == "__main__":
    root = tk.Tk()
    app = MainApp(root)
    root.mainloop()