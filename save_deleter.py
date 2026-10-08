"""
The Witcher 3 Save Deleter
Менеджер очистки сохранений для The Witcher 3: Дикая Охота
"""

import os
import sys
import math
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    from send2trash import send2trash
    HAS_SEND2TRASH = True
except ImportError:
    HAS_SEND2TRASH = False


# Размеры миниатюр
THUMB_WIDTH = 160
THUMB_HEIGHT = 90
ROW_HEIGHT = 100

# Цветовая палитра
COLOR_BG_NORMAL = "#ffffff"
COLOR_BG_ALT = "#fbfbfb"
COLOR_BG_SELECTED = "#d0e2ff"
COLOR_BG_HOVER = "#eef4fd"
COLOR_BORDER = "#e0e0e0"
COLOR_TEXT_PRIMARY = "#111111"
COLOR_TEXT_SECONDARY = "#555555"
COLOR_ACCENT_RED = "#d9383a"

# Типы сохранений по префиксу
SAVE_TYPE_PREFIXES = {
    "AutoSave": "Автосохранение",
    "ManualSave": "Ручное сохранение",
    "CheckPoint": "Контрольная точка",
    "QuickSave": "Быстрое сохранение",
}


def find_default_saves_dir() -> Path:
    """Определяет стандартное расположение папки сохранений Ведьмака 3."""
    user_home = Path.home()
    candidates = [
        Path(__file__).parent / "gamesaves",
        user_home / "Documents" / "The Witcher 3" / "gamesaves",
        user_home / "OneDrive" / "Documents" / "The Witcher 3" / "gamesaves",
        user_home / "Documents" / "The Witcher 3" / "saves",
    ]
    for p in candidates:
        if p.exists() and p.is_dir():
            return p
    return user_home / "Documents" / "The Witcher 3" / "gamesaves"


def format_file_size(size_bytes: int) -> str:
    """Форматирует размер файла в удобочитаемый вид."""
    if size_bytes < 1024:
        return f"{size_bytes} Б"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} КБ"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} МБ"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} ГБ"


class ThumbnailCache:
    """Кэш миниатюр для оптимизации расхода памяти и ускорения скроллинга."""
    def __init__(self, max_size: int = 500):
        self.max_size = max_size
        self._cache = {}
        self._placeholder = None

    def get(self, png_path: Path) -> ImageTk.PhotoImage | None:
        if not HAS_PIL:
            return None

        path_str = str(png_path)
        if path_str in self._cache:
            return self._cache[path_str]

        photo = self._load_image(png_path)
        if len(self._cache) >= self.max_size:
            # Очищаем четверть кэша при переполнении
            remove_keys = list(self._cache.keys())[:len(self._cache) // 4]
            for k in remove_keys:
                del self._cache[k]

        self._cache[path_str] = photo
        return photo

    def get_placeholder(self) -> ImageTk.PhotoImage | None:
        if not HAS_PIL:
            return None
        if self._placeholder is None:
            # Создаем нейтральное серое изображение-заглушку
            img = Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT), color=(45, 45, 50))
            self._placeholder = ImageTk.PhotoImage(img)
        return self._placeholder

    def _load_image(self, png_path: Path) -> ImageTk.PhotoImage | None:
        if not png_path.exists():
            return self.get_placeholder()
        try:
            with Image.open(png_path) as im:
                w, h = im.size
                scale = min(THUMB_WIDTH / w, THUMB_HEIGHT / h)
                new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))
                im_resized = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
                
                # Центрируем изображение на черном фоне нужного размера
                bg = Image.new("RGB", (THUMB_WIDTH, THUMB_HEIGHT), (25, 25, 28))
                paste_x = (THUMB_WIDTH - new_w) // 2
                paste_y = (THUMB_HEIGHT - new_h) // 2
                bg.paste(im_resized, (paste_x, paste_y))
                return ImageTk.PhotoImage(bg)
        except Exception:
            return self.get_placeholder()


class VirtualSaveList(tk.Frame):
    """
    Виртуализированный список сохранений.
    Рендерит только видимые на экране строки, полностью устраняя
    проблему лимита 32767 пикселей Win32/Tkinter и зависания интерфейса.
    """
    def __init__(self, parent, thumb_cache: ThumbnailCache, on_selection_change=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.thumb_cache = thumb_cache
        self.on_selection_change = on_selection_change

        self.items = []          # Список словарей данных всех сохранений
        self.selected_indices = set()  # Множество индексов выбранных сохранений

        self.scroll_y = 0        # Текущее смещение скролла в пикселях
        self.last_clicked_idx = None
        self.drag_start_idx = None
        self.is_dragging = False

        self._pool = []          # Пул UI-виджетов строк для повторного использования
        self.configure(bg="#ffffff")

        self._setup_ui()

    def _setup_ui(self):
        self.canvas = tk.Canvas(self, bg="#ffffff", highlightthickness=0, bd=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.v_scroll = ttk.Scrollbar(self, orient="vertical", command=self._on_scrollbar)
        self.v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-4>", lambda e: self._scroll_units(-3))
        self.canvas.bind("<Button-5>", lambda e: self._scroll_units(3))

        # Привязка клавиш навигации
        self.bind("<Up>", lambda e: self._scroll_units(-1))
        self.bind("<Down>", lambda e: self._scroll_units(1))
        self.bind("<Prior>", lambda e: self._scroll_page(-1))  # Page Up
        self.bind("<Next>", lambda e: self._scroll_page(1))   # Page Down
        self.bind("<Home>", lambda e: self._scroll_to(0))
        self.bind("<End>", lambda e: self._scroll_to(self._max_scroll_y()))

    def _max_scroll_y(self) -> int:
        total_h = len(self.items) * ROW_HEIGHT
        view_h = self.canvas.winfo_height()
        return max(0, total_h - view_h)

    def _on_canvas_resize(self, event):
        self._ensure_widget_pool(event.height)
        self._clamp_scroll()
        self.render()

    def _ensure_widget_pool(self, view_height: int):
        needed = (view_height // ROW_HEIGHT) + 3
        while len(self._pool) < needed:
            idx = len(self._pool)
            row_frame = self._create_row_widget()
            self._pool.append(row_frame)

    def _create_row_widget(self):
        """Создает одну строку-шаблон, которая повторно используется."""
        row = tk.Frame(self.canvas, bg=COLOR_BG_NORMAL, height=ROW_HEIGHT, bd=0)
        row.pack_propagate(False)

        # Контейнер для выравнивания
        inner = tk.Frame(row, bg=COLOR_BG_NORMAL)
        inner.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # Чекбокс
        var = tk.BooleanVar(value=False)
        cb = ttk.Checkbutton(inner, variable=var, takefocus=False)
        cb.pack(side=tk.LEFT, padx=(0, 10))

        # Превью
        img_label = tk.Label(inner, bg="#202020", width=THUMB_WIDTH, height=THUMB_HEIGHT)
        img_label.pack(side=tk.LEFT, padx=(0, 12))

        # Текстовые метки
        text_frame = tk.Frame(inner, bg=COLOR_BG_NORMAL)
        text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        title_lbl = tk.Label(
            text_frame, text="", font=("Segoe UI", 10, "bold"),
            anchor="w", fg=COLOR_TEXT_PRIMARY, bg=COLOR_BG_NORMAL
        )
        title_lbl.pack(fill=tk.X, anchor="w", pady=(2, 2))

        meta_lbl = tk.Label(
            text_frame, text="", font=("Segoe UI", 9),
            anchor="w", fg=COLOR_TEXT_SECONDARY, bg=COLOR_BG_NORMAL
        )
        meta_lbl.pack(fill=tk.X, anchor="w")

        file_lbl = tk.Label(
            text_frame, text="", font=("Consolas", 8),
            anchor="w", fg="#888888", bg=COLOR_BG_NORMAL
        )
        file_lbl.pack(fill=tk.X, anchor="w", pady=(2, 0))

        # Линия-разделитель внизу
        sep = tk.Frame(row, bg=COLOR_BORDER, height=1)
        sep.pack(side=tk.BOTTOM, fill=tk.X)

        # Сохраняем ссылки
        widgets_dict = {
            "root": row,
            "inner": inner,
            "cb": cb,
            "cb_var": var,
            "img": img_label,
            "text_frame": text_frame,
            "title": title_lbl,
            "meta": meta_lbl,
            "file": file_lbl,
            "sep": sep,
            "item_index": None,
            "photo_ref": None,
        }

        # Привязка событий мыши (клик по всей строке, драг, колесико)
        clickable_widgets = [row, inner, img_label, text_frame, title_lbl, meta_lbl, file_lbl]
        for w in clickable_widgets:
            w.bind("<ButtonPress-1>", lambda e, r=widgets_dict: self._on_row_press(e, r))
            w.bind("<B1-Motion>", lambda e, r=widgets_dict: self._on_row_drag(e, r))
            w.bind("<ButtonRelease-1>", lambda e, r=widgets_dict: self._on_row_release(e, r))
            w.bind("<MouseWheel>", self._on_mousewheel)
            w.bind("<Button-4>", lambda e: self._scroll_units(-3))
            w.bind("<Button-5>", lambda e: self._scroll_units(3))

        # Чекбокс клик
        cb.configure(command=lambda r=widgets_dict: self._on_cb_toggle(r))

        return widgets_dict

    def _on_cb_toggle(self, row_dict):
        idx = row_dict["item_index"]
        if idx is None or idx >= len(self.items):
            return
        is_sel = row_dict["cb_var"].get()
        if is_sel:
            self.selected_indices.add(idx)
        else:
            self.selected_indices.discard(idx)
        self.last_clicked_idx = idx
        self._update_row_colors(row_dict, idx)
        if self.on_selection_change:
            self.on_selection_change()

    def _on_row_press(self, event, row_dict):
        self.focus_set()
        idx = row_dict["item_index"]
        if idx is None or idx >= len(self.items):
            return

        self.drag_start_idx = idx
        self.is_dragging = False

        # Shift + Клик: выделение диапазона
        if event.state & 0x0001:  # Shift mask
            anchor = self.last_clicked_idx if self.last_clicked_idx is not None else idx
            low, high = min(anchor, idx), max(anchor, idx)
            for i in range(low, high + 1):
                self.selected_indices.add(i)
        # Ctrl + Клик: переключение одного
        elif event.state & 0x0004:  # Control mask
            if idx in self.selected_indices:
                self.selected_indices.discard(idx)
            else:
                self.selected_indices.add(idx)
            self.last_clicked_idx = idx
        else:
            # Обычный клик: инвертировать выбор строки
            if idx in self.selected_indices:
                self.selected_indices.discard(idx)
            else:
                self.selected_indices.add(idx)
            self.last_clicked_idx = idx

        self.render()
        if self.on_selection_change:
            self.on_selection_change()

    def _on_row_drag(self, event, row_dict):
        """Выделение нескольких элементов при протягивании мыши с зажатой ЛКМ."""
        if self.drag_start_idx is None:
            return

        self.is_dragging = True
        
        # Вычисляем глобальную координату Y в списке
        mouse_canvas_y = event.widget.winfo_rooty() - self.canvas.winfo_rooty() + event.y
        current_y = self.scroll_y + mouse_canvas_y
        hovered_idx = int(current_y // ROW_HEIGHT)
        hovered_idx = max(0, min(len(self.items) - 1, hovered_idx))

        low, high = min(self.drag_start_idx, hovered_idx), max(self.drag_start_idx, hovered_idx)
        for i in range(low, high + 1):
            self.selected_indices.add(i)

        # Автоматическая прокрутка при выходе за пределы
        view_h = self.canvas.winfo_height()
        if mouse_canvas_y < 30:
            self._scroll_units(-1)
        elif mouse_canvas_y > view_h - 30:
            self._scroll_units(1)

        self.render()
        if self.on_selection_change:
            self.on_selection_change()

    def _on_row_release(self, event, row_dict):
        self.drag_start_idx = None
        self.is_dragging = False

    def _update_row_colors(self, row_dict, idx: int):
        is_sel = idx in self.selected_indices
        bg = COLOR_BG_SELECTED if is_sel else (COLOR_BG_NORMAL if idx % 2 == 0 else COLOR_BG_ALT)

        row_dict["root"].configure(bg=bg)
        row_dict["inner"].configure(bg=bg)
        row_dict["text_frame"].configure(bg=bg)
        row_dict["title"].configure(bg=bg)
        row_dict["meta"].configure(bg=bg)
        row_dict["file"].configure(bg=bg)
        row_dict["cb_var"].set(is_sel)

    def render(self):
        """Отрисовывает видимые строки и синхронизирует скроллбар."""
        total_items = len(self.items)
        view_h = self.canvas.winfo_height()
        view_w = self.canvas.winfo_width()

        if total_items == 0 or view_h <= 1:
            for r in self._pool:
                r["root"].place_forget()
            self.v_scroll.set(0.0, 1.0)
            return

        first_idx = self.scroll_y // ROW_HEIGHT
        pixel_offset = self.scroll_y % ROW_HEIGHT

        # Размещаем строки из пула
        for i, row_dict in enumerate(self._pool):
            item_idx = first_idx + i
            if item_idx < total_items:
                data = self.items[item_idx]
                row_dict["item_index"] = item_idx

                # Заполняем данные
                row_dict["title"].configure(text=data["name"])
                row_dict["meta"].configure(text=f"Дата: {data['date']}   |   Размер: {data['size_str']}   |   Тип: {data['savetype']}")
                row_dict["file"].configure(text=f"Файл: {data['path'].name}")

                # Миниатюра
                photo = self.thumb_cache.get(data["png_path"])
                row_dict["img"].configure(image=photo)
                row_dict["photo_ref"] = photo

                # Цвета и состояние чекбокса
                self._update_row_colors(row_dict, item_idx)

                # Позиционирование
                y_pos = (i * ROW_HEIGHT) - pixel_offset
                row_dict["root"].place(x=0, y=y_pos, width=view_w, height=ROW_HEIGHT)
            else:
                row_dict["item_index"] = None
                row_dict["root"].place_forget()

        # Обновление скроллбара
        total_h = total_items * ROW_HEIGHT
        first_frac = self.scroll_y / total_h
        last_frac = min(1.0, (self.scroll_y + view_h) / total_h)
        self.v_scroll.set(first_frac, last_frac)

    def _clamp_scroll(self):
        self.scroll_y = max(0, min(self._max_scroll_y(), self.scroll_y))

    def _scroll_to(self, new_y: int):
        self.scroll_y = new_y
        self._clamp_scroll()
        self.render()

    def _scroll_units(self, units: int):
        self._scroll_to(self.scroll_y + units * (ROW_HEIGHT // 2))

    def _scroll_page(self, direction: int):
        view_h = self.canvas.winfo_height()
        self._scroll_to(self.scroll_y + direction * (view_h - ROW_HEIGHT))

    def _on_mousewheel(self, event):
        delta = -1 if event.delta > 0 else 1
        self._scroll_units(delta * 2)

    def _on_scrollbar(self, action, *args):
        total_h = len(self.items) * ROW_HEIGHT
        if total_h <= 0:
            return

        if action == "moveto":
            fraction = float(args[0])
            self._scroll_to(int(fraction * total_h))
        elif action == "scroll":
            count = int(args[0])
            unit_type = args[1]
            if unit_type == "units":
                self._scroll_units(count)
            elif unit_type == "pages":
                self._scroll_page(count)

    def set_items(self, items: list[dict]):
        self.items = items
        self.selected_indices.clear()
        self.last_clicked_idx = None
        self.scroll_y = 0
        self.render()

    def select_all(self):
        self.selected_indices = set(range(len(self.items)))
        self.render()
        if self.on_selection_change:
            self.on_selection_change()

    def deselect_all(self):
        self.selected_indices.clear()
        self.render()
        if self.on_selection_change:
            self.on_selection_change()

    def invert_selection(self):
        all_indices = set(range(len(self.items)))
        self.selected_indices = all_indices - self.selected_indices
        self.render()
        if self.on_selection_change:
            self.on_selection_change()

    def select_by_predicate(self, predicate):
        for idx, item in enumerate(self.items):
            if predicate(item):
                self.selected_indices.add(idx)
        self.render()
        if self.on_selection_change:
            self.on_selection_change()


class SaveDeleterApp(tk.Tk):
    """Главное окно приложения для удаления сохранений Ведьмака 3."""
    def __init__(self):
        super().__init__()
        self.title("The Witcher 3 — Менеджер очистки сохранений")
        self.geometry("920x660")
        self.minsize(780, 480)

        self.saves_dir = find_default_saves_dir()
        self.thumb_cache = ThumbnailCache()
        self.all_saves = []

        self._setup_styles()
        self._build_ui()
        self.refresh_list()

    def _setup_styles(self):
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # Настройка цветов кнопок
        self.style.configure("Danger.TButton", foreground="#ffffff", background=COLOR_ACCENT_RED, font=("Segoe UI", 9, "bold"))
        self.style.map("Danger.TButton", background=[("active", "#b82b2d"), ("pressed", "#9c2022")])

    def _build_ui(self):
        # 1. Верхняя панель: выбор директории
        top_frame = ttk.Frame(self, padding=(10, 8, 10, 4))
        top_frame.pack(fill=tk.X)

        ttk.Label(top_frame, text="Папка сохранений:", font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 6))

        self.path_var = tk.StringVar(value=str(self.saves_dir))
        path_entry = ttk.Entry(top_frame, textvariable=self.path_var, font=("Segoe UI", 9))
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        ttk.Button(top_frame, text="Обзор...", command=self.select_saves_dir).pack(side=tk.LEFT)

        # 2. Основная рабочая область: виртуальный список
        center_frame = ttk.Frame(self, padding=(10, 4, 10, 4))
        center_frame.pack(fill=tk.BOTH, expand=True)

        self.save_list = VirtualSaveList(
            center_frame,
            thumb_cache=self.thumb_cache,
            on_selection_change=self.update_status,
        )
        self.save_list.pack(fill=tk.BOTH, expand=True)

        # 3. Нижняя панель действий
        bottom_frame = ttk.Frame(self, padding=(10, 8, 10, 10))
        bottom_frame.pack(fill=tk.X)

        # Быстрый выбор
        quick_frame = ttk.Frame(bottom_frame)
        quick_frame.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(quick_frame, text="Быстрый выбор:", font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(quick_frame, text="Автосейвы и Чекпоинты", command=self._select_autos_and_checkpoints).pack(side=tk.LEFT, padx=2)
        ttk.Button(quick_frame, text="Выбрать все", command=self.save_list.select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(quick_frame, text="Снять выбор", command=self.save_list.deselect_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(quick_frame, text="Инвертировать выбор", command=self.save_list.invert_selection).pack(side=tk.LEFT, padx=2)

        # Нижняя строка с кнопками удаления и статусом
        actions_frame = ttk.Frame(bottom_frame)
        actions_frame.pack(fill=tk.X)

        self.del_btn = ttk.Button(actions_frame, text="Удалить выбранные", style="Danger.TButton", command=self.confirm_delete)
        self.del_btn.pack(side=tk.LEFT, padx=(0, 6))

        ttk.Button(actions_frame, text="Обновить список", command=self.refresh_list).pack(side=tk.LEFT, padx=(0, 12))

        # Опция помещения в корзину
        self.recycle_bin_var = tk.BooleanVar(value=HAS_SEND2TRASH)
        if HAS_SEND2TRASH:
            ttk.Checkbutton(actions_frame, text="Перемещать в Корзину (безопасно)", variable=self.recycle_bin_var).pack(side=tk.LEFT)

        # Статистика справа
        self.status_label = ttk.Label(actions_frame, text="", font=("Segoe UI", 9, "bold"))
        self.status_label.pack(side=tk.RIGHT)

    def _select_autos_and_checkpoints(self):
        """Выделяет только автосохранения и контрольные точки."""
        self.save_list.select_by_predicate(
            lambda item: item["prefix"] in ("AutoSave", "CheckPoint")
        )

    def update_status(self):
        """Обновляет индикатор выбранных файлов и освобождаемого места."""
        total_count = len(self.all_saves)
        sel_indices = self.save_list.selected_indices
        sel_count = len(sel_indices)
        remaining_count = total_count - sel_count

        sel_bytes = sum(self.all_saves[i]["total_size"] for i in sel_indices)
        rem_bytes = sum(self.all_saves[i]["total_size"] for i in range(total_count) if i not in sel_indices)

        self.status_label.config(
            text=f"Выбрано: {sel_count} ({format_file_size(sel_bytes)})  |  Останется: {remaining_count} ({format_file_size(rem_bytes)})"
        )

    def refresh_list(self):
        """Сканирует папку и обновляет список сохранений."""
        self.saves_dir = Path(self.path_var.get())
        if not self.saves_dir.exists():
            messagebox.showwarning(
                "Папка не найдена",
                f"Папка с сохранениями не существует:\n{self.saves_dir}\n\nПожалуйста, укажите правильный путь кнопкой 'Обзор...'",
            )
            self.all_saves = []
            self.save_list.set_items([])
            self.update_status()
            return

        saves = []
        for f in self.saves_dir.glob("*.sav"):
            if not f.is_file():
                continue

            try:
                stat = f.stat()
                mtime = stat.st_mtime
                date_str = datetime.fromtimestamp(mtime).strftime("%d.%m.%Y %H:%M:%S")
                sav_size = stat.st_size
            except OSError:
                mtime = 0
                date_str = "неизвестно"
                sav_size = 0

            png_path = f.with_suffix(".png")
            png_size = png_path.stat().st_size if png_path.exists() else 0
            total_size = sav_size + png_size

            prefix = f.name.split("_")[0]
            savetype = SAVE_TYPE_PREFIXES.get(prefix, "Сохранение")
            display_name = f"{savetype} ({f.stem})"

            saves.append({
                "path": f,
                "png_path": png_path,
                "prefix": prefix,
                "savetype": savetype,
                "name": display_name,
                "mtime": mtime,
                "date": date_str,
                "total_size": total_size,
                "size_str": format_file_size(total_size),
            })

        # Сортировка: самые новые сохранения идут первыми
        saves.sort(key=lambda s: s["mtime"], reverse=True)

        self.all_saves = saves
        self.save_list.set_items(saves)
        self.update_status()

    def select_saves_dir(self):
        chosen = filedialog.askdirectory(
            initialdir=str(self.saves_dir if self.saves_dir.exists() else Path.home()),
            title="Выберите папку с сохранениями The Witcher 3",
        )
        if chosen:
            self.saves_dir = Path(chosen)
            self.path_var.set(str(self.saves_dir))
            self.refresh_list()

    def confirm_delete(self):
        """Подтверждение и удаление выбранных файлов."""
        sel_indices = self.save_list.selected_indices
        if not sel_indices:
            messagebox.showinfo("Удаление", "Не выбрано ни одного сохранения для удаления.")
            return

        to_delete = [self.all_saves[i] for i in sorted(sel_indices)]
        count = len(to_delete)
        total_size = sum(item["total_size"] for item in to_delete)
        remaining = len(self.all_saves) - count

        if remaining == 0:
            warn_msg = (
                f"ВНИМАНИЕ! Вы собираетесь удалить ВСЕ сохранения ({count} шт., {format_file_size(total_size)})!\n\n"
                f"После этой операции не останется ни одного файла сохранения.\nПродолжить?"
            )
            if not messagebox.askyesno("Критическое предупреждение", warn_msg, icon="warning"):
                return
        else:
            confirm_msg = (
                f"Вы уверены, что хотите удалить {count} сохранение(й)?\n"
                f"Освободится места: {format_file_size(total_size)}\n"
                f"Останется сохранений: {remaining}\n\n"
                f"Способ удаления: {'Корзина Windows' if self.recycle_bin_var.get() and HAS_SEND2TRASH else 'Безвозвратно'}"
            )
            if not messagebox.askyesno("Подтверждение удаления", confirm_msg):
                return

        use_trash = self.recycle_bin_var.get() and HAS_SEND2TRASH
        deleted_count = 0
        errors = []

        for item in to_delete:
            sav_file = item["path"]
            png_file = item["png_path"]

            files_to_remove = [sav_file]
            if png_file.exists():
                files_to_remove.append(png_file)

            for target in files_to_remove:
                try:
                    if use_trash:
                        send2trash(str(target))
                    else:
                        target.unlink(missing_ok=True)
                except Exception as ex:
                    errors.append(f"{target.name}: {ex}")

            deleted_count += 1

        self.refresh_list()

        if errors:
            err_text = "\n".join(errors[:10])
            if len(errors) > 10:
                err_text += f"\n...и еще {len(errors) - 10} ошибок."
            messagebox.showerror("Ошибки при удалении", f"Не удалось удалить часть файлов:\n{err_text}")
        else:
            messagebox.showinfo(
                "Успешно",
                f"Удалено {deleted_count} сохранение(й).\nОсвобождено {format_file_size(total_size)}.",
            )


def main():
    if not HAS_PIL:
        # Информируем пользователя о библиотеке Pillow
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning(
            "Внимание",
            "Для отображения скриншотов сохранений рекомендуется установить Pillow:\npip install Pillow",
        )
        root.destroy()

    app = SaveDeleterApp()
    app.mainloop()


if __name__ == "__main__":
    main()
