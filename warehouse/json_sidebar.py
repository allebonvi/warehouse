# json_sidebar.py
import os, json
import tkinter as tk
from tkinter import ttk

# --- opzionale: supporto icone FA/resize immagine ---
try:
    from PIL import Image, ImageTk, ImageDraw, ImageFont
    _PIL_OK = True
except Exception:
    _PIL_OK = False

__all__ = ["JsonSidebar"]

def _pct_to_rel(x):
    if isinstance(x, str):
        s = x.strip().replace(",", ".")
        if s.endswith("%"):
            try: return max(0.0, min(1.0, float(s[:-1]) / 100.0))
            except ValueError: return 0.0
        try:
            v = float(s)
            return max(0.0, min(1.0, v if v <= 1.0 else v / 100.0))
        except ValueError:
            return 0.0
    if isinstance(x, (int, float)):
        return max(0.0, min(1.0, x if x <= 1.0 else x / 100.0))
    return 0.0

class _ScrollFrame(ttk.Frame):
    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        self.columnconfigure(0, weight=1); self.rowconfigure(0, weight=1)
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_wheel, add="+")
        self.canvas.bind_all("<Button-4>", self._on_wheel, add="+")
        self.canvas.bind_all("<Button-5>", self._on_wheel, add="+")
    def _on_inner_configure(self, _): self.canvas.configure(scrollregion=self.canvas.bbox("all"))
    def _on_canvas_configure(self, e): self.canvas.itemconfigure(self._win, width=e.width)
    def _on_wheel(self, e):
        if getattr(e, "num", None) == 4 or getattr(e, "delta", 0) > 0: self.canvas.yview_scroll(-1, "units")
        else: self.canvas.yview_scroll(1, "units")

class JsonSidebar(ttk.Frame):
    """
    Sidebar apribile/chiudibile da JSON con supporto TREE:
      - Posizionamento in % (place relx/rely/relwidth/relheight)
      - Voci con icone (PNG/JPG) o 'fa' (OTF/TTF via Pillow)
      - Nodi ad albero (children) espandibili
      - Foglie: 'command' (callbacks[name]) o 'frame' (passa a page_loader)

    JSON (esempio nei commenti sotto).
    """
    def __init__(self, master, config, callbacks=None, page_loader=None, **kwargs):
        super().__init__(master, **kwargs)
        self.config_dict = self._load_config(config)
        self.callbacks = callbacks or {}
        self.page_loader = page_loader  # callable(name) -> mostra/crea frame

        # --- posizione/dimensioni ---
        pos = self.config_dict.get("position", {})
        self.relx = _pct_to_rel(pos.get("relx", 0))
        self.rely = _pct_to_rel(pos.get("rely", 0))
        self.relheight = _pct_to_rel(pos.get("height_pct", 1.0))
        self.relwidth_open = _pct_to_rel(pos.get("width_open_pct", 0.25))
        self.relwidth_closed = _pct_to_rel(pos.get("width_closed_pct", 0.08))
        self.is_open = bool(pos.get("start_open", False))  # default: CHIUSA

        # --- aspetto ---
        app = self.config_dict.get("appearance", {})
        self.title_text = app.get("title", "Menu")
        self.show_icons = bool(app.get("show_icons", True))
        self.icon_size = int(app.get("icon_size", 18))
        self.icon_color = str(app.get("icon_color", "#222222"))
        self.fa_ttf_path = self._resolve_path(app.get("fa_ttf") or app.get("fa_font"))

        # --- stato tree ---
        self._expanded = {}   # node_id -> bool
        self._rows = []       # widget rows (destroy on rerender)
        self._icons = []      # keep references (PhotoImage/ImageTk)
        self._row_index = 0   # current grid row
        self._full_texts = {} # idx -> testo (per hide/show text a sidebar chiusa)

        # --- layout base ---
        self.columnconfigure(0, weight=1)
        self.header = ttk.Frame(self); self.header.grid(row=0, column=0, sticky="ew")
        self.header.columnconfigure(0, weight=1)
        self.lbl_title = ttk.Label(self.header, text=self.title_text, anchor="w", padding=(10, 8))
        self.lbl_title.grid(row=0, column=0, sticky="ew")
        self.btn_toggle = ttk.Button(self.header, text="⮞" if not self.is_open else "⮜", width=3, command=self.toggle)
        self.btn_toggle.grid(row=0, column=1, sticky="ne", padx=(0, 6), pady=6)

        self.body = _ScrollFrame(self); self.body.grid(row=1, column=0, sticky="nsew"); self.rowconfigure(1, weight=1)
        self.footer = ttk.Frame(self); self.footer.grid(row=2, column=0, sticky="ew")

        style = ttk.Style(self)
        style.configure("JSidebar.TButton", anchor="w", padding=(10, 6))
        style.configure("JSidebar.Section.TLabel", padding=(10, 8))
        style.configure("JSidebar.Group.TButton", anchor="w", padding=(8, 6))  # riga gruppo

        # --- build tree ---
        self._build_tree()
        self._apply_place()
        self._apply_open_state(first=True)

    # ===== API =====
    def toggle(self):
        self.is_open = not self.is_open
        self._apply_open_state()

    def open(self):
        if not self.is_open:
            self.is_open = True; self._apply_open_state()

    def close(self):
        if self.is_open:
            self.is_open = False; self._apply_open_state()

    def reapply_from_config(self, config=None):
        if config is not None: self.config_dict = self._load_config(config)
        pos = self.config_dict.get("position", {})
        self.relx = _pct_to_rel(pos.get("relx", self.relx))
        self.rely = _pct_to_rel(pos.get("rely", self.rely))
        self.relheight = _pct_to_rel(pos.get("height_pct", self.relheight))
        self.relwidth_open = _pct_to_rel(pos.get("width_open_pct", self.relwidth_open))
        self.relwidth_closed = _pct_to_rel(pos.get("width_closed_pct", self.relwidth_closed))
        self.is_open = bool(pos.get("start_open", self.is_open))
        app = self.config_dict.get("appearance", {})
        self.title_text = app.get("title", self.title_text); self.lbl_title.configure(text=self.title_text)
        self.show_icons = bool(app.get("show_icons", self.show_icons))
        self.icon_size = int(app.get("icon_size", self.icon_size))
        self.icon_color = str(app.get("icon_color", self.icon_color))
        self.fa_ttf_path = self._resolve_path(app.get("fa_ttf") or app.get("fa_font") or self.fa_ttf_path)

        self._build_tree()
        self._apply_place(); self._apply_open_state()

    def add_footer_widget(self, widget: tk.Widget, side="left"):
        widget.pack(in_=self.footer, side=side, padx=8, pady=6)

    # ===== internals =====
    def _load_config(self, config):
        if isinstance(config, dict):
            self._config_dir = None
            return config
        if isinstance(config, str):
            cfg_path = os.path.abspath(config)
            self._config_dir = os.path.dirname(cfg_path)
            with open(cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        raise TypeError("config deve essere dict o path JSON")

    def _resolve_path(self, p):
        if not p: return None
        if os.path.isabs(p) or not getattr(self, "_config_dir", None): return p
        return os.path.normpath(os.path.join(self._config_dir, p))

    def _apply_place(self):
        rw = self.relwidth_open if self.is_open else self.relwidth_closed
        self.place(relx=self.relx, rely=self.rely, relwidth=rw, relheight=self.relheight)

    def _apply_open_state(self, first=False):
        self._apply_place()
        # aggiorna testo bottoni (icone sempre visibili)
        for row in self._rows:
            btn = row.get("button")
            if not btn: continue
            full = row.get("full_text", "")
            if self.is_open:
                btn.configure(text=("  " + full if row.get("has_icon") else full))
            else:
                btn.configure(text="")
        self.btn_toggle.configure(text="⮜" if self.is_open else "⮞")
        if not first: self.update_idletasks()

    # -- tree build/render --
    def _build_tree(self):
        # pulisci righe esistenti
        for row in self._rows:
            for w in ("frame","chev","button"):
                if row.get(w): row[w].destroy()
        self._rows.clear(); self._icons.clear(); self._row_index = 0

        items = self.config_dict.get("items", [])
        self._render_items(items, depth=0, parent_id="root", parent_expanded=True)

    def _render_items(self, items, depth, parent_id, parent_expanded):
        # disegna solo se il parent è espanso (root=True)
        if not parent_expanded: return
        for idx, node in enumerate(items):
            node_id = f"{parent_id}/{idx}"
            is_section = "section" in node and not node.get("children")
            has_children = bool(node.get("children"))
            # stato expanded default da json
            if node_id not in self._expanded:
                self._expanded[node_id] = bool(node.get("expanded", False))
            # SEZIONE semplice
            if is_section:
                lbl = ttk.Label(self.body.inner, text=node["section"], style="JSidebar.Section.TLabel")
                lbl.grid(row=self._row_index, column=0, sticky="ew", padx=6, pady=(8, 4))
                self.body.inner.grid_columnconfigure(0, weight=1)
                self._rows.append({"frame": lbl})
                self._row_index += 1
                continue

            # RIGA (gruppo o foglia)
            rowf = ttk.Frame(self.body.inner)
            rowf.grid(row=self._row_index, column=0, sticky="ew")
            self.body.inner.grid_columnconfigure(0, weight=1)

            # indent + chevron
            indent = 6 + depth * 14
            chev_txt = ""
            if has_children:
                chev_txt = "▼" if self._expanded[node_id] else "▶"
            chev = ttk.Label(rowf, text=chev_txt, width=2)
            chev.grid(row=0, column=0, sticky="w", padx=(indent, 2))

            # icona + testo
            icon_img = self._create_icon_image(node) if self.show_icons else None
            full_text = node.get("text", "")
            has_icon = bool(icon_img)
            # handler
            def _on_click(n=node, nid=node_id):
                # se ha children: se non ha command/frame, il click sul bottone toggla
                if n.get("children") and not (n.get("command") or n.get("frame")):
                    self._expanded[nid] = not self._expanded.get(nid, False)
                    self._build_tree(); self._apply_open_state()
                    return
                # altrimenti esegui azione foglia
                self._handle_leaf(n)

            btn = ttk.Button(rowf,
                             text=(("  " + full_text) if (self.is_open and has_icon) else (full_text if self.is_open else "")),
                             image=icon_img if icon_img else "",
                             compound="left" if icon_img else None,
                             style=("JSidebar.TButton" if not has_children else "JSidebar.Group.TButton"),
                             command=_on_click)
            btn.grid(row=0, column=1, sticky="ew", padx=(0, 6), pady=2)
            rowf.grid_columnconfigure(1, weight=1)

            # click sulla chevron: sempre toggle dei children
            if has_children:
                def _toggle(nid=node_id):
                    self._expanded[nid] = not self._expanded.get(nid, False)
                    self._build_tree(); self._apply_open_state()
                chev.bind("<Button-1>", lambda _e, nid=node_id: _toggle(nid))

            self._rows.append({
                "frame": rowf,
                "chev": chev,
                "button": btn,
                "full_text": full_text,
                "has_icon": has_icon
            })
            self._row_index += 1

            # ricorsione figli, se espanso
            if has_children:
                self._render_items(node["children"], depth+1, node_id, parent_expanded=self._expanded[node_id])

    def _handle_leaf(self, node):
        # 1) callback nominale
        name = node.get("command")
        if name and callable(self.callbacks.get(name)):
            self.callbacks[name]()  # esegui callback
        # 2) apertura frame nominale
        frame_name = node.get("frame")
        if frame_name and callable(self.page_loader):
            self.page_loader(frame_name)
        # close on select?
        if self.config_dict.get("appearance", {}).get("close_on_select", False):
            self.close()

    # --- icone (FA/immagine) ---
    def _create_icon_image(self, item):
        # Font Awesome char?
        fa = item.get("fa")
        if fa and _PIL_OK and self.fa_ttf_path and os.path.exists(self.fa_ttf_path):
            try:
                ch = fa.get("char") if isinstance(fa, dict) else None
                if ch:
                    size = max(12, int(self.icon_size))
                    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                    draw = ImageDraw.Draw(img)
                    font = ImageFont.truetype(self.fa_ttf_path, size)
                    w, h = draw.textbbox((0, 0), ch, font=font)[2:]
                    draw.text(((size - w) / 2, (size - h) / 2), ch, font=font, fill=self.icon_color)
                    tkimg = ImageTk.PhotoImage(img)
                    self._icons.append(tkimg)
                    return tkimg
            except Exception:
                pass
        # PNG/JPG
        icon_path = self._resolve_path(item.get("icon"))
        if icon_path and os.path.exists(icon_path):
            if _PIL_OK:
                try:
                    size = max(12, int(self.icon_size))
                    im = Image.open(icon_path).convert("RGBA")
                    im.thumbnail((size, size), Image.LANCZOS)
                    tkimg = ImageTk.PhotoImage(im)
                    self._icons.append(tkimg)
                    return tkimg
                except Exception:
                    pass
            try:
                tkimg = tk.PhotoImage(file=icon_path)
                self._icons.append(tkimg)
                return tkimg
            except Exception:
                return None
        return None
