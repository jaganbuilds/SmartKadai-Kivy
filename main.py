import os
import json
import csv
import hmac
import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from kivy.app import App
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.uix.spinner import Spinner
from kivy.uix.behaviors import ButtonBehavior
from kivy.graphics import Color, Rectangle, RoundedRectangle, Line, Ellipse

Window.size = (360, 640)
Window.clearcolor = (0.95, 0.97, 0.95, 1)

AUTH_FILE = Path(__file__).parent / "smartkadai_auth.json"
DB_PATH = Path(__file__).parent / "smartkadai.db"


def get_db_connection(db_path=None):
    """
    Establish a safe SQLite connection with foreign keys enforced and busy timeout configured.
    Respects runtime DB_PATH overrides for isolated testing.
    """
    target = db_path if db_path is not None else DB_PATH
    conn = sqlite3.connect(target)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn

# AI Forecasting Engine Integration (Strictly Read-Only)
from forecasting import SalesDataPreparation, ForecastEngine


def load_auth():
    if not AUTH_FILE.exists():
        return None
    try:
        data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            return None
        if not isinstance(data.get("salt"), str):
            return None
        if not isinstance(data.get("hash"), str):
            return None
        return data
    except (OSError, ValueError):
        return None


def make_hash(pin, salt_hex):
    salt = bytes.fromhex(salt_hex)
    return hashlib.pbkdf2_hmac(
        "sha256", pin.encode("utf-8"), salt, 600_000
    ).hex()


# -----------------------------------------------------------------------------
# DESIGN SYSTEM COLOR TOKENS
# -----------------------------------------------------------------------------
C_DEEP_EMERALD = (0.024, 0.306, 0.231, 1.0)  # #064E3B
C_EMERALD      = (0.020, 0.588, 0.412, 1.0)  # #059669
C_DARK_TEXT    = (0.063, 0.165, 0.133, 1.0)  # #102A22
C_SOFT_MINT    = (0.820, 0.980, 0.898, 1.0)  # #D1FAE5
C_PALE_SURFACE = (0.925, 0.992, 0.961, 1.0)  # #ECFDF5
C_MAIN_BG      = (0.957, 0.973, 0.961, 1.0)  # #F4F8F5
C_WHITE        = (1.0, 1.0, 1.0, 1.0)        # #FFFFFF
C_SEC_TEXT     = (0.392, 0.455, 0.545, 1.0)  # #64748B
C_DIVIDER      = (0.886, 0.910, 0.941, 1.0)  # #E2E8F0
C_WARNING      = (0.851, 0.467, 0.024, 1.0)  # #D97706
C_DANGER       = (0.863, 0.149, 0.149, 1.0)  # #DC2626
C_SUCCESS      = (0.082, 0.502, 0.239, 1.0)  # #15803D


# -----------------------------------------------------------------------------
# REUSABLE UI COMPONENTS
# -----------------------------------------------------------------------------
class RoundedCard(BoxLayout):
    """Reusable card with rounded corners and optional border."""
    def __init__(self, bg_color=C_WHITE, radius=dp(10), border_color=C_DIVIDER, border_width=dp(1), **kwargs):
        super().__init__(**kwargs)
        self.bg_color = bg_color
        self.radius_val = radius
        self.border_color = border_color
        self.border_width = border_width
        with self.canvas.before:
            self._bg_color_instr = Color(*self.bg_color)
            self._bg_rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius_val])
            if self.border_color:
                self._border_color_instr = Color(*self.border_color)
                self._border_line = Line(
                    rounded_rectangle=(self.x, self.y, self.width, self.height, self.radius_val),
                    width=self.border_width
                )
            else:
                self._border_line = None
        self.bind(pos=self._update_card, size=self._update_card)

    def _update_card(self, *args):
        self._bg_rect.pos = self.pos
        self._bg_rect.size = self.size
        if self._border_line:
            self._border_line.rounded_rectangle = (self.x, self.y, self.width, self.height, self.radius_val)


class StoreIconWidget(Widget):
    """Draws a clean, crisp retail storefront vector icon."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (None, None)
        self.size = (dp(34), dp(34))
        self.bind(pos=self._update, size=self._update)

    def _update(self, *args):
        self.canvas.clear()
        with self.canvas:
            # Soft mint circular badge
            Color(*C_SOFT_MINT)
            Ellipse(pos=self.pos, size=self.size)

            # Deep emerald storefront vector drawing
            Color(*C_DEEP_EMERALD)
            cx, cy = self.center_x, self.center_y
            
            # Store roof / awning triangle
            Line(points=[cx - dp(9), cy, cx, cy + dp(8), cx + dp(9), cy], width=dp(1.5), close=True)
            # Store body
            Line(rectangle=(cx - dp(7), cy - dp(8), dp(14), dp(8)), width=dp(1.3))
            # Store door
            Color(0.024, 0.306, 0.231, 0.85)
            Rectangle(pos=(cx - dp(2.5), cy - dp(8)), size=(dp(5), dp(5)))


class ActionCard(ButtonBehavior, BoxLayout):
    """Interactive card for Quick Actions with pressed visual feedback."""
    def __init__(self, title, subtitle, icon_text, is_primary=False, on_click=None, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.padding = [dp(8), dp(8), dp(8), dp(8)]
        self.spacing = dp(7)
        self.size_hint_y = None
        self.height = dp(80)
        self.is_primary = is_primary
        self.on_click_callback = on_click

        if self.is_primary:
            self.normal_bg = C_EMERALD
            self.down_bg = C_DEEP_EMERALD
            self.title_color = C_WHITE
            self.sub_color = C_SOFT_MINT
            self.badge_bg = (1.0, 1.0, 1.0, 0.22)
            self.badge_fg = C_WHITE
            self.border_col = None
        else:
            self.normal_bg = C_WHITE
            self.down_bg = C_PALE_SURFACE
            self.title_color = C_DARK_TEXT
            self.sub_color = C_SEC_TEXT
            self.badge_bg = C_PALE_SURFACE
            self.badge_fg = C_EMERALD
            self.border_col = C_DIVIDER

        with self.canvas.before:
            self._bg_col = Color(*self.normal_bg)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(10)])
            if self.border_col:
                self._border_col = Color(*self.border_col)
                self._line = Line(rounded_rectangle=(self.x, self.y, self.width, self.height, dp(10)), width=dp(1))
            else:
                self._line = None

        self.bind(pos=self._update_geom, size=self._update_geom)

        # Left Icon Badge
        badge = BoxLayout(size_hint=(None, None), size=(dp(28), dp(28)), pos_hint={"center_y": 0.5})
        with badge.canvas.before:
            Color(*self.badge_bg)
            self._badge_rect = RoundedRectangle(pos=badge.pos, size=badge.size, radius=[dp(8)])
        badge.bind(pos=lambda *a: setattr(self._badge_rect, "pos", badge.pos),
                   size=lambda *a: setattr(self._badge_rect, "size", badge.size))
        
        badge_lbl = Label(
            text=f"[b]{icon_text}[/b]",
            markup=True,
            font_size="12sp",
            color=self.badge_fg,
            halign="center",
            valign="middle"
        )
        badge_lbl.bind(size=badge_lbl.setter("text_size"))
        badge.add_widget(badge_lbl)
        self.add_widget(badge)

        # Text column
        text_col = BoxLayout(orientation="vertical", spacing=dp(2), pos_hint={"center_y": 0.5})
        title_font = "12.5sp" if len(title) > 9 else "13sp"
        title_lbl = Label(
            text=f"[b]{title}[/b]",
            markup=True,
            font_size=title_font,
            color=self.title_color,
            size_hint_y=None,
            height=dp(20),
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right"
        )
        title_lbl.bind(size=title_lbl.setter("text_size"))
        text_col.add_widget(title_lbl)

        sub_lbl = Label(
            text=subtitle,
            font_size="10sp",
            color=self.sub_color,
            size_hint_y=None,
            height=dp(30),
            halign="left",
            valign="top"
        )
        sub_lbl.bind(size=sub_lbl.setter("text_size"))
        text_col.add_widget(sub_lbl)
        self.add_widget(text_col)

        if self.on_click_callback:
            self.bind(on_release=lambda *a: self.on_click_callback())

    def on_state(self, instance, value):
        if value == "down":
            self._bg_col.rgba = self.down_bg
        else:
            self._bg_col.rgba = self.normal_bg

    def _update_geom(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size
        if self._line:
            self._line.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(10))


class ClickableRow(ButtonBehavior, BoxLayout):
    """Interactive row with hover/pressed feedback."""
    def __init__(self, on_click=None, **kwargs):
        super().__init__(**kwargs)
        self.on_click_callback = on_click
        with self.canvas.before:
            self._bg_col = Color(0, 0, 0, 0)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(6)])
        self.bind(pos=lambda *a: setattr(self._rect, "pos", self.pos),
                  size=lambda *a: setattr(self._rect, "size", self.size))
        if self.on_click_callback:
            self.bind(on_release=lambda *a: self.on_click_callback())

    def on_state(self, instance, value):
        if value == "down":
            self._bg_col.rgba = (0.02, 0.59, 0.41, 0.08)
        else:
            self._bg_col.rgba = (0, 0, 0, 0)


class ForecastBanner(ButtonBehavior, BoxLayout):
    """Slim, interactive banner for AI Sales Forecast on Dashboard."""
    def __init__(self, on_click=None, **kwargs):
        kwargs.setdefault("orientation", "horizontal")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(52))
        kwargs.setdefault("padding", [dp(12), dp(8), dp(12), dp(8)])
        kwargs.setdefault("spacing", dp(10))
        super().__init__(**kwargs)
        self.on_click_callback = on_click

        self.normal_bg = (0.925, 0.992, 0.961, 1.0)  # C_PALE_SURFACE
        self.down_bg = (0.820, 0.980, 0.898, 1.0)    # C_SOFT_MINT
        self.border_col = (0.65, 0.88, 0.76, 1.0)

        with self.canvas.before:
            self._bg_col = Color(*self.normal_bg)
            self._rect = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(10)])
            self._border_col = Color(*self.border_col)
            self._line = Line(rounded_rectangle=(self.x, self.y, self.width, self.height, dp(10)), width=dp(1))

        self.bind(pos=self._update_geom, size=self._update_geom)

        # Left AI badge
        badge = BoxLayout(size_hint=(None, None), size=(dp(34), dp(34)), pos_hint={"center_y": 0.5})
        with badge.canvas.before:
            Color(*C_DEEP_EMERALD)
            self._badge_rect = RoundedRectangle(pos=badge.pos, size=badge.size, radius=[dp(8)])
        badge.bind(
            pos=lambda *a: setattr(self._badge_rect, "pos", badge.pos),
            size=lambda *a: setattr(self._badge_rect, "size", badge.size)
        )
        b_lbl = Label(text="[b]AI[/b]", markup=True, font_size="11.5sp", color=C_WHITE, halign="center", valign="middle")
        b_lbl.bind(size=b_lbl.setter("text_size"))
        badge.add_widget(b_lbl)
        self.add_widget(badge)

        # Middle descriptive text
        text_col = BoxLayout(orientation="vertical", spacing=dp(1), pos_hint={"center_y": 0.5})
        title_lbl = Label(
            text="[b]AI Sales Forecast & Runway Analysis[/b]",
            markup=True,
            font_size="12.5sp",
            color=C_DEEP_EMERALD,
            size_hint_y=None,
            height=dp(18),
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right"
        )
        title_lbl.bind(size=title_lbl.setter("text_size"))
        text_col.add_widget(title_lbl)

        sub_lbl = Label(
            text="Predict demand, stockout runway & reorder requirements",
            font_size="10sp",
            color=C_SEC_TEXT,
            size_hint_y=None,
            height=dp(16),
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right"
        )
        sub_lbl.bind(size=sub_lbl.setter("text_size"))
        text_col.add_widget(sub_lbl)
        self.add_widget(text_col)

        # Right view action
        right_btn = Label(
            text="[b]View ->[/b]",
            markup=True,
            font_size="11.5sp",
            color=C_EMERALD,
            size_hint=(None, None),
            size=(dp(58), dp(26)),
            pos_hint={"center_y": 0.5},
            halign="right",
            valign="middle"
        )
        right_btn.bind(size=right_btn.setter("text_size"))
        self.add_widget(right_btn)

        if self.on_click_callback:
            self.bind(on_release=lambda *a: self.on_click_callback())

    def on_state(self, instance, value):
        if value == "down":
            self._bg_col.rgba = self.down_bg
        else:
            self._bg_col.rgba = self.normal_bg

    def _update_geom(self, *args):
        self._rect.pos = self.pos
        self._rect.size = self.size
        self._line.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(10))


class StyledInput(TextInput):
    """Clean, consistent text input field."""
    def __init__(self, **kwargs):
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_active", "")
        kwargs.setdefault("background_color", C_WHITE)
        kwargs.setdefault("foreground_color", C_DARK_TEXT)
        kwargs.setdefault("cursor_color", C_EMERALD)
        kwargs.setdefault("padding", [dp(10), dp(10), dp(10), dp(10)])
        kwargs.setdefault("font_size", "14sp")
        kwargs.setdefault("multiline", False)
        super().__init__(**kwargs)


class PrimaryButton(Button):
    """Emerald filled button for primary actions."""
    def __init__(self, **kwargs):
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", C_EMERALD)
        kwargs.setdefault("color", C_WHITE)
        kwargs.setdefault("font_size", "13sp")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(40))
        super().__init__(**kwargs)


class SecondaryButton(Button):
    """Clean neutral button for secondary actions."""
    def __init__(self, **kwargs):
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", (0.92, 0.94, 0.96, 1.0))
        kwargs.setdefault("color", C_DARK_TEXT)
        kwargs.setdefault("font_size", "12sp")
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(34))
        super().__init__(**kwargs)


def make_screen_header(title, subtitle, on_back):
    """Consistent Deep Emerald top header with back navigation."""
    header = BoxLayout(
        orientation="horizontal",
        size_hint_y=None,
        height=dp(64),
        padding=[dp(14), dp(10), dp(14), dp(10)],
        spacing=dp(10)
    )
    with header.canvas.before:
        Color(*C_DEEP_EMERALD)
        h_bg = Rectangle(pos=header.pos, size=header.size)
    header.bind(
        pos=lambda inst, val: setattr(h_bg, "pos", val),
        size=lambda inst, val: setattr(h_bg, "size", val)
    )

    header.add_widget(StoreIconWidget())

    title_col = BoxLayout(orientation="vertical", spacing=dp(2), pos_hint={"center_y": 0.5})
    t_lbl = Label(
        text=f"[b]{title}[/b]",
        markup=True,
        font_size="15.5sp",
        color=C_WHITE,
        size_hint_y=None,
        height=dp(22),
        halign="left",
        valign="middle",
        shorten=True,
        shorten_from="right"
    )
    t_lbl.bind(size=t_lbl.setter("text_size"))
    title_col.add_widget(t_lbl)

    s_lbl = Label(
        text=subtitle,
        font_size="10.5sp",
        color=C_SOFT_MINT,
        size_hint_y=None,
        height=dp(16),
        halign="left",
        valign="middle",
        shorten=True,
        shorten_from="right"
    )
    s_lbl.bind(size=s_lbl.setter("text_size"))
    title_col.add_widget(s_lbl)
    header.add_widget(title_col)

    back_btn = Button(
        text="< Dashboard",
        size_hint=(None, None),
        size=(dp(90), dp(32)),
        pos_hint={"center_y": 0.5},
        background_normal="",
        background_color=(0.10, 0.45, 0.30, 1.0),
        color=C_WHITE,
        font_size="11sp"
    )
    back_btn.bind(on_release=lambda *a: on_back())
    header.add_widget(back_btn)
    return header


# -----------------------------------------------------------------------------
# READ-ONLY SQLITE DATA QUERY HELPER
# -----------------------------------------------------------------------------
def fetch_dashboard_data(db_path):
    """Safely query read-only dashboard metrics from SQLite."""
    data = {
        "today_sales": 0.0,
        "today_bills": 0,
        "total_products": 0,
        "low_stock_count": 0,
        "recent_sales": [],
        "low_stock_items": [],
        "error": None
    }
    today_str = datetime.now().strftime("%Y-%m-%d")

    try:
        with get_db_connection(db_path) as conn:
            # 1. Today's sales (sum of quantity_sold * selling_price for current local date)
            row = conn.execute(
                "SELECT COALESCE(SUM(quantity_sold * selling_price), 0.0) FROM sales WHERE date = ?",
                (today_str,)
            ).fetchone()
            data["today_sales"] = float(row[0]) if row and row[0] is not None else 0.0

            # 2. Bills today (unique bill count for current local date)
            row = conn.execute(
                "SELECT COUNT(DISTINCT COALESCE(bill_id, CAST(sale_id AS TEXT))) FROM sales WHERE date = ?",
                (today_str,)
            ).fetchone()
            data["today_bills"] = int(row[0]) if row and row[0] is not None else 0

            # 3. Total products in catalog
            row = conn.execute("SELECT COUNT(*) FROM products").fetchone()
            data["total_products"] = int(row[0]) if row and row[0] is not None else 0

            # 4. Low stock items count (current_stock <= safety_stock)
            row = conn.execute(
                "SELECT COUNT(*) FROM products WHERE current_stock <= safety_stock"
            ).fetchone()
            data["low_stock_count"] = int(row[0]) if row and row[0] is not None else 0

            # 5. Recent 5 sales transactions
            sales_rows = conn.execute("""
                SELECT
                    s.sale_id,
                    COALESCE(s.bill_id, 'Bill #' || s.sale_id) AS bill_ref,
                    COALESCE(p.product_name, 'Unknown Product') AS product_name,
                    s.quantity_sold,
                    s.selling_price,
                    (s.quantity_sold * s.selling_price) AS line_total,
                    COALESCE(s.timestamp, s.date) AS tx_time
                FROM sales s
                LEFT JOIN products p ON s.product_id = p.product_id
                ORDER BY s.sale_id DESC
                LIMIT 5
            """).fetchall()
            data["recent_sales"] = sales_rows

            # 6. Low stock products (up to 5)
            low_rows = conn.execute("""
                SELECT product_id, product_name, current_stock, safety_stock
                FROM products
                WHERE current_stock <= safety_stock
                ORDER BY current_stock ASC
                LIMIT 5
            """).fetchall()
            data["low_stock_items"] = low_rows

    except Exception as exc:
        data["error"] = str(exc)

    return data

class SmartKadaiApp(App):
    def apply_emerald_background(self, screen):
        from kivy.graphics import Color, Rectangle

        with screen.canvas.before:
            Color(0.02, 0.40, 0.25, 1)
            bg = Rectangle(pos=screen.pos, size=screen.size)

        screen.bind(
            pos=lambda instance, value: setattr(bg, "pos", value),
            size=lambda instance, value: setattr(bg, "size", value)
        )
    def build(self):
        self.auth = load_auth()
        self.setup_mode = self.auth is None
        self.cached_forecast_report = None
        self.show_login()
        return self.root

    def invalidate_forecast_cache(self):
        """Invalidate the in-memory AI sales forecast cache."""
        self.cached_forecast_report = None

    def show_login(self):
        root = BoxLayout(
            orientation="vertical",
            padding=dp(28),
            spacing=dp(16)
        )

        root.add_widget(Label(
            text="[b]SmartKadai[/b]",
            markup=True,
            font_size="32sp",
            color=(0.08, 0.35, 0.22, 1),
            size_hint_y=None,
            height=dp(70)
        ))

        heading = (
            "Create your 4–6 digit PIN"
            if self.setup_mode else "Enter your PIN"
        )
        root.add_widget(Label(
            text=heading,
            color=(0.18, 0.25, 0.20, 1),
            size_hint_y=None,
            height=dp(40)
        ))

        self.pin = TextInput(
            hint_text="4–6 digit PIN",
            password=True,
            multiline=False,
            input_filter="int",
            size_hint_y=None,
            height=dp(52),
            font_size="18sp"
        )
        root.add_widget(self.pin)

        self.confirm_pin = None
        if self.setup_mode:
            self.confirm_pin = TextInput(
                hint_text="Confirm PIN",
                password=True,
                multiline=False,
                input_filter="int",
                size_hint_y=None,
                height=dp(52),
                font_size="18sp"
            )
            root.add_widget(self.confirm_pin)

        button = Button(
            text="Create PIN" if self.setup_mode else "Login",
            size_hint_y=None,
            height=dp(52),
            background_normal="",
            background_color=(0.08, 0.45, 0.27, 1)
        )
        button.bind(on_press=self.submit_pin)
        root.add_widget(button)

        root.add_widget(Label(text="Offline shop management"))
        if hasattr(self, "root") and self.root is not None:
            self.root.clear_widgets()
            self.root.add_widget(root)
        else:
            self.root = root

    def message(self, title, text):
        Popup(
            title=title,
            content=Label(text=text),
            size_hint=(0.85, 0.3)
        ).open()

    def submit_pin(self, instance):
        pin = self.pin.text

        if not (pin.isdigit() and 4 <= len(pin) <= 6):
            self.message("Invalid PIN", "Enter 4 to 6 digits.")
            return

        if self.setup_mode:
            if self.confirm_pin.text != pin:
                self.message("PIN mismatch", "Both PINs must match.")
                return

            salt = secrets.token_bytes(16).hex()
            data = {
                "version": 1,
                "salt": salt,
                "hash": make_hash(pin, salt)
            }

            try:
                with AUTH_FILE.open("x", encoding="utf-8") as file:
                    json.dump(data, file)
                os.chmod(AUTH_FILE, 0o600)
            except FileExistsError:
                self.message(
                    "Setup changed",
                    "Restart the app and try logging in."
                )
                return
            except OSError:
                self.message(
                    "Save failed",
                    "Could not save PIN. Check folder permissions."
                )
                return

            self.message(
                "PIN created",
                "PIN saved locally. Restart the app to log in."
            )
            return

        try:
            actual = make_hash(pin, self.auth["salt"])
        except (ValueError, TypeError, KeyError):
            self.message("Login error", "Stored PIN data is invalid.")
            return

        if hmac.compare_digest(actual, self.auth["hash"]):
            self.show_dashboard()
        else:
            self.pin.text = ""
            self.message("Login failed", "Incorrect PIN. Try again.")

    def show_dashboard(self):
        data = fetch_dashboard_data(DB_PATH)

        # Root layout with Main Background
        root = BoxLayout(orientation="vertical")
        with root.canvas.before:
            Color(*C_MAIN_BG)
            bg_rect = Rectangle(pos=root.pos, size=root.size)
        root.bind(
            pos=lambda inst, val: setattr(bg_rect, "pos", val),
            size=lambda inst, val: setattr(bg_rect, "size", val)
        )

        # -------------------------------------------------------------
        # A. TOP BRAND HEADER (Deep Emerald)
        # -------------------------------------------------------------
        header = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(116),
            padding=[dp(16), dp(10), dp(16), dp(10)],
            spacing=dp(6)
        )
        with header.canvas.before:
            Color(*C_DEEP_EMERALD)
            header_bg = Rectangle(pos=header.pos, size=header.size)
        header.bind(
            pos=lambda inst, val: setattr(header_bg, "pos", val),
            size=lambda inst, val: setattr(header_bg, "size", val)
        )

        # Top Bar: Store Icon + Brand + Logout
        top_bar = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(10))
        top_bar.add_widget(StoreIconWidget())

        brand_col = BoxLayout(orientation="vertical", spacing=dp(1), pos_hint={"center_y": 0.5})
        brand_name = Label(
            text="[b]SmartKadai[/b]",
            markup=True,
            font_size="20sp",
            color=C_WHITE,
            size_hint_y=None,
            height=dp(24),
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right"
        )
        brand_name.bind(size=brand_name.setter("text_size"))
        brand_col.add_widget(brand_name)

        subtitle_lbl = Label(
            text="Smart Retail Management",
            font_size="11sp",
            color=C_SOFT_MINT,
            size_hint_y=None,
            height=dp(16),
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right"
        )
        subtitle_lbl.bind(size=subtitle_lbl.setter("text_size"))
        brand_col.add_widget(subtitle_lbl)
        top_bar.add_widget(brand_col)

        # Logout Button
        logout_btn = Button(
            text="Logout",
            size_hint=(None, None),
            size=(dp(68), dp(32)),
            pos_hint={"center_y": 0.5},
            background_normal="",
            background_color=(0.10, 0.45, 0.30, 1.0),
            color=C_WHITE,
            font_size="12sp"
        )
        logout_btn.bind(on_press=self.logout)
        top_bar.add_widget(logout_btn)
        header.add_widget(top_bar)

        # Bottom Bar: Welcome message + Date + Offline Ready Badge
        bottom_bar = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
        
        now_dt = datetime.now()
        date_display = now_dt.strftime("%A, %d %b %Y")
        welcome_col = BoxLayout(orientation="vertical", spacing=dp(1), pos_hint={"center_y": 0.5})
        welcome_lbl = Label(
            text="Welcome back!",
            font_size="12sp",
            color=C_WHITE,
            size_hint_y=None,
            height=dp(18),
            halign="left",
            valign="middle"
        )
        welcome_lbl.bind(size=welcome_lbl.setter("text_size"))
        welcome_col.add_widget(welcome_lbl)

        date_lbl = Label(
            text=date_display,
            font_size="10.5sp",
            color=C_SOFT_MINT,
            size_hint_y=None,
            height=dp(16),
            halign="left",
            valign="middle",
            shorten=True,
            shorten_from="right"
        )
        date_lbl.bind(size=date_lbl.setter("text_size"))
        welcome_col.add_widget(date_lbl)
        bottom_bar.add_widget(welcome_col)

        # Offline Ready Badge
        offline_badge = BoxLayout(
            size_hint=(None, None),
            size=(dp(96), dp(24)),
            pos_hint={"center_y": 0.5},
            padding=[dp(7), dp(2)],
            spacing=dp(5)
        )
        with offline_badge.canvas.before:
            Color(0.0, 0.0, 0.0, 0.22)
            off_rect = RoundedRectangle(pos=offline_badge.pos, size=offline_badge.size, radius=[dp(12)])
        offline_badge.bind(
            pos=lambda inst, val: setattr(off_rect, "pos", val),
            size=lambda inst, val: setattr(off_rect, "size", val)
        )

        # Green indicator dot
        dot_box = Widget(size_hint=(None, None), size=(dp(6), dp(6)), pos_hint={"center_y": 0.5})
        with dot_box.canvas:
            Color(0.25, 0.95, 0.55, 1.0)
            dot_shape = Ellipse(pos=dot_box.pos, size=dot_box.size)
        dot_box.bind(
            pos=lambda inst, val: setattr(dot_shape, "pos", val),
            size=lambda inst, val: setattr(dot_shape, "size", val)
        )
        offline_badge.add_widget(dot_box)

        off_lbl = Label(
            text="Offline Ready",
            font_size="10sp",
            color=C_SOFT_MINT,
            halign="left",
            valign="middle"
        )
        off_lbl.bind(size=off_lbl.setter("text_size"))
        offline_badge.add_widget(off_lbl)
        bottom_bar.add_widget(offline_badge)

        header.add_widget(bottom_bar)
        root.add_widget(header)

        # -------------------------------------------------------------
        # SCROLLABLE CONTENT BODY
        # -------------------------------------------------------------
        scroll = ScrollView(
            do_scroll_x=False,
            do_scroll_y=True,
            bar_width=dp(4),
            bar_color=(0.02, 0.59, 0.41, 0.6),
            bar_inactive_color=(0.8, 0.8, 0.8, 0.3)
        )
        content = BoxLayout(
            orientation="vertical",
            spacing=dp(16),
            padding=[dp(14), dp(14), dp(14), dp(24)],
            size_hint_y=None
        )
        content.bind(minimum_height=content.setter("height"))

        # Database Error Warning Notice (safe error handling)
        if data["error"]:
            err_card = RoundedCard(
                bg_color=(1.0, 0.95, 0.95, 1.0),
                border_color=C_DANGER,
                size_hint_y=None,
                height=dp(50),
                padding=dp(8)
            )
            err_card.add_widget(Label(
                text=f"[b]Database Notice:[/b] {data['error']}",
                markup=True,
                color=C_DANGER,
                font_size="11sp"
            ))
            content.add_widget(err_card)

        # -------------------------------------------------------------
        # B. TODAY'S BUSINESS SUMMARY ("Today's Overview")
        # -------------------------------------------------------------
        sec_overview = BoxLayout(size_hint_y=None, height=dp(24))
        overview_title = Label(
            text="[b]Today's Overview[/b]",
            markup=True,
            font_size="16sp",
            color=C_DARK_TEXT,
            halign="left",
            valign="middle"
        )
        overview_title.bind(size=overview_title.setter("text_size"))
        sec_overview.add_widget(overview_title)
        content.add_widget(sec_overview)

        metrics_grid = GridLayout(cols=2, spacing=dp(10), size_hint_y=None, height=dp(204))

        def make_metric_card(title_text, val_text, sub_text, val_color=C_DARK_TEXT, badge_text=""):
            card = RoundedCard(
                bg_color=C_WHITE,
                radius=dp(10),
                border_color=C_DIVIDER,
                orientation="vertical",
                padding=[dp(12), dp(9), dp(12), dp(9)],
                spacing=dp(2)
            )
            
            top_r = BoxLayout(size_hint_y=None, height=dp(18), spacing=dp(4))
            t_lbl = Label(
                text=title_text,
                font_size="10sp",
                color=C_SEC_TEXT,
                halign="left",
                valign="middle",
                shorten=True,
                shorten_from="right"
            )
            t_lbl.bind(size=t_lbl.setter("text_size"))
            top_r.add_widget(t_lbl)

            if badge_text:
                b_lbl = Label(
                    text=badge_text,
                    font_size="10sp",
                    color=C_EMERALD,
                    size_hint_x=None,
                    width=dp(22),
                    halign="right",
                    valign="middle"
                )
                b_lbl.bind(size=b_lbl.setter("text_size"))
                top_r.add_widget(b_lbl)
            card.add_widget(top_r)

            # Responsive font size for metric value: dynamically adapt based on digits length
            v_len = len(val_text)
            if v_len > 11:
                v_font_size = "14.5sp"
            elif v_len > 8:
                v_font_size = "16sp"
            else:
                v_font_size = "18sp"

            v_lbl = Label(
                text=f"[b]{val_text}[/b]",
                markup=True,
                font_size=v_font_size,
                color=val_color,
                size_hint_y=None,
                height=dp(32),
                halign="left",
                valign="middle"
            )
            v_lbl.bind(size=v_lbl.setter("text_size"))
            card.add_widget(v_lbl)

            s_lbl = Label(
                text=sub_text,
                font_size="10.5sp",
                color=C_SEC_TEXT,
                size_hint_y=None,
                height=dp(18),
                halign="left",
                valign="middle",
                shorten=True,
                shorten_from="right"
            )
            s_lbl.bind(size=s_lbl.setter("text_size"))
            card.add_widget(s_lbl)
            return card

        # Metric 1: Today's Sales
        sales_str = f"₹{data['today_sales']:,.2f}"
        metrics_grid.add_widget(make_metric_card("TODAY'S SALES", sales_str, "Gross revenue", C_DARK_TEXT, "₹"))

        # Metric 2: Bills Today
        bills_str = str(data["today_bills"])
        metrics_grid.add_widget(make_metric_card("BILLS TODAY", bills_str, "Completed bills", C_DARK_TEXT, "#"))

        # Metric 3: Total Products
        prod_str = str(data["total_products"])
        metrics_grid.add_widget(make_metric_card("TOTAL PRODUCTS", prod_str, "In catalog", C_DARK_TEXT, "PKG"))

        # Metric 4: Low Stock Items
        low_count = data["low_stock_count"]
        low_color = C_WARNING if low_count > 0 else C_SUCCESS
        low_sub = f"{low_count} items to reorder" if low_count > 0 else "All stocks healthy"
        metrics_grid.add_widget(make_metric_card("LOW STOCK", str(low_count), low_sub, low_color, "!"))

        content.add_widget(metrics_grid)

        # -------------------------------------------------------------
        # C. QUICK ACTIONS
        # -------------------------------------------------------------
        sec_actions = BoxLayout(size_hint_y=None, height=dp(24))
        actions_title = Label(
            text="[b]Quick Actions[/b]",
            markup=True,
            font_size="16sp",
            color=C_DARK_TEXT,
            halign="left",
            valign="middle"
        )
        actions_title.bind(size=actions_title.setter("text_size"))
        sec_actions.add_widget(actions_title)
        content.add_widget(sec_actions)

        actions_grid = GridLayout(cols=2, spacing=dp(10), size_hint_y=None, height=dp(170))
        actions_grid.add_widget(ActionCard(
            title="New Bill",
            subtitle="Create customer bill",
            icon_text="+",
            is_primary=True,
            on_click=lambda: self.open_section("Billing")
        ))
        actions_grid.add_widget(ActionCard(
            title="Products",
            subtitle="Catalog & prices",
            icon_text="::",
            is_primary=False,
            on_click=lambda: self.open_section("Products")
        ))
        actions_grid.add_widget(ActionCard(
            title="Manage Stock",
            subtitle="Add incoming stock",
            icon_text="^",
            is_primary=False,
            on_click=lambda: self.open_section("Stock Management")
        ))
        actions_grid.add_widget(ActionCard(
            title="Sales Report",
            subtitle="Sales & receipts",
            icon_text="%",
            is_primary=False,
            on_click=lambda: self.open_section("Sales Report")
        ))
        content.add_widget(actions_grid)

        # AI Sales Forecast Banner (Slim, Clickable)
        forecast_banner = ForecastBanner(on_click=lambda: self.open_section("AI Sales Forecast"))
        content.add_widget(forecast_banner)

        # -------------------------------------------------------------
        # D. RECENT SALES
        # -------------------------------------------------------------
        sec_sales_hdr = BoxLayout(size_hint_y=None, height=dp(24))
        sales_title = Label(
            text="[b]Recent Sales[/b]",
            markup=True,
            font_size="16sp",
            color=C_DARK_TEXT,
            halign="left",
            valign="middle"
        )
        sales_title.bind(size=sales_title.setter("text_size"))
        sec_sales_hdr.add_widget(sales_title)

        sales_sub_lbl = Label(
            text="Latest transactions",
            font_size="11.5sp",
            color=C_SEC_TEXT,
            size_hint_x=None,
            width=dp(120),
            halign="right",
            valign="middle"
        )
        sales_sub_lbl.bind(size=sales_sub_lbl.setter("text_size"))
        sec_sales_hdr.add_widget(sales_sub_lbl)
        content.add_widget(sec_sales_hdr)

        recent_sales = data["recent_sales"]
        if recent_sales:
            sales_card = RoundedCard(
                bg_color=C_WHITE,
                radius=dp(10),
                border_color=C_DIVIDER,
                orientation="vertical",
                padding=[dp(12), dp(10), dp(12), dp(10)],
                spacing=dp(6),
                size_hint_y=None
            )
            sales_card.bind(minimum_height=sales_card.setter("height"))

            for i, item in enumerate(recent_sales):
                sale_id, bill_ref, prod_name, qty, price, total_amt, tx_time = item
                
                # Format bill reference cleanly
                if bill_ref and str(bill_ref).startswith("SK-"):
                    short_bill = "SK-" + str(bill_ref)[-6:]
                else:
                    short_bill = str(bill_ref or f"Bill #{sale_id}")
                
                # Format time string cleanly
                time_raw = str(tx_time).replace("T", " ")
                if len(time_raw) >= 16:
                    try:
                        dt_obj = datetime.fromisoformat(time_raw[:16])
                        time_str = dt_obj.strftime("%d %b, %H:%M")
                    except Exception:
                        time_str = time_raw[5:16]
                else:
                    time_str = time_raw

                row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52), spacing=dp(8))
                
                left_col = BoxLayout(orientation="vertical", spacing=dp(2), pos_hint={"center_y": 0.5})
                p_name_lbl = Label(
                    text=f"[b]{prod_name}[/b]",
                    markup=True,
                    font_size="13sp",
                    color=C_DARK_TEXT,
                    size_hint_y=None,
                    height=dp(22),
                    halign="left",
                    valign="middle",
                    shorten=True,
                    shorten_from="right"
                )
                p_name_lbl.bind(size=p_name_lbl.setter("text_size"))
                left_col.add_widget(p_name_lbl)

                meta_lbl = Label(
                    text=f"{short_bill} • Qty: {qty} • {time_str}",
                    font_size="10.5sp",
                    color=C_SEC_TEXT,
                    size_hint_y=None,
                    height=dp(18),
                    halign="left",
                    valign="middle",
                    shorten=True,
                    shorten_from="right"
                )
                meta_lbl.bind(size=meta_lbl.setter("text_size"))
                left_col.add_widget(meta_lbl)
                row.add_widget(left_col)

                right_col = BoxLayout(orientation="vertical", size_hint_x=None, width=dp(98), spacing=dp(2), pos_hint={"center_y": 0.5})
                amt_lbl = Label(
                    text=f"[b]₹{total_amt:,.2f}[/b]",
                    markup=True,
                    font_size="13sp",
                    color=C_EMERALD,
                    size_hint_y=None,
                    height=dp(22),
                    halign="right",
                    valign="middle",
                    shorten=True,
                    shorten_from="right"
                )
                amt_lbl.bind(size=amt_lbl.setter("text_size"))
                right_col.add_widget(amt_lbl)

                unit_lbl = Label(
                    text=f"@ ₹{price:.2f}",
                    font_size="10.5sp",
                    color=C_SEC_TEXT,
                    size_hint_y=None,
                    height=dp(16),
                    halign="right",
                    valign="middle"
                )
                unit_lbl.bind(size=unit_lbl.setter("text_size"))
                right_col.add_widget(unit_lbl)
                row.add_widget(right_col)

                sales_card.add_widget(row)

                if i < len(recent_sales) - 1:
                    divider = Widget(size_hint_y=None, height=dp(1))
                    with divider.canvas:
                        Color(*C_DIVIDER)
                        div_rect = Rectangle(pos=divider.pos, size=(divider.width, dp(1)))
                    divider.bind(
                        pos=lambda inst, val, r=div_rect, d=divider: setattr(r, "pos", val),
                        size=lambda inst, val, r=div_rect, d=divider: setattr(r, "size", (d.width, dp(1)))
                    )
                    sales_card.add_widget(divider)

            content.add_widget(sales_card)
        else:
            empty_card = RoundedCard(
                bg_color=C_WHITE,
                radius=dp(10),
                border_color=C_DIVIDER,
                orientation="vertical",
                padding=[dp(16), dp(20), dp(16), dp(20)],
                spacing=dp(4),
                size_hint_y=None,
                height=dp(86)
            )
            empty_title = Label(
                text="[b]No sales yet[/b]",
                markup=True,
                font_size="13.5sp",
                color=C_SEC_TEXT,
                size_hint_y=None,
                height=dp(20),
                halign="center",
                valign="middle"
            )
            empty_title.bind(size=empty_title.setter("text_size"))
            empty_card.add_widget(empty_title)

            empty_sub = Label(
                text="Your completed bills will appear here.",
                font_size="11.5sp",
                color=C_SEC_TEXT,
                size_hint_y=None,
                height=dp(18),
                halign="center",
                valign="middle"
            )
            empty_sub.bind(size=empty_sub.setter("text_size"))
            empty_card.add_widget(empty_sub)
            content.add_widget(empty_card)

        # -------------------------------------------------------------
        # E. STOCK ALERTS
        # -------------------------------------------------------------
        sec_stock_hdr = BoxLayout(size_hint_y=None, height=dp(24))
        stock_title = Label(
            text="[b]Stock Alerts[/b]",
            markup=True,
            font_size="16sp",
            color=C_DARK_TEXT,
            halign="left",
            valign="middle"
        )
        stock_title.bind(size=stock_title.setter("text_size"))
        sec_stock_hdr.add_widget(stock_title)

        stock_sub_lbl = Label(
            text="Safety threshold watch",
            font_size="11.5sp",
            color=C_SEC_TEXT,
            size_hint_x=None,
            width=dp(140),
            halign="right",
            valign="middle"
        )
        stock_sub_lbl.bind(size=stock_sub_lbl.setter("text_size"))
        sec_stock_hdr.add_widget(stock_sub_lbl)
        content.add_widget(sec_stock_hdr)

        low_stock_items = data["low_stock_items"]
        if low_stock_items:
            stock_card = RoundedCard(
                bg_color=C_WHITE,
                radius=dp(10),
                border_color=C_DIVIDER,
                orientation="vertical",
                padding=[dp(12), dp(10), dp(12), dp(10)],
                spacing=dp(6),
                size_hint_y=None
            )
            stock_card.bind(minimum_height=stock_card.setter("height"))

            for i, p in enumerate(low_stock_items):
                pid, pname, cstock, sstock = p
                is_out = cstock <= 0
                badge_bg = (0.98, 0.90, 0.90, 1.0) if is_out else (1.0, 0.96, 0.88, 1.0)
                badge_fg = C_DANGER if is_out else C_WARNING
                badge_txt = "OUT OF STOCK" if is_out else "LOW STOCK"

                row_wrap = ClickableRow(
                    on_click=lambda: self.open_section("Stock Management"),
                    size_hint_y=None,
                    height=dp(52)
                )
                row_box = BoxLayout(orientation="horizontal", spacing=dp(8), padding=[dp(4), 0, dp(4), 0])
                
                left_col = BoxLayout(orientation="vertical", spacing=dp(2), pos_hint={"center_y": 0.5})
                pn_lbl = Label(
                    text=f"[b]{pname}[/b]",
                    markup=True,
                    font_size="13sp",
                    color=C_DARK_TEXT,
                    size_hint_y=None,
                    height=dp(22),
                    halign="left",
                    valign="middle",
                    shorten=True,
                    shorten_from="right"
                )
                pn_lbl.bind(size=pn_lbl.setter("text_size"))
                left_col.add_widget(pn_lbl)

                thresh_lbl = Label(
                    text=f"Stock: {cstock} • Min: {sstock}",
                    font_size="10.5sp",
                    color=C_SEC_TEXT,
                    size_hint_y=None,
                    height=dp(18),
                    halign="left",
                    valign="middle",
                    shorten=True,
                    shorten_from="right"
                )
                thresh_lbl.bind(size=thresh_lbl.setter("text_size"))
                left_col.add_widget(thresh_lbl)
                row_box.add_widget(left_col)

                badge_box = BoxLayout(size_hint=(None, None), size=(dp(94), dp(24)), pos_hint={"center_y": 0.5})
                with badge_box.canvas.before:
                    Color(*badge_bg)
                    b_rect = RoundedRectangle(pos=badge_box.pos, size=badge_box.size, radius=[dp(6)])
                badge_box.bind(
                    pos=lambda inst, val, r=b_rect: setattr(r, "pos", val),
                    size=lambda inst, val, r=b_rect: setattr(r, "size", val)
                )
                
                b_lbl = Label(
                    text=f"[b]{badge_txt}[/b]",
                    markup=True,
                    font_size="9.5sp",
                    color=badge_fg,
                    halign="center",
                    valign="middle"
                )
                b_lbl.bind(size=b_lbl.setter("text_size"))
                badge_box.add_widget(b_lbl)
                row_box.add_widget(badge_box)

                row_wrap.add_widget(row_box)
                stock_card.add_widget(row_wrap)

                if i < len(low_stock_items) - 1:
                    divider = Widget(size_hint_y=None, height=dp(1))
                    with divider.canvas:
                        Color(*C_DIVIDER)
                        div_rect = Rectangle(pos=divider.pos, size=(divider.width, dp(1)))
                    divider.bind(
                        pos=lambda inst, val, r=div_rect, d=divider: setattr(r, "pos", val),
                        size=lambda inst, val, r=div_rect, d=divider: setattr(r, "size", (d.width, dp(1)))
                    )
                    stock_card.add_widget(divider)

            content.add_widget(stock_card)
        else:
            good_card = RoundedCard(
                bg_color=C_PALE_SURFACE,
                radius=dp(10),
                border_color=C_SOFT_MINT,
                orientation="horizontal",
                padding=[dp(12), dp(10), dp(12), dp(10)],
                spacing=dp(10),
                size_hint_y=None,
                height=dp(76)
            )
            chk_badge = BoxLayout(size_hint=(None, None), size=(dp(28), dp(28)), pos_hint={"center_y": 0.5})
            with chk_badge.canvas.before:
                Color(*C_SOFT_MINT)
                chk_rect = RoundedRectangle(pos=chk_badge.pos, size=chk_badge.size, radius=[dp(14)])
            chk_badge.bind(
                pos=lambda inst, val, r=chk_rect: setattr(r, "pos", val),
                size=lambda inst, val, r=chk_rect: setattr(r, "size", val)
            )
            chk_lbl = Label(text="[b]OK[/b]", markup=True, font_size="10sp", color=C_SUCCESS, halign="center", valign="middle")
            chk_lbl.bind(size=chk_lbl.setter("text_size"))
            chk_badge.add_widget(chk_lbl)
            good_card.add_widget(chk_badge)

            good_col = BoxLayout(orientation="vertical", spacing=dp(2), pos_hint={"center_y": 0.5})
            good_title = Label(
                text="[b]All stock levels look good.[/b]",
                markup=True,
                font_size="13sp",
                color=C_SUCCESS,
                size_hint_y=None,
                height=dp(20),
                halign="left",
                valign="middle"
            )
            good_title.bind(size=good_title.setter("text_size"))
            good_col.add_widget(good_title)

            good_sub = Label(
                text="All inventory is currently above required safety thresholds.",
                font_size="10.5sp",
                color=C_SEC_TEXT,
                size_hint_y=None,
                height=dp(34),
                halign="left",
                valign="top"
            )
            good_sub.bind(size=good_sub.setter("text_size"))
            good_col.add_widget(good_sub)
            good_card.add_widget(good_col)

            content.add_widget(good_card)

        # -------------------------------------------------------------
        # FOOTER & LOGOUT
        # -------------------------------------------------------------
        footer = BoxLayout(size_hint_y=None, height=dp(36), padding=[dp(4), dp(4)], spacing=dp(10))
        footer_lbl = Label(
            text="SmartKadai Retail Management  •  Offline Ready",
            font_size="11sp",
            color=C_SEC_TEXT,
            halign="center",
            valign="middle"
        )
        footer_lbl.bind(size=footer_lbl.setter("text_size"))
        footer.add_widget(footer_lbl)
        content.add_widget(footer)

        # Responsive handler when window is resized or maximized
        def update_responsive_layout(window_instance, *args, **kwargs):
            width = None
            if args:
                if isinstance(args[0], (tuple, list)):
                    width = args[0][0]
                elif isinstance(args[0], (int, float)):
                    width = args[0]
            if width is None:
                width = getattr(window_instance, "width", 360)

            if width >= dp(600):
                # Desktop / Tablet / Maximized mode
                metrics_grid.cols = 4
                metrics_grid.height = dp(98)
                actions_grid.cols = 4
                actions_grid.height = dp(80)
            else:
                # Compact / Mobile mode
                metrics_grid.cols = 2
                metrics_grid.height = dp(204)
                actions_grid.cols = 2
                actions_grid.height = dp(170)

        if hasattr(self, "_dashboard_resize_cb") and self._dashboard_resize_cb:
            try:
                Window.unbind(on_resize=self._dashboard_resize_cb)
                Window.unbind(size=self._dashboard_resize_cb)
            except Exception:
                pass
        self._dashboard_resize_cb = update_responsive_layout
        Window.bind(on_resize=self._dashboard_resize_cb)
        Window.bind(size=self._dashboard_resize_cb)
        update_responsive_layout(Window, Window.width, Window.height)

        scroll.add_widget(content)
        root.add_widget(scroll)

        self.root.clear_widgets()
        self.root.add_widget(root)
    
    def open_section(self, name):
        if name == "Billing":
            self.show_billing()
        elif name == "Products":
            self.show_products()
        elif name == "Stock Management":
            self.show_stock()
        elif name == "Sales Report":
            self.show_sales_report("today")
        elif name == "AI Sales Forecast":
            self.show_forecast()
        else:
            self.message(name, f"{name} section.")

    # -------------------------------------------------------------
    # 1. PRODUCTS SCREEN
    # -------------------------------------------------------------
    def show_products(self):
        root = BoxLayout(orientation="vertical")
        with root.canvas.before:
            Color(*C_MAIN_BG)
            bg_rect = Rectangle(pos=root.pos, size=root.size)
        root.bind(
            pos=lambda inst, val: setattr(bg_rect, "pos", val),
            size=lambda inst, val: setattr(bg_rect, "size", val)
        )

        root.add_widget(make_screen_header("Product Catalog", "Manage items, prices & stock levels", self.show_dashboard))

        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(4))
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=[dp(14), dp(12), dp(14), dp(24)], size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        # Top Control Card: Search Bar & Add Button
        ctrl_card = RoundedCard(bg_color=C_WHITE, padding=[dp(12), dp(12)], spacing=dp(10), size_hint_y=None, height=dp(114), orientation="vertical")
        
        search_box = StyledInput(hint_text="Search by name or product ID...", size_hint_y=None, height=dp(38))
        ctrl_card.add_widget(search_box)

        btn_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(10))
        add_btn = PrimaryButton(
            text="[b]+ ADD PRODUCT[/b]",
            markup=True,
            font_size="12sp",
            size_hint=(None, None),
            size=(dp(142), dp(38)),
            pos_hint={"center_y": 0.5}
        )
        add_btn.bind(on_release=lambda *a: self.open_add_product_dialog())
        btn_row.add_widget(add_btn)

        count_lbl = Label(text="", font_size="11.5sp", color=C_SEC_TEXT, halign="right", valign="middle")
        count_lbl.bind(size=count_lbl.setter("text_size"))
        btn_row.add_widget(count_lbl)
        ctrl_card.add_widget(btn_row)
        content.add_widget(ctrl_card)

        # Container for Product Cards
        cards_container = BoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None)
        cards_container.bind(minimum_height=cards_container.setter("height"))
        content.add_widget(cards_container)

        def load_products_list(query=""):
            cards_container.clear_widgets()
            try:
                with get_db_connection(DB_PATH) as conn:
                    if query.strip():
                        q = f"%{query.strip()}%"
                        rows = conn.execute("""
                            SELECT product_id, product_name, selling_price, current_stock, safety_stock, supplier_lead_days
                            FROM products
                            WHERE product_name LIKE ? OR product_id LIKE ?
                            ORDER BY product_name
                        """, (q, q)).fetchall()
                    else:
                        rows = conn.execute("""
                            SELECT product_id, product_name, selling_price, current_stock, safety_stock, supplier_lead_days
                            FROM products
                            ORDER BY product_name
                        """).fetchall()
            except Exception as e:
                cards_container.add_widget(Label(text=f"Error loading catalog: {e}", color=C_DANGER, size_hint_y=None, height=dp(40)))
                return

            count_lbl.text = f"{len(rows)} products in catalog"

            if not rows:
                empty = RoundedCard(bg_color=C_WHITE, padding=[dp(16), dp(24)], size_hint_y=None, height=dp(90), orientation="vertical", spacing=dp(4))
                empty.add_widget(Label(text="[b]No matching products found[/b]", markup=True, font_size="13.5sp", color=C_SEC_TEXT, halign="center"))
                empty.add_widget(Label(text="Tap '+ Add Product' above to create a new retail item.", font_size="11sp", color=C_SEC_TEXT, halign="center"))
                cards_container.add_widget(empty)
                return

            for item in rows:
                pid, pname, price, cstock, sstock, lead_days = item
                is_out = cstock <= 0
                is_low = (cstock <= sstock) and not is_out

                card = RoundedCard(bg_color=C_WHITE, padding=[dp(12), dp(10)], spacing=dp(6), size_hint_y=None, height=dp(104), orientation="vertical")
                
                # Row 1: Product Name & ID Badge
                r1 = BoxLayout(size_hint_y=None, height=dp(22), spacing=dp(8))
                n_lbl = Label(
                    text=f"[b]{pname}[/b]",
                    markup=True,
                    font_size="14sp",
                    color=C_DARK_TEXT,
                    halign="left",
                    valign="middle",
                    shorten=True,
                    shorten_from="right"
                )
                n_lbl.bind(size=n_lbl.setter("text_size"))
                r1.add_widget(n_lbl)

                id_badge = BoxLayout(size_hint=(None, None), size=(dp(54), dp(22)), pos_hint={"center_y": 0.5})
                with id_badge.canvas.before:
                    Color(*C_SOFT_MINT)
                    RoundedRectangle(pos=id_badge.pos, size=id_badge.size, radius=[dp(6)])
                id_badge.bind(pos=lambda *a: None, size=lambda *a: None)
                id_lbl = Label(text=f"[b]{pid}[/b]", markup=True, font_size="10.5sp", color=C_DEEP_EMERALD, halign="center", valign="middle")
                id_badge.add_widget(id_lbl)
                r1.add_widget(id_badge)
                card.add_widget(r1)

                # Row 2: Price & Stock Badge
                r2 = BoxLayout(size_hint_y=None, height=dp(20), spacing=dp(8))
                p_lbl = Label(text=f"[b]₹{price:,.2f}[/b]", markup=True, font_size="13.5sp", color=C_EMERALD, size_hint_x=None, width=dp(85), halign="left", valign="middle")
                p_lbl.bind(size=p_lbl.setter("text_size"))
                r2.add_widget(p_lbl)

                if is_out:
                    st_col, st_txt = C_DANGER, f"Out of Stock ({cstock})"
                elif is_low:
                    st_col, st_txt = C_WARNING, f"Low Stock ({cstock})"
                else:
                    st_col, st_txt = C_SUCCESS, f"Stock: {cstock}"

                s_lbl = Label(text=f"[b]{st_txt}[/b]  •  Min: {sstock}  •  Lead: {lead_days}d", markup=True, font_size="11sp", color=st_col, halign="left", valign="middle")
                s_lbl.bind(size=s_lbl.setter("text_size"))
                r2.add_widget(s_lbl)
                card.add_widget(r2)

                # Row 3: Edit & Delete Action Buttons
                r3 = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(8))
                r3.add_widget(Widget()) # spacer

                edit_btn = SecondaryButton(text="Edit", size_hint=(None, None), size=(dp(64), dp(30)), font_size="11.5sp")
                edit_btn.bind(on_release=lambda *a, p_id=pid, p_n=pname, p_pr=price, p_sf=sstock, p_ld=lead_days: self.open_edit_product_dialog(p_id, p_n, p_pr, p_sf, p_ld))
                r3.add_widget(edit_btn)

                del_btn = SecondaryButton(text="Delete", size_hint=(None, None), size=(dp(68), dp(30)), font_size="11.5sp", color=C_DANGER)
                del_btn.bind(on_release=lambda *a, p_id=pid, p_n=pname: self.open_delete_product_dialog(p_id, p_n))
                r3.add_widget(del_btn)
                card.add_widget(r3)

                cards_container.add_widget(card)

        search_box.bind(text=lambda inst, val: load_products_list(val))
        load_products_list("")

        scroll.add_widget(content)
        root.add_widget(scroll)

        self.root.clear_widgets()
        self.root.add_widget(root)

    def open_add_product_dialog(self):
        # Auto-compute next sequential product ID
        suggested_id = "P001"
        try:
            with get_db_connection(DB_PATH) as conn:
                existing_ids = [r[0] for r in conn.execute("SELECT product_id FROM products").fetchall()]
                max_num = 0
                for pid in existing_ids:
                    if pid.startswith("P") and pid[1:].isdigit():
                        max_num = max(max_num, int(pid[1:]))
                suggested_id = f"P{max_num + 1:03d}"
        except Exception:
            pass

        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(12))
        
        box.add_widget(Label(text="Product ID:", font_size="11sp", color=C_DARK_TEXT, size_hint_y=None, height=dp(16), halign="left"))
        id_inp = StyledInput(text=suggested_id, size_hint_y=None, height=dp(36))
        box.add_widget(id_inp)

        box.add_widget(Label(text="Product Name:", font_size="11sp", color=C_DARK_TEXT, size_hint_y=None, height=dp(16), halign="left"))
        name_inp = StyledInput(hint_text="e.g. Atta 1kg, Sunflower Oil", size_hint_y=None, height=dp(36))
        box.add_widget(name_inp)

        box.add_widget(Label(text="Selling Price (₹):", font_size="11sp", color=C_DARK_TEXT, size_hint_y=None, height=dp(16), halign="left"))
        price_inp = StyledInput(hint_text="e.g. 60.00", size_hint_y=None, height=dp(36))
        box.add_widget(price_inp)

        box.add_widget(Label(text="Initial Stock Quantity:", font_size="11sp", color=C_DARK_TEXT, size_hint_y=None, height=dp(16), halign="left"))
        stock_inp = StyledInput(text="10", input_filter="int", size_hint_y=None, height=dp(36))
        box.add_widget(stock_inp)

        box.add_widget(Label(text="Safety Stock Threshold (Alert level):", font_size="11sp", color=C_DARK_TEXT, size_hint_y=None, height=dp(16), halign="left"))
        safety_inp = StyledInput(text="5", input_filter="int", size_hint_y=None, height=dp(36))
        box.add_widget(safety_inp)

        box.add_widget(Label(text="Supplier Lead Time (Days):", font_size="11sp", color=C_DARK_TEXT, size_hint_y=None, height=dp(16), halign="left"))
        lead_inp = StyledInput(text="3", input_filter="int", size_hint_y=None, height=dp(36))
        box.add_widget(lead_inp)

        btn_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(10))
        save_btn = PrimaryButton(text="Save Product", height=dp(38))
        cancel_btn = SecondaryButton(text="Cancel", height=dp(38))
        btn_row.add_widget(save_btn)
        btn_row.add_widget(cancel_btn)
        box.add_widget(btn_row)

        popup = Popup(title="Add New Product", content=box, size_hint=(0.90, 0.85))

        def save_product(*a):
            pid = id_inp.text.strip().upper()
            pname = name_inp.text.strip()
            if not pid or not pname:
                self.message("Validation Error", "Product ID and Name cannot be empty.")
                return
            try:
                price = float(price_inp.text.strip())
                if price <= 0:
                    raise ValueError
            except ValueError:
                self.message("Validation Error", "Selling price must be a positive number.")
                return

            try:
                cstock = int(stock_inp.text.strip())
                sstock = int(safety_inp.text.strip())
                if cstock < 0 or sstock < 0:
                    raise ValueError
            except ValueError:
                self.message("Validation Error", "Stock and Threshold must be non-negative integers.")
                return

            try:
                lead_days = int(lead_inp.text.strip())
                if lead_days < 0:
                    raise ValueError
            except ValueError:
                self.message("Validation Error", "Supplier Lead Time must be a non-negative whole number (0 or greater).")
                return

            try:
                with get_db_connection(DB_PATH) as conn:
                    # Check if ID exists
                    exists = conn.execute("SELECT 1 FROM products WHERE product_id = ?", (pid,)).fetchone()
                    if exists:
                        self.message("Duplicate ID", f"Product ID '{pid}' already exists. Choose another.")
                        return

                    conn.execute("""
                        INSERT INTO products (product_id, product_name, selling_price, current_stock, supplier_lead_days, safety_stock)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (pid, pname, price, cstock, lead_days, sstock))
                self.invalidate_forecast_cache()
                popup.dismiss()
                self.message("Product Saved", f"Successfully added '{pname}' ({pid}) to catalog.")
                self.show_products()
            except Exception as e:
                self.message("Database Error", f"Failed to save product: {e}")

        save_btn.bind(on_release=save_product)
        cancel_btn.bind(on_release=popup.dismiss)
        popup.open()

    def open_edit_product_dialog(self, pid, pname, price, safety_stock, supplier_lead_days=3):
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(12))

        box.add_widget(Label(text=f"Editing: {pid}", font_size="12sp", color=C_EMERALD, size_hint_y=None, height=dp(18)))

        box.add_widget(Label(text="Product Name:", font_size="11sp", color=C_DARK_TEXT, size_hint_y=None, height=dp(16)))
        name_inp = StyledInput(text=pname, size_hint_y=None, height=dp(36))
        box.add_widget(name_inp)

        box.add_widget(Label(text="Selling Price (₹):", font_size="11sp", color=C_DARK_TEXT, size_hint_y=None, height=dp(16)))
        price_inp = StyledInput(text=f"{price:.2f}", size_hint_y=None, height=dp(36))
        box.add_widget(price_inp)

        box.add_widget(Label(text="Safety Threshold:", font_size="11sp", color=C_DARK_TEXT, size_hint_y=None, height=dp(16)))
        safety_inp = StyledInput(text=str(safety_stock), input_filter="int", size_hint_y=None, height=dp(36))
        box.add_widget(safety_inp)

        box.add_widget(Label(text="Supplier Lead Time (Days):", font_size="11sp", color=C_DARK_TEXT, size_hint_y=None, height=dp(16)))
        lead_inp = StyledInput(text=str(supplier_lead_days), input_filter="int", size_hint_y=None, height=dp(36))
        box.add_widget(lead_inp)

        btn_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(10))
        save_btn = PrimaryButton(text="Update Product", height=dp(38))
        cancel_btn = SecondaryButton(text="Cancel", height=dp(38))
        btn_row.add_widget(save_btn)
        btn_row.add_widget(cancel_btn)
        box.add_widget(btn_row)

        popup = Popup(title=f"Edit Product {pid}", content=box, size_hint=(0.88, 0.70))

        def update_product(*a):
            new_name = name_inp.text.strip()
            if not new_name:
                self.message("Validation Error", "Product Name cannot be empty.")
                return
            try:
                new_price = float(price_inp.text.strip())
                if new_price <= 0:
                    raise ValueError
            except ValueError:
                self.message("Validation Error", "Selling price must be a positive number.")
                return

            try:
                new_safety = int(safety_inp.text.strip())
                if new_safety < 0:
                    raise ValueError
            except ValueError:
                self.message("Validation Error", "Threshold must be a non-negative integer.")
                return

            try:
                new_lead = int(lead_inp.text.strip())
                if new_lead < 0:
                    raise ValueError
            except ValueError:
                self.message("Validation Error", "Supplier Lead Time must be a non-negative whole number (0 or greater).")
                return

            try:
                with get_db_connection(DB_PATH) as conn:
                    conn.execute("""
                        UPDATE products
                        SET product_name = ?, selling_price = ?, safety_stock = ?, supplier_lead_days = ?
                        WHERE product_id = ?
                    """, (new_name, new_price, new_safety, new_lead, pid))
                self.invalidate_forecast_cache()
                popup.dismiss()
                self.message("Updated", f"Successfully updated '{new_name}'.")
                self.show_products()
            except Exception as e:
                self.message("Database Error", f"Update failed: {e}")

        save_btn.bind(on_release=update_product)
        cancel_btn.bind(on_release=popup.dismiss)
        popup.open()

    def open_delete_product_dialog(self, pid, pname):
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(14))
        box.add_widget(Label(
            text=f"Delete [b]{pname}[/b] ({pid})?\n\nThis will remove the item from the catalog.",
            markup=True,
            font_size="13sp",
            color=C_DARK_TEXT,
            halign="center"
        ))

        btn_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(10))
        del_btn = Button(text="Delete", background_normal="", background_color=C_DANGER, color=C_WHITE, font_size="12sp")
        cancel_btn = SecondaryButton(text="Cancel", height=dp(38))
        btn_row.add_widget(del_btn)
        btn_row.add_widget(cancel_btn)
        box.add_widget(btn_row)

        popup = Popup(title="Confirm Delete", content=box, size_hint=(0.85, 0.35))

        def confirm_delete(*a):
            try:
                with get_db_connection(DB_PATH) as conn:
                    # Pre-check: Protect products with historical sales records
                    sales_count = conn.execute("SELECT COUNT(*) FROM sales WHERE product_id = ?", (pid,)).fetchone()[0]
                    if sales_count > 0:
                        popup.dismiss()
                        self.message(
                            "Cannot Delete Product",
                            f"Product '{pname}' ({pid}) cannot be deleted because it has {sales_count} historical sales record(s).\n\n"
                            "Deleting this product would break past bill records and sales reports.\n"
                            "To discontinue this item, set its current stock to 0 instead."
                        )
                        return

                    conn.execute("DELETE FROM products WHERE product_id = ?", (pid,))
                self.invalidate_forecast_cache()
                popup.dismiss()
                self.message("Deleted", f"Product '{pname}' has been deleted.")
                self.show_products()
            except sqlite3.IntegrityError:
                popup.dismiss()
                self.message(
                    "Cannot Delete Product",
                    f"Product '{pname}' ({pid}) is referenced in billing history and cannot be deleted due to database integrity rules."
                )
            except Exception as e:
                self.message("Error", f"Failed to delete product: {e}")

        del_btn.bind(on_release=confirm_delete)
        cancel_btn.bind(on_release=popup.dismiss)
        popup.open()

    # -------------------------------------------------------------
    # 2. BILLING / NEW BILL SCREEN (Full Multi-Product Cart POS)
    # -------------------------------------------------------------
    def show_billing(self):
        if not hasattr(self, "cart"):
            self.cart = []

        root = BoxLayout(orientation="vertical")
        with root.canvas.before:
            Color(*C_MAIN_BG)
            bg_rect = Rectangle(pos=root.pos, size=root.size)
        root.bind(
            pos=lambda inst, val: setattr(bg_rect, "pos", val),
            size=lambda inst, val: setattr(bg_rect, "size", val)
        )

        root.add_widget(make_screen_header("New Customer Bill", "Retail Point-of-Sale checkout", self.show_dashboard))

        # Query all products from SQLite
        try:
            with get_db_connection(DB_PATH) as conn:
                products_list = conn.execute("""
                    SELECT product_id, product_name, selling_price, current_stock
                    FROM products
                    ORDER BY product_name
                """).fetchall()
        except Exception as e:
            self.message("Database Error", str(e))
            self.show_dashboard()
            return

        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(4))
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=[dp(14), dp(12), dp(14), dp(24)], size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        # Section 1: Item Selection & Add to Bill Card
        add_card = RoundedCard(bg_color=C_WHITE, padding=[dp(12), dp(12)], spacing=dp(8), size_hint_y=None, height=dp(136), orientation="vertical")
        
        add_title = Label(text="[b]Select Product to Bill[/b]", markup=True, font_size="13.5sp", color=C_DARK_TEXT, size_hint_y=None, height=dp(18), halign="left")
        add_title.bind(size=add_title.setter("text_size"))
        add_card.add_widget(add_title)

        if not products_list:
            add_card.add_widget(Label(text="No products in catalog. Add products first.", color=C_DANGER, size_hint_y=None, height=dp(30)))
            content.add_widget(add_card)
        else:
            prod_map = {
                f"{p[1]} (Stock: {p[3]}) | ₹{p[2]:.2f}": p
                for p in products_list
            }
            spinner = Spinner(
                text=list(prod_map.keys())[0],
                values=list(prod_map.keys()),
                size_hint_y=None,
                height=dp(38),
                background_normal="",
                background_color=(0.94, 0.96, 0.95, 1.0),
                color=C_DARK_TEXT,
                font_size="12.5sp"
            )
            add_card.add_widget(spinner)

            action_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(8))
            qty_input = StyledInput(text="1", input_filter="int", hint_text="Qty", size_hint_x=0.35, height=dp(38))
            action_row.add_widget(qty_input)

            add_item_btn = PrimaryButton(text="+ Add to Bill", height=dp(38), size_hint_x=0.65)
            action_row.add_widget(add_item_btn)
            add_card.add_widget(action_row)
            content.add_widget(add_card)

        # Section 2: Current Bill Items (Cart Table)
        cart_header_row = BoxLayout(size_hint_y=None, height=dp(26), spacing=dp(8))
        cart_title = Label(text="[b]Current Bill Items[/b]", markup=True, font_size="15sp", color=C_DARK_TEXT, halign="left", valign="middle")
        cart_title.bind(size=cart_title.setter("text_size"))
        cart_header_row.add_widget(cart_title)

        clear_bill_btn = Button(
            text="Clear Bill",
            size_hint=(None, None),
            size=(dp(78), dp(26)),
            pos_hint={"center_y": 0.5},
            background_normal="",
            background_color=(0.95, 0.90, 0.90, 1.0),
            color=C_DANGER,
            font_size="11sp"
        )
        cart_header_row.add_widget(clear_bill_btn)
        content.add_widget(cart_header_row)

        cart_card = RoundedCard(bg_color=C_WHITE, padding=[dp(12), dp(10)], spacing=dp(6), size_hint_y=None)
        
        cart_items_box = BoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None)
        cart_items_box.bind(minimum_height=cart_items_box.setter("height"))
        cart_items_box.bind(height=lambda inst, val: setattr(cart_card, "height", max(val + dp(20), dp(58))))
        cart_card.add_widget(cart_items_box)
        content.add_widget(cart_card)

        # Section 3: Bill Total & Checkout Summary Card
        summary_card = RoundedCard(bg_color=C_PALE_SURFACE, border_color=C_SOFT_MINT, padding=[dp(14), dp(12)], spacing=dp(10), size_hint_y=None, height=dp(110), orientation="vertical")
        
        sum_row = BoxLayout(size_hint_y=None, height=dp(28))
        items_count_lbl = Label(text="Items: 0  •  Units: 0", font_size="12sp", color=C_SEC_TEXT, halign="left", valign="middle")
        items_count_lbl.bind(size=items_count_lbl.setter("text_size"))
        sum_row.add_widget(items_count_lbl)

        total_val_lbl = Label(text="[b]Total: ₹0.00[/b]", markup=True, font_size="18sp", color=C_DEEP_EMERALD, halign="right", valign="middle")
        total_val_lbl.bind(size=total_val_lbl.setter("text_size"))
        sum_row.add_widget(total_val_lbl)
        summary_card.add_widget(sum_row)

        checkout_btn = Button(
            text="Confirm & Save Bill",
            size_hint_y=None,
            height=dp(42),
            background_normal="",
            background_color=C_EMERALD,
            color=C_WHITE,
            font_size="14sp"
        )
        summary_card.add_widget(checkout_btn)
        content.add_widget(summary_card)

        def update_cart_ui():
            cart_items_box.clear_widgets()
            total_amount = sum(it["line_total"] for it in self.cart)
            total_units = sum(it["quantity"] for it in self.cart)
            total_items = len(self.cart)

            items_count_lbl.text = f"Items: {total_items}  •  Units: {total_units}"
            total_val_lbl.text = f"[b]Total: ₹{total_amount:,.2f}[/b]"

            if not self.cart:
                empty_lbl = Label(text="No items in bill yet. Select a product above and click '+ Add to Bill'.", font_size="11.5sp", color=C_SEC_TEXT, size_hint_y=None, height=dp(48), halign="center", valign="middle")
                empty_lbl.bind(size=empty_lbl.setter("text_size"))
                cart_items_box.add_widget(empty_lbl)
                checkout_btn.disabled = True
                checkout_btn.background_color = (0.7, 0.75, 0.72, 1.0)
                clear_bill_btn.disabled = True
                clear_bill_btn.opacity = 0.0
                return

            clear_bill_btn.disabled = False
            clear_bill_btn.opacity = 1.0
            checkout_btn.disabled = False
            checkout_btn.background_color = C_EMERALD

            # Table Header for Cart Items
            th_row = BoxLayout(size_hint_y=None, height=dp(20), spacing=dp(6))
            th_name = Label(text="ITEM / PRICE", font_size="9.5sp", color=C_SEC_TEXT, halign="left", valign="middle")
            th_name.bind(size=th_name.setter("text_size"))
            th_row.add_widget(th_name)

            th_qty = Label(text="QTY", font_size="9.5sp", color=C_SEC_TEXT, size_hint_x=None, width=dp(76), halign="center", valign="middle")
            th_qty.bind(size=th_qty.setter("text_size"))
            th_row.add_widget(th_qty)

            th_tot = Label(text="TOTAL", font_size="9.5sp", color=C_SEC_TEXT, size_hint_x=None, width=dp(68), halign="right", valign="middle")
            th_tot.bind(size=th_tot.setter("text_size"))
            th_row.add_widget(th_tot)

            th_act = Label(text="", size_hint_x=None, width=dp(24))
            th_row.add_widget(th_act)
            cart_items_box.add_widget(th_row)

            for idx, item in enumerate(self.cart):
                row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(44), spacing=dp(6))
                
                # Name & unit price
                info_col = BoxLayout(orientation="vertical", spacing=dp(1), pos_hint={"center_y": 0.5})
                it_name = Label(text=f"[b]{item['product_name']}[/b]", markup=True, font_size="12.5sp", color=C_DARK_TEXT, size_hint_y=None, height=dp(18), halign="left", shorten=True, shorten_from="right")
                it_name.bind(size=it_name.setter("text_size"))
                info_col.add_widget(it_name)

                it_sub = Label(text=f"@ ₹{item['selling_price']:.2f}", font_size="10.5sp", color=C_SEC_TEXT, size_hint_y=None, height=dp(14), halign="left")
                it_sub.bind(size=it_sub.setter("text_size"))
                info_col.add_widget(it_sub)
                row.add_widget(info_col)

                # Quantity controls: [-] Qty [+]
                qty_box = BoxLayout(size_hint=(None, None), size=(dp(76), dp(28)), spacing=dp(2), pos_hint={"center_y": 0.5})
                minus_btn = Button(text="-", size_hint=(None, 1), width=dp(22), background_normal="", background_color=(0.90, 0.92, 0.94, 1.0), color=C_DARK_TEXT, font_size="14sp")
                q_lbl = Label(text=str(item["quantity"]), font_size="12sp", color=C_DARK_TEXT)
                plus_btn = Button(text="+", size_hint=(None, 1), width=dp(22), background_normal="", background_color=(0.90, 0.92, 0.94, 1.0), color=C_DARK_TEXT, font_size="14sp")
                
                minus_btn.bind(on_release=lambda *a, i=idx: adjust_qty(i, -1))
                plus_btn.bind(on_release=lambda *a, i=idx: adjust_qty(i, +1))
                qty_box.add_widget(minus_btn)
                qty_box.add_widget(q_lbl)
                qty_box.add_widget(plus_btn)
                row.add_widget(qty_box)

                # Line total
                lt_lbl = Label(text=f"[b]₹{item['line_total']:,.2f}[/b]", markup=True, font_size="12.5sp", color=C_EMERALD, size_hint_x=None, width=dp(68), halign="right", valign="middle")
                lt_lbl.bind(size=lt_lbl.setter("text_size"))
                row.add_widget(lt_lbl)

                # Remove button
                rm_btn = Button(text="✕", size_hint=(None, None), size=(dp(24), dp(24)), pos_hint={"center_y": 0.5}, background_normal="", background_color=(0.98, 0.90, 0.90, 1.0), color=C_DANGER, font_size="11sp")
                rm_btn.bind(on_release=lambda *a, i=idx: remove_item(i))
                row.add_widget(rm_btn)

                cart_items_box.add_widget(row)

                if idx < len(self.cart) - 1:
                    divider = Widget(size_hint_y=None, height=dp(1))
                    with divider.canvas:
                        Color(*C_DIVIDER)
                        Rectangle(pos=divider.pos, size=(divider.width, dp(1)))
                    cart_items_box.add_widget(divider)

        def on_clear_bill(*a):
            if not self.cart:
                return
            self.cart = []
            update_cart_ui()

        clear_bill_btn.bind(on_release=on_clear_bill)

        def adjust_qty(index, delta):
            if 0 <= index < len(self.cart):
                item = self.cart[index]
                new_q = item["quantity"] + delta
                if new_q <= 0:
                    self.cart.pop(index)
                else:
                    if new_q > item["current_stock"]:
                        self.message("Stock Limit", f"Only {item['current_stock']} units available in stock.")
                        return
                    item["quantity"] = new_q
                    item["line_total"] = round(new_q * item["selling_price"], 2)
                update_cart_ui()

        def remove_item(index):
            if 0 <= index < len(self.cart):
                self.cart.pop(index)
                update_cart_ui()

        def on_add_item(*a):
            if not products_list:
                return
            raw_qty = qty_input.text.strip()
            if not raw_qty:
                self.message("Invalid Quantity", "Please enter a positive whole number for quantity.")
                return
            try:
                qty = int(raw_qty)
                if qty <= 0:
                    self.message("Invalid Quantity", f"Quantity must be a positive whole number (at least 1). Received: '{raw_qty}'.")
                    return
            except ValueError:
                self.message("Invalid Quantity", f"Please enter a positive whole number for quantity. Received: '{raw_qty}'.")
                return

            selected_tuple = prod_map[spinner.text]
            pid, pname, price, stock = selected_tuple

            if stock <= 0:
                self.message("Out of Stock", f"'{pname}' is out of stock.")
                return

            # Check existing cart quantity
            existing = next((it for it in self.cart if it["product_id"] == pid), None)
            current_in_cart = existing["quantity"] if existing else 0
            if current_in_cart + qty > stock:
                remaining_avail = max(0, stock - current_in_cart)
                self.message(
                    "Stock Limit Exceeded",
                    f"Only {stock} available for '{pname}'. You already have {current_in_cart} in your bill. Maximum additional: {remaining_avail}."
                )
                return

            if existing:
                existing["quantity"] += qty
                existing["line_total"] = round(existing["quantity"] * existing["selling_price"], 2)
            else:
                self.cart.append({
                    "product_id": pid,
                    "product_name": pname,
                    "selling_price": price,
                    "current_stock": stock,
                    "quantity": qty,
                    "line_total": round(price * qty, 2)
                })

            qty_input.text = "1"
            update_cart_ui()

        if products_list:
            add_item_btn.bind(on_release=on_add_item)

        def on_confirm_checkout(*a):
            if not self.cart:
                self.message("Empty Bill", "Please add at least one product before saving.")
                return

            # --- Pre-checkout Sanity & Consistency Checks ---
            if not isinstance(self.cart, list) or len(self.cart) == 0:
                self.message("Empty Bill", "Please add at least one product before saving.")
                return

            for item in self.cart:
                pid = item.get("product_id")
                pname = item.get("product_name", "Unknown Item")
                q = item.get("quantity")
                sp = item.get("selling_price")
                stk = item.get("current_stock", 0)

                if not pid or not isinstance(pid, str):
                    self.message("Cart Validation Error", f"Invalid product ID: '{pid}'.")
                    return

                if not isinstance(q, int) or q <= 0:
                    self.message("Cart Validation Error", f"Invalid quantity ({q}) for '{pname}'. Must be a positive integer.")
                    return

                if not isinstance(sp, (int, float)) or sp < 0:
                    self.message("Cart Validation Error", f"Invalid selling price for '{pname}'.")
                    return

                if q > stk:
                    self.message("Stock Limit Exceeded", f"Cannot checkout: '{pname}' quantity ({q}) exceeds current stock ({stk}).")
                    return

                # Strict recalculation of line total
                item["line_total"] = round(q * float(sp), 2)

            grand_total = round(sum(it["line_total"] for it in self.cart), 2)
            if grand_total <= 0:
                self.message("Invalid Bill Total", f"Bill grand total must be greater than zero. Calculated: ₹{grand_total:,.2f}")
                return

            items_count = len(self.cart)

            # Disable button to prevent duplicate clicks
            checkout_btn.disabled = True

            bill_id = "SK-" + datetime.now().strftime("%Y%m%d%H%M%S")
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            timestamp_str = now.isoformat(timespec="seconds")

            try:
                with get_db_connection(DB_PATH) as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    for item in self.cart:
                        # 1. Update and verify stock
                        res = conn.execute("""
                            UPDATE products
                            SET current_stock = current_stock - ?
                            WHERE product_id = ? AND current_stock >= ?
                        """, (item["quantity"], item["product_id"], item["quantity"]))
                        if res.rowcount != 1:
                            raise ValueError(f"Stock changed for '{item['product_name']}'. Refresh and try again.")

                        # 2. Insert sales row
                        conn.execute("""
                            INSERT INTO sales (bill_id, timestamp, date, product_id, quantity_sold, selling_price)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (bill_id, timestamp_str, today_str, item["product_id"], item["quantity"], item["selling_price"]))

                # Clear cart and show receipt
                self.cart = []
                self.invalidate_forecast_cache()
                show_receipt_popup(bill_id, items_count, grand_total)
            except Exception as e:
                self.message("Checkout Failed", str(e))
                checkout_btn.disabled = False

        def show_receipt_popup(bill_ref, num_items, total_val):
            box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(14))
            
            box.add_widget(Label(text="[b]BILL COMPLETED SUCCESSFULLY[/b]", markup=True, font_size="15sp", color=C_SUCCESS, size_hint_y=None, height=dp(24)))
            box.add_widget(Label(text=f"Bill Reference:\n[b]{bill_ref}[/b]", markup=True, font_size="13sp", color=C_DARK_TEXT, halign="center"))
            box.add_widget(Label(text=f"Items: {num_items}   •   Total: [b]₹{total_val:,.2f}[/b]", markup=True, font_size="15sp", color=C_DEEP_EMERALD, halign="center"))

            btn_row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(10))
            new_btn = PrimaryButton(text="New Bill", height=dp(40))
            dash_btn = SecondaryButton(text="Dashboard", height=dp(40))
            btn_row.add_widget(new_btn)
            btn_row.add_widget(dash_btn)
            box.add_widget(btn_row)

            receipt_popup = Popup(title="Retail Sale Receipt", content=box, size_hint=(0.88, 0.44), auto_dismiss=False)
            new_btn.bind(on_release=lambda *a: (receipt_popup.dismiss(), self.show_billing()))
            dash_btn.bind(on_release=lambda *a: (receipt_popup.dismiss(), self.show_dashboard()))
            receipt_popup.open()

        checkout_btn.bind(on_release=on_confirm_checkout)
        update_cart_ui()

        scroll.add_widget(content)
        root.add_widget(scroll)

        self.root.clear_widgets()
        self.root.add_widget(root)

    # -------------------------------------------------------------
    # 3. STOCK MANAGEMENT SCREEN (Inventory Levels & Restocking)
    # -------------------------------------------------------------
    def show_stock(self):
        if not hasattr(self, "stock_filter"):
            self.stock_filter = "all"
        if not hasattr(self, "stock_search_query"):
            self.stock_search_query = ""

        root = BoxLayout(orientation="vertical")
        with root.canvas.before:
            Color(*C_MAIN_BG)
            bg_rect = Rectangle(pos=root.pos, size=root.size)
        root.bind(
            pos=lambda inst, val: setattr(bg_rect, "pos", val),
            size=lambda inst, val: setattr(bg_rect, "size", val)
        )

        root.add_widget(make_screen_header("Stock Management", "Inventory tracking, replenishments & safety alerts", self.show_dashboard))

        # Query products and stock metrics from SQLite
        try:
            with get_db_connection(DB_PATH) as conn:
                products_list = conn.execute("""
                    SELECT product_id, product_name, current_stock, safety_stock
                    FROM products
                    ORDER BY product_name
                """).fetchall()
        except Exception as e:
            self.message("Database Error", str(e))
            self.show_dashboard()
            return

        total_prods = len(products_list)
        in_stock_items = [p for p in products_list if p[2] > p[3]]
        low_stock_items = [p for p in products_list if p[2] <= p[3] and p[2] > 0]
        out_of_stock_items = [p for p in products_list if p[2] <= 0]

        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(4))
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=[dp(14), dp(12), dp(14), dp(24)], size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        # Top 3 Metrics Summary Bar
        metrics_bar = GridLayout(cols=3, spacing=dp(8), size_hint_y=None, height=dp(68))
        
        def make_stat_box(title, val, val_col):
            b = RoundedCard(bg_color=C_WHITE, padding=[dp(8), dp(6)], orientation="vertical", spacing=dp(2))
            tl = Label(text=title, font_size="9.5sp", color=C_SEC_TEXT, halign="center", valign="middle")
            tl.bind(size=tl.setter("text_size"))
            vl = Label(text=f"[b]{val}[/b]", markup=True, font_size="17sp", color=val_col, halign="center", valign="middle")
            vl.bind(size=vl.setter("text_size"))
            b.add_widget(tl)
            b.add_widget(vl)
            return b

        metrics_bar.add_widget(make_stat_box("TOTAL PRODUCTS", str(total_prods), C_DARK_TEXT))
        metrics_bar.add_widget(make_stat_box("LOW STOCK", str(len(low_stock_items)), C_WARNING if low_stock_items else C_SUCCESS))
        metrics_bar.add_widget(make_stat_box("OUT OF STOCK", str(len(out_of_stock_items)), C_DANGER if out_of_stock_items else C_SUCCESS))
        content.add_widget(metrics_bar)

        # Section 1: Low Stock Alert Watchlist (if any need replenishment)
        if low_stock_items or out_of_stock_items:
            alert_header = BoxLayout(size_hint_y=None, height=dp(22))
            alert_title = Label(text="[b]Stock Replenishment Needed[/b]", markup=True, font_size="14.5sp", color=C_DANGER if out_of_stock_items else C_WARNING, halign="left")
            alert_title.bind(size=alert_title.setter("text_size"))
            alert_header.add_widget(alert_title)
            content.add_widget(alert_header)

            alert_card = RoundedCard(bg_color=C_WHITE, border_color=C_WARNING, padding=[dp(12), dp(10)], spacing=dp(6), size_hint_y=None)
            alert_card.bind(minimum_height=alert_card.setter("height"))

            for idx, p in enumerate(out_of_stock_items + low_stock_items):
                pid, pname, cstock, sstock = p
                is_out = cstock <= 0
                bg_col = C_DANGER if is_out else C_WARNING

                row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
                info = Label(text=f"[b]{pname}[/b]  •  Stock: [b]{cstock}[/b] (Min: {sstock})", markup=True, font_size="12sp", color=C_DARK_TEXT, halign="left", valign="middle", shorten=True, shorten_from="right")
                info.bind(size=info.setter("text_size"))
                row.add_widget(info)

                reorder_btn = Button(text="+ Add", size_hint=(None, None), size=(dp(58), dp(28)), pos_hint={"center_y": 0.5}, background_normal="", background_color=bg_col, color=C_WHITE, font_size="11sp")
                reorder_btn.bind(on_release=lambda *a, p_id=pid, p_n=pname: self.open_quick_restock_dialog(p_id, p_n))
                row.add_widget(reorder_btn)

                alert_card.add_widget(row)
            content.add_widget(alert_card)
        else:
            good_banner = RoundedCard(bg_color=C_PALE_SURFACE, border_color=C_SOFT_MINT, padding=[dp(12), dp(10)], size_hint_y=None, height=dp(52), orientation="horizontal", spacing=dp(8))
            chk = Label(text="[b]OK[/b]", markup=True, font_size="11sp", color=C_SUCCESS, size_hint_x=None, width=dp(28))
            good_banner.add_widget(chk)
            gt = Label(text="[b]All inventory healthy.[/b] No items need replenishment.", markup=True, font_size="12sp", color=C_SUCCESS, halign="left", valign="middle")
            gt.bind(size=gt.setter("text_size"))
            good_banner.add_widget(gt)
            content.add_widget(good_banner)

        # Section 2: Receive Incoming Stock Card
        replenish_card = RoundedCard(bg_color=C_WHITE, padding=[dp(12), dp(12)], spacing=dp(8), size_hint_y=None, height=dp(136), orientation="vertical")
        rt = Label(text="[b]Receive Incoming Stock[/b]", markup=True, font_size="13.5sp", color=C_DARK_TEXT, size_hint_y=None, height=dp(18), halign="left")
        rt.bind(size=rt.setter("text_size"))
        replenish_card.add_widget(rt)

        if products_list:
            prod_stock_map = {
                f"{p[1]} (Stock: {p[2]})": p
                for p in products_list
            }
            stock_spinner = Spinner(
                text=list(prod_stock_map.keys())[0],
                values=list(prod_stock_map.keys()),
                size_hint_y=None,
                height=dp(38),
                background_normal="",
                background_color=(0.94, 0.96, 0.95, 1.0),
                color=C_DARK_TEXT,
                font_size="12.5sp"
            )
            replenish_card.add_widget(stock_spinner)

            act_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(8))
            qty_add_input = StyledInput(text="10", input_filter="int", hint_text="Units to add", size_hint_x=0.45, height=dp(38))
            act_row.add_widget(qty_add_input)

            add_stock_btn = PrimaryButton(text="+ Add Stock", height=dp(38), size_hint_x=0.55)
            act_row.add_widget(add_stock_btn)
            replenish_card.add_widget(act_row)

            def do_add_stock(*a):
                raw = qty_add_input.text.strip()
                if not raw:
                    self.message("Invalid Quantity", "Enter a positive number of units to add.")
                    return
                try:
                    qty = int(raw)
                    if qty <= 0:
                        self.message("Invalid Quantity", f"Enter a positive number of units to add (at least 1). Received: '{raw}'.")
                        return
                except ValueError:
                    self.message("Invalid Quantity", f"Enter a positive whole number of units to add. Received: '{raw}'.")
                    return

                selected = prod_stock_map[stock_spinner.text]
                pid, pname = selected[0], selected[1]

                try:
                    with get_db_connection(DB_PATH) as conn:
                        res = conn.execute("UPDATE products SET current_stock = current_stock + ? WHERE product_id = ?", (qty, pid))
                        if res.rowcount != 1:
                            raise ValueError(f"Product '{pid}' not found in catalog.")
                        new_stock = conn.execute("SELECT current_stock FROM products WHERE product_id = ?", (pid,)).fetchone()[0]
                    self.invalidate_forecast_cache()
                    self.message("Stock Updated", f"Added {qty} units to '{pname}'.\nNew total stock: {new_stock}")
                    self.show_stock()
                except Exception as e:
                    self.message("Database Error", f"Failed to update stock: {e}")

            add_stock_btn.bind(on_release=do_add_stock)

        content.add_widget(replenish_card)

        # Section 3: Redesigned Inventory Levels Table with Search and Filters
        inv_title_row = BoxLayout(size_hint_y=None, height=dp(26), spacing=dp(8))
        inv_title = Label(text="[b]Inventory Levels[/b]", markup=True, font_size="15sp", color=C_DARK_TEXT, halign="left", valign="middle")
        inv_title.bind(size=inv_title.setter("text_size"))
        inv_title_row.add_widget(inv_title)

        inv_count_lbl = Label(text="", font_size="11.5sp", color=C_SEC_TEXT, halign="right", valign="middle")
        inv_count_lbl.bind(size=inv_count_lbl.setter("text_size"))
        inv_title_row.add_widget(inv_count_lbl)
        content.add_widget(inv_title_row)

        # Search and Filters Card
        ctrl_card = RoundedCard(bg_color=C_WHITE, padding=[dp(10), dp(10)], spacing=dp(8), size_hint_y=None, height=dp(90), orientation="vertical")
        
        search_box = StyledInput(text=self.stock_search_query, hint_text="Search by product name or product ID...", size_hint_y=None, height=dp(34))
        ctrl_card.add_widget(search_box)

        filter_scroll = ScrollView(do_scroll_x=True, do_scroll_y=False, size_hint_y=None, height=dp(30), bar_width=0)
        filter_row = BoxLayout(spacing=dp(6), size_hint=(None, 1))

        tab_all = Button(text=f"All Products ({total_prods})", size_hint=(0.25, 1), background_normal="", font_size="10.5sp")
        tab_in = Button(text=f"In Stock ({len(in_stock_items)})", size_hint=(0.25, 1), background_normal="", font_size="10.5sp")
        tab_low = Button(text=f"Low Stock ({len(low_stock_items)})", size_hint=(0.25, 1), background_normal="", font_size="10.5sp")
        tab_out = Button(text=f"Out of Stock ({len(out_of_stock_items)})", size_hint=(0.25, 1), background_normal="", font_size="10.5sp")

        filter_buttons = [
            (tab_all, "all"),
            (tab_in, "instock"),
            (tab_low, "low"),
            (tab_out, "out")
        ]

        def update_tab_buttons():
            for btn, key in filter_buttons:
                if self.stock_filter == key:
                    btn.background_color = C_EMERALD
                    btn.color = C_WHITE
                else:
                    btn.background_color = (0.94, 0.96, 0.95, 1.0)
                    btn.color = C_DARK_TEXT

        def update_filter_geom(*args):
            avail_w = max(ctrl_card.width - dp(20), dp(440))
            filter_row.width = avail_w
            filter_scroll.width = max(ctrl_card.width - dp(20), dp(100))

        ctrl_card.bind(width=update_filter_geom)

        for btn, key in filter_buttons:
            def on_tab_click(*a, k=key):
                self.stock_filter = k
                update_tab_buttons()
                render_table_rows()
            btn.bind(on_release=on_tab_click)
            filter_row.add_widget(btn)

        update_tab_buttons()
        filter_scroll.add_widget(filter_row)
        ctrl_card.add_widget(filter_scroll)
        content.add_widget(ctrl_card)

        # Inventory Table Card
        inv_table_card = RoundedCard(bg_color=C_WHITE, padding=[dp(8), dp(8)], spacing=dp(4), size_hint_y=None)

        table_scroll = ScrollView(do_scroll_x=True, do_scroll_y=False, size_hint_y=None, bar_width=dp(3))
        table_layout = BoxLayout(orientation="vertical", size_hint=(None, None), spacing=dp(2))
        table_layout.bind(minimum_height=table_layout.setter("height"))

        def update_table_geom(*args):
            avail_w = max(inv_table_card.width - dp(16), dp(620))
            table_layout.width = avail_w
            table_scroll.width = max(inv_table_card.width - dp(16), dp(100))

        inv_table_card.bind(width=update_table_geom)
        table_layout.bind(height=lambda inst, val: (
            setattr(table_scroll, "height", val),
            setattr(inv_table_card, "height", val + dp(18))
        ))

        # Table Header Row (Consistent 6-Column Layout)
        th_bar = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(4), padding=[dp(6), dp(0)])
        with th_bar.canvas.before:
            Color(0.92, 0.95, 0.93, 1.0)
            th_bg = RoundedRectangle(pos=th_bar.pos, size=th_bar.size, radius=[dp(6)])
        th_bar.bind(
            pos=lambda inst, val: setattr(th_bg, "pos", val),
            size=lambda inst, val: setattr(th_bg, "size", val)
        )

        def make_th_cell(title, ratio, halign):
            lbl = Label(
                text=f"[b]{title}[/b]",
                markup=True,
                font_size="10.5sp",
                color=C_DEEP_EMERALD,
                size_hint_x=ratio,
                halign=halign,
                valign="middle"
            )
            lbl.bind(size=lbl.setter("text_size"))
            return lbl

        th_bar.add_widget(make_th_cell("PRODUCT ID", 0.13, "left"))
        th_bar.add_widget(make_th_cell("PRODUCT NAME", 0.28, "left"))
        th_bar.add_widget(make_th_cell("CURRENT STOCK", 0.15, "center"))
        th_bar.add_widget(make_th_cell("MIN. STOCK", 0.14, "center"))
        th_bar.add_widget(make_th_cell("STATUS", 0.16, "center"))
        th_bar.add_widget(make_th_cell("ACTION", 0.14, "right"))

        def render_table_rows():
            table_layout.clear_widgets()
            table_layout.add_widget(th_bar)

            q = self.stock_search_query.strip().lower()
            filtered = []
            for p in products_list:
                pid, pname, cstock, sstock = p
                # Search filter
                if q and (q not in pname.lower() and q not in pid.lower()):
                    continue
                # Status filter
                if self.stock_filter == "instock" and cstock <= sstock:
                    continue
                if self.stock_filter == "low" and not (cstock <= sstock and cstock > 0):
                    continue
                if self.stock_filter == "out" and cstock > 0:
                    continue
                filtered.append(p)

            inv_count_lbl.text = f"Showing {len(filtered)} of {total_prods} products"

            if not filtered:
                empty_row = BoxLayout(size_hint_y=None, height=dp(54))
                empty_lbl = Label(text="No products match the selected filter or search query.", font_size="12sp", color=C_SEC_TEXT, halign="center", valign="middle")
                empty_lbl.bind(size=empty_lbl.setter("text_size"))
                empty_row.add_widget(empty_lbl)
                table_layout.add_widget(empty_row)
                return

            for idx, p in enumerate(filtered):
                pid, pname, cstock, sstock = p
                is_out = cstock <= 0
                is_low = (cstock <= sstock) and not is_out

                t_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(4), padding=[dp(6), dp(0)])

                # 1. Product ID (Left)
                c_id = Label(text=f"[b]{pid}[/b]", markup=True, font_size="11sp", color=C_DEEP_EMERALD, size_hint_x=0.13, halign="left", valign="middle")
                c_id.bind(size=c_id.setter("text_size"))
                t_row.add_widget(c_id)

                # 2. Product Name (Left)
                c_name = Label(text=f"[b]{pname}[/b]", markup=True, font_size="11.5sp", color=C_DARK_TEXT, size_hint_x=0.28, halign="left", valign="middle", shorten=True, shorten_from="right")
                c_name.bind(size=c_name.setter("text_size"))
                t_row.add_widget(c_name)

                # 3. Current Stock (Center)
                c_stock = Label(text=f"[b]{cstock}[/b] units", markup=True, font_size="11.5sp", color=C_DARK_TEXT, size_hint_x=0.15, halign="center", valign="middle")
                c_stock.bind(size=c_stock.setter("text_size"))
                t_row.add_widget(c_stock)

                # 4. Minimum Safety Stock (Center)
                c_min = Label(text=f"{sstock} units", font_size="11sp", color=C_SEC_TEXT, size_hint_x=0.14, halign="center", valign="middle")
                c_min.bind(size=c_min.setter("text_size"))
                t_row.add_widget(c_min)

                # 5. Status Badge (Center)
                if is_out:
                    badge_bg, badge_fg, badge_txt = (0.99, 0.88, 0.88, 1.0), C_DANGER, "OUT OF STOCK"
                elif is_low:
                    badge_bg, badge_fg, badge_txt = (0.99, 0.94, 0.85, 1.0), C_WARNING, "LOW STOCK"
                else:
                    badge_bg, badge_fg, badge_txt = C_SOFT_MINT, C_DEEP_EMERALD, "IN STOCK"

                c_status_box = AnchorLayout(anchor_x="center", anchor_y="center", size_hint_x=0.16)
                badge_box = BoxLayout(size_hint=(None, None), size=(dp(90), dp(22)))
                with badge_box.canvas.before:
                    Color(*badge_bg)
                    b_rect = RoundedRectangle(pos=badge_box.pos, size=badge_box.size, radius=[dp(5)])
                badge_box.bind(
                    pos=lambda inst, val, r=b_rect: setattr(r, "pos", val),
                    size=lambda inst, val, r=b_rect: setattr(r, "size", val)
                )
                b_lbl = Label(text=f"[b]{badge_txt}[/b]", markup=True, font_size="9sp", color=badge_fg, halign="center", valign="middle")
                b_lbl.bind(size=b_lbl.setter("text_size"))
                badge_box.add_widget(b_lbl)
                c_status_box.add_widget(badge_box)
                t_row.add_widget(c_status_box)

                # 6. Action Button (Right)
                c_act_box = AnchorLayout(anchor_x="right", anchor_y="center", size_hint_x=0.14)
                restock_btn = SecondaryButton(text="+ Restock", size_hint=(None, None), size=(dp(74), dp(26)), font_size="10.5sp")
                restock_btn.bind(on_release=lambda *a, p_id=pid, p_n=pname: self.open_quick_restock_dialog(p_id, p_n))
                c_act_box.add_widget(restock_btn)
                t_row.add_widget(c_act_box)

                table_layout.add_widget(t_row)

                if idx < len(filtered) - 1:
                    row_div = Widget(size_hint_y=None, height=dp(1))
                    with row_div.canvas:
                        Color(*C_DIVIDER)
                        d_rect = Rectangle(pos=row_div.pos, size=row_div.size)
                    row_div.bind(
                        pos=lambda inst, val, r=d_rect: setattr(r, "pos", val),
                        size=lambda inst, val, r=d_rect: setattr(r, "size", (val[0], dp(1)))
                    )
                    table_layout.add_widget(row_div)

        search_box.bind(text=lambda inst, val: (
            setattr(self, "stock_search_query", val),
            render_table_rows()
        ))

        table_scroll.add_widget(table_layout)
        inv_table_card.add_widget(table_scroll)
        content.add_widget(inv_table_card)

        render_table_rows()
        update_table_geom()
        update_filter_geom()

        scroll.add_widget(content)
        root.add_widget(scroll)

        self.root.clear_widgets()
        self.root.add_widget(root)

    def quick_add_stock_value(self, pid, pname, val):
        if not isinstance(val, int) or val <= 0:
            self.message("Invalid Quantity", "Restock quantity must be a positive integer.")
            return
        try:
            with get_db_connection(DB_PATH) as conn:
                res = conn.execute("UPDATE products SET current_stock = current_stock + ? WHERE product_id = ?", (val, pid))
                if res.rowcount != 1:
                    raise ValueError(f"Product ID '{pid}' not found.")
                new_stock = conn.execute("SELECT current_stock FROM products WHERE product_id = ?", (pid,)).fetchone()[0]
            self.invalidate_forecast_cache()
            self.message("Stock Added", f"Added +{val} to '{pname}'.\nTotal stock: {new_stock}")
            self.show_stock()
        except Exception as e:
            self.message("Error", f"Failed to add stock: {e}")

    def open_quick_restock_dialog(self, pid, pname):
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(14))
        box.add_widget(Label(text=f"Reorder stock for:\n[b]{pname}[/b] ({pid})", markup=True, font_size="13sp", color=C_DARK_TEXT, halign="center"))

        qty_input = StyledInput(text="10", input_filter="int", hint_text="Units to add", size_hint_y=None, height=dp(38))

        # Quick preset buttons row (+5, +10, +25)
        q_row = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(6))
        for add_val in [5, 10, 25]:
            btn = SecondaryButton(text=f"+{add_val}", size_hint=(0.33, 1), font_size="11sp", height=dp(28))
            btn.bind(on_release=lambda *a, v=add_val: setattr(qty_input, "text", str(v)))
            q_row.add_widget(btn)
        box.add_widget(q_row)
        box.add_widget(qty_input)

        btn_row = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(10))
        confirm_btn = PrimaryButton(text="Confirm Add", height=dp(38))
        cancel_btn = SecondaryButton(text="Cancel", height=dp(38))
        btn_row.add_widget(confirm_btn)
        btn_row.add_widget(cancel_btn)
        box.add_widget(btn_row)

        popup = Popup(title="Restock Item", content=box, size_hint=(0.88, 0.46))

        def on_confirm(*a):
            raw = qty_input.text.strip()
            if not raw:
                self.message("Invalid Quantity", "Enter a positive number of units.")
                return
            try:
                qty = int(raw)
                if qty <= 0:
                    raise ValueError
            except ValueError:
                self.message("Invalid Quantity", "Enter a positive number of units.")
                return

            try:
                with get_db_connection(DB_PATH) as conn:
                    res = conn.execute("UPDATE products SET current_stock = current_stock + ? WHERE product_id = ?", (qty, pid))
                    if res.rowcount != 1:
                        raise ValueError(f"Product '{pid}' not found.")
                    new_stock = conn.execute("SELECT current_stock FROM products WHERE product_id = ?", (pid,)).fetchone()[0]
                self.invalidate_forecast_cache()
                popup.dismiss()
                self.message("Stock Added", f"Added {qty} units to '{pname}'.\nNew total stock: {new_stock}")
                self.show_stock()
            except Exception as e:
                self.message("Database Error", f"Failed to restock: {e}")

        confirm_btn.bind(on_release=on_confirm)
        cancel_btn.bind(on_release=popup.dismiss)
        popup.open()

    # -------------------------------------------------------------
    # 4. SALES REPORT SCREEN (Revenue Analytics, Date Filters & CSV Export)
    # -------------------------------------------------------------
    def show_sales_report(self, active_tab="today", reference_date=None):
        self.sales_filter = active_tab

        # Deterministic reference date handling for isolated testing and normal operation
        ref = reference_date or getattr(self, "report_reference_date", None)
        if ref is not None:
            if isinstance(ref, str):
                ref_dt = datetime.strptime(ref, "%Y-%m-%d").date()
            elif isinstance(ref, datetime):
                ref_dt = ref.date()
            else:
                ref_dt = ref
        else:
            ref_dt = datetime.now().date()

        self.report_reference_date = ref_dt

        root = BoxLayout(orientation="vertical")
        with root.canvas.before:
            Color(*C_MAIN_BG)
            bg_rect = Rectangle(pos=root.pos, size=root.size)
        root.bind(
            pos=lambda inst, val: setattr(bg_rect, "pos", val),
            size=lambda inst, val: setattr(bg_rect, "size", val)
        )

        root.add_widget(make_screen_header("Sales Report", "Retail revenue analysis & transaction logs", self.show_dashboard))

        # Query metrics and transactions according to active filter
        today_str = ref_dt.strftime("%Y-%m-%d")
        week_ago_str = (ref_dt - timedelta(days=6)).strftime("%Y-%m-%d")

        try:
            with get_db_connection(DB_PATH) as conn:
                # Query metrics
                if active_tab == "today":
                    filter_clause = "WHERE COALESCE(s.date, SUBSTR(s.timestamp, 1, 10)) = ?"
                    params = (today_str,)
                elif active_tab == "week":
                    filter_clause = "WHERE COALESCE(s.date, SUBSTR(s.timestamp, 1, 10)) >= ? AND COALESCE(s.date, SUBSTR(s.timestamp, 1, 10)) <= ?"
                    params = (week_ago_str, today_str)
                else: # all time
                    filter_clause = ""
                    params = ()

                metrics_query = f"""
                    SELECT
                        COALESCE(SUM(s.quantity_sold * s.selling_price), 0.0) AS total_revenue,
                        COUNT(DISTINCT CASE WHEN s.bill_id IS NOT NULL AND s.bill_id != '' THEN s.bill_id ELSE 'LEGACY_' || CAST(s.sale_id AS TEXT) END) AS total_bills,
                        COALESCE(SUM(s.quantity_sold), 0) AS total_units
                    FROM sales s
                    {filter_clause}
                """
                m_row = conn.execute(metrics_query, params).fetchone()
                total_rev = float(m_row[0]) if m_row else 0.0
                total_bills = int(m_row[1]) if m_row else 0
                total_units = int(m_row[2]) if m_row else 0
                avg_bill = (total_rev / total_bills) if total_bills > 0 else 0.0

                # Query transaction rows
                tx_query = f"""
                    SELECT
                        s.sale_id,
                        CASE WHEN s.bill_id IS NOT NULL AND s.bill_id != '' THEN s.bill_id ELSE 'Bill #' || s.sale_id END AS bill_ref,
                        COALESCE(s.timestamp, s.date) AS tx_time,
                        s.date,
                        s.product_id,
                        COALESCE(p.product_name, 'Unknown') AS product_name,
                        s.quantity_sold,
                        s.selling_price,
                        (s.quantity_sold * s.selling_price) AS line_total
                    FROM sales s
                    LEFT JOIN products p ON s.product_id = p.product_id
                    {filter_clause}
                    ORDER BY s.sale_id DESC
                    LIMIT 100
                """
                tx_rows = conn.execute(tx_query, params).fetchall()

        except Exception as e:
            self.message("Database Error", str(e))
            self.show_dashboard()
            return

        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(4))
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=[dp(14), dp(12), dp(14), dp(24)], size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        # Filter Tabs Row
        filter_card = RoundedCard(bg_color=C_WHITE, padding=[dp(6), dp(6)], spacing=dp(6), size_hint_y=None, height=dp(46))
        
        tab_today = Button(text="Today", size_hint=(0.33, 1), background_normal="", font_size="12sp")
        tab_week = Button(text="Last 7 Days", size_hint=(0.33, 1), background_normal="", font_size="12sp")
        tab_all = Button(text="All Time", size_hint=(0.33, 1), background_normal="", font_size="12sp")

        for btn, key in [(tab_today, "today"), (tab_week, "week"), (tab_all, "all")]:
            if active_tab == key:
                btn.background_color = C_EMERALD
                btn.color = C_WHITE
            else:
                btn.background_color = (0.94, 0.96, 0.95, 1.0)
                btn.color = C_DARK_TEXT
            btn.bind(on_release=lambda *a, k=key: self.show_sales_report(k, reference_date=ref_dt))
            filter_card.add_widget(btn)
        content.add_widget(filter_card)

        # Top 4 Summary Metrics (2x2 Grid)
        metrics_grid = GridLayout(cols=2, spacing=dp(10), size_hint_y=None, height=dp(130))

        def make_rep_stat(title, val, sub):
            card = RoundedCard(bg_color=C_WHITE, padding=[dp(10), dp(8)], orientation="vertical", spacing=dp(2))
            t = Label(text=title, font_size="9.5sp", color=C_SEC_TEXT, halign="left", valign="middle")
            t.bind(size=t.setter("text_size"))
            v = Label(text=f"[b]{val}[/b]", markup=True, font_size="16sp", color=C_DARK_TEXT, halign="left", valign="middle")
            v.bind(size=v.setter("text_size"))
            s = Label(text=sub, font_size="9.5sp", color=C_SEC_TEXT, halign="left", valign="middle")
            s.bind(size=s.setter("text_size"))
            card.add_widget(t)
            card.add_widget(v)
            card.add_widget(s)
            return card

        sub_desc = "Today's sales" if active_tab == "today" else ("Last 7 Days sales" if active_tab == "week" else "All-time sales")
        metrics_grid.add_widget(make_rep_stat("PERIOD REVENUE", f"₹{total_rev:,.2f}", sub_desc))
        metrics_grid.add_widget(make_rep_stat("COMPLETED BILLS", str(total_bills), "Unique customers"))
        metrics_grid.add_widget(make_rep_stat("UNITS SOLD", str(total_units), "Total items sold"))
        metrics_grid.add_widget(make_rep_stat("AVG BILL VALUE", f"₹{avg_bill:,.2f}", "Revenue per bill"))
        content.add_widget(metrics_grid)

        # Export CSV Button Row
        export_row = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(10))
        export_title = Label(text=f"[b]Transactions ({len(tx_rows)})[/b]", markup=True, font_size="14.5sp", color=C_DARK_TEXT, halign="left", valign="middle")
        export_title.bind(size=export_title.setter("text_size"))
        export_row.add_widget(export_title)

        csv_btn = SecondaryButton(text="Export CSV", size_hint=(None, None), size=(dp(96), dp(32)), font_size="11sp")
        csv_btn.bind(on_release=lambda *a: self.export_sales_to_csv(active_tab, reference_date=ref_dt))
        export_row.add_widget(csv_btn)
        content.add_widget(export_row)

        # Transactions Table in RoundedCard
        tx_card = RoundedCard(bg_color=C_WHITE, padding=[dp(6), dp(8)], spacing=dp(4), size_hint_y=None)

        if not tx_rows:
            tx_card.height = dp(72)
            empty = Label(text="No transactions recorded for this period.", font_size="12sp", color=C_SEC_TEXT, halign="center", valign="middle")
            empty.bind(size=empty.setter("text_size"))
            tx_card.add_widget(empty)
        else:
            table_scroll = ScrollView(do_scroll_x=True, do_scroll_y=False, size_hint_y=None, bar_width=dp(3))
            table_layout = BoxLayout(orientation="vertical", size_hint=(None, None), spacing=dp(2))
            table_layout.bind(minimum_height=table_layout.setter("height"))

            def update_table_geom(*args):
                avail_w = max(tx_card.width - dp(12), dp(540))
                table_layout.width = avail_w
                table_scroll.width = max(tx_card.width - dp(12), dp(100))

            tx_card.bind(width=update_table_geom)
            table_layout.bind(height=lambda inst, val: (
                setattr(table_scroll, "height", val),
                setattr(tx_card, "height", val + dp(18))
            ))

            # Table Header Row
            th_bar = BoxLayout(size_hint_y=None, height=dp(32), spacing=dp(4))
            with th_bar.canvas.before:
                Color(0.92, 0.95, 0.93, 1.0)
                th_bg = RoundedRectangle(pos=th_bar.pos, size=th_bar.size, radius=[dp(6)])
            th_bar.bind(
                pos=lambda inst, val: setattr(th_bg, "pos", val),
                size=lambda inst, val: setattr(th_bg, "size", val)
            )

            def make_th_cell(title, ratio, halign):
                lbl = Label(
                    text=f"[b]{title}[/b]",
                    markup=True,
                    font_size="10.5sp",
                    color=C_DEEP_EMERALD,
                    size_hint_x=ratio,
                    halign=halign,
                    valign="middle"
                )
                lbl.bind(size=lbl.setter("text_size"))
                return lbl

            th_bar.add_widget(make_th_cell("DATE / TIME", 0.19, "left"))
            th_bar.add_widget(make_th_cell("BILL REF", 0.16, "left"))
            th_bar.add_widget(make_th_cell("PRODUCT", 0.27, "left"))
            th_bar.add_widget(make_th_cell("QTY", 0.09, "center"))
            th_bar.add_widget(make_th_cell("UNIT PRICE", 0.14, "right"))
            th_bar.add_widget(make_th_cell("TOTAL", 0.15, "right"))
            table_layout.add_widget(th_bar)

            # Table Data Rows
            for idx, tx in enumerate(tx_rows):
                sale_id, bill_ref, tx_time, date_str, pid, pname, qty, price, line_tot = tx

                # Compact bill ref
                short_bill = ("SK-" + bill_ref[-6:]) if str(bill_ref).startswith("SK-") else str(bill_ref)

                # Format time string cleanly
                time_raw = str(tx_time).replace("T", " ")
                if len(time_raw) >= 16:
                    try:
                        dt = datetime.fromisoformat(time_raw[:16])
                        time_display = dt.strftime("%d %b, %H:%M")
                    except Exception:
                        time_display = time_raw[5:16]
                else:
                    time_display = time_raw

                t_row = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(4))

                # 1. Date / Time (Left)
                c_date = Label(text=time_display, font_size="11sp", color=C_SEC_TEXT, size_hint_x=0.19, halign="left", valign="middle")
                c_date.bind(size=c_date.setter("text_size"))
                t_row.add_widget(c_date)

                # 2. Bill Reference (Left)
                c_bill = Label(text=short_bill, font_size="11sp", color=C_DARK_TEXT, size_hint_x=0.16, halign="left", valign="middle", shorten=True, shorten_from="right")
                c_bill.bind(size=c_bill.setter("text_size"))
                t_row.add_widget(c_bill)

                # 3. Product Name (Left)
                c_prod = Label(text=f"[b]{pname}[/b]", markup=True, font_size="11.5sp", color=C_DARK_TEXT, size_hint_x=0.27, halign="left", valign="middle", shorten=True, shorten_from="right")
                c_prod.bind(size=c_prod.setter("text_size"))
                t_row.add_widget(c_prod)

                # 4. Quantity (Center)
                c_qty = Label(text=str(qty), font_size="11.5sp", color=C_DARK_TEXT, size_hint_x=0.09, halign="center", valign="middle")
                c_qty.bind(size=c_qty.setter("text_size"))
                t_row.add_widget(c_qty)

                # 5. Unit Price (Right)
                c_pr = Label(text=f"₹{price:.2f}", font_size="11.5sp", color=C_SEC_TEXT, size_hint_x=0.14, halign="right", valign="middle")
                c_pr.bind(size=c_pr.setter("text_size"))
                t_row.add_widget(c_pr)

                # 6. Line Total (Right)
                c_tot = Label(text=f"[b]₹{line_tot:,.2f}[/b]", markup=True, font_size="11.5sp", color=C_EMERALD, size_hint_x=0.15, halign="right", valign="middle")
                c_tot.bind(size=c_tot.setter("text_size"))
                t_row.add_widget(c_tot)

                table_layout.add_widget(t_row)

                if idx < len(tx_rows) - 1:
                    row_div = Widget(size_hint_y=None, height=dp(1))
                    with row_div.canvas:
                        Color(*C_DIVIDER)
                        Rectangle(pos=row_div.pos, size=(row_div.width, dp(1)))
                    table_layout.add_widget(row_div)

            table_scroll.add_widget(table_layout)
            tx_card.add_widget(table_scroll)
            update_table_geom()

        content.add_widget(tx_card)

        scroll.add_widget(content)
        root.add_widget(scroll)

        self.root.clear_widgets()
        self.root.add_widget(root)

    def export_sales_to_csv(self, active_tab="today", reference_date=None, export_path=None):
        ref = reference_date or getattr(self, "report_reference_date", None)
        if ref is not None:
            if isinstance(ref, str):
                ref_dt = datetime.strptime(ref, "%Y-%m-%d").date()
            elif isinstance(ref, datetime):
                ref_dt = ref.date()
            else:
                ref_dt = ref
        else:
            ref_dt = datetime.now().date()

        today_str = ref_dt.strftime("%Y-%m-%d")
        week_ago_str = (ref_dt - timedelta(days=6)).strftime("%Y-%m-%d")

        try:
            with get_db_connection(DB_PATH) as conn:
                if active_tab == "today":
                    filter_clause = "WHERE COALESCE(s.date, SUBSTR(s.timestamp, 1, 10)) = ?"
                    params = (today_str,)
                elif active_tab == "week":
                    filter_clause = "WHERE COALESCE(s.date, SUBSTR(s.timestamp, 1, 10)) >= ? AND COALESCE(s.date, SUBSTR(s.timestamp, 1, 10)) <= ?"
                    params = (week_ago_str, today_str)
                else: # all time
                    filter_clause = ""
                    params = ()

                query = f"""
                    SELECT
                        s.sale_id,
                        CASE WHEN s.bill_id IS NOT NULL AND s.bill_id != '' THEN s.bill_id ELSE 'Bill #' || s.sale_id END AS bill_ref,
                        s.date,
                        COALESCE(s.timestamp, s.date) AS tx_time,
                        s.product_id,
                        COALESCE(p.product_name, 'Unknown') AS product_name,
                        s.quantity_sold,
                        s.selling_price,
                        (s.quantity_sold * s.selling_price) AS line_total
                    FROM sales s
                    LEFT JOIN products p ON s.product_id = p.product_id
                    {filter_clause}
                    ORDER BY s.sale_id DESC
                """
                rows = conn.execute(query, params).fetchall()

            if export_path is not None:
                export_file = Path(export_path)
                export_file.parent.mkdir(parents=True, exist_ok=True)
            else:
                export_dir = Path(__file__).parent / "exports"
                export_dir.mkdir(parents=True, exist_ok=True)
                export_file = export_dir / f"sales_report_{active_tab}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

            with open(export_file, mode="w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
                writer.writerow([
                    "Sale ID",
                    "Bill Reference",
                    "Date",
                    "Timestamp",
                    "Product ID",
                    "Product Name",
                    "Quantity Sold",
                    "Unit Price (Rs)",
                    "Line Total (Rs)"
                ])
                for r in rows:
                    writer.writerow([
                        r[0],
                        r[1],
                        r[2],
                        r[3],
                        r[4],
                        r[5],
                        int(r[6]),
                        f"{float(r[7]):.2f}",
                        f"{float(r[8]):.2f}"
                    ])

            if not rows:
                self.message("Export Notice", f"No transactions recorded for '{active_tab}'.\nEmpty report with headers saved to:\n{export_file.name}")
            else:
                self.message("Export Successful", f"Saved {len(rows)} records to:\n{export_file.name}")

            return export_file
        except Exception as e:
            self.message("Export Failed", f"Could not write CSV: {e}")
            return None

    # -------------------------------------------------------------
    # 5. AI SALES FORECAST SCREEN (Demand & Replenishment Intelligence)
    # -------------------------------------------------------------
    def show_forecast(self, refresh=False):
        if not hasattr(self, "forecast_search_query"):
            self.forecast_search_query = ""
        if not hasattr(self, "forecast_filter"):
            self.forecast_filter = "all"
        if not hasattr(self, "cached_forecast_report"):
            self.cached_forecast_report = None

        root = BoxLayout(orientation="vertical")
        with root.canvas.before:
            Color(*C_MAIN_BG)
            bg_rect = Rectangle(pos=root.pos, size=root.size)
        root.bind(
            pos=lambda inst, val: setattr(bg_rect, "pos", val),
            size=lambda inst, val: setattr(bg_rect, "size", val)
        )

        root.add_widget(make_screen_header(
            "AI Sales Forecast",
            "Demand estimation, stockout runway & replenishment intelligence",
            self.show_dashboard
        ))

        # Safe data-pipeline execution via read-only interfaces with in-memory caching
        if refresh or self.cached_forecast_report is None:
            try:
                db_target = getattr(self, "db_path", None) or DB_PATH
                prep = SalesDataPreparation(db_target, zero_fill_internal_gaps=False)
                products_raw, sales_raw = prep.load_raw_data()
                aggregated_sales, date_metadata = prep.aggregate_daily_sales(products_raw, sales_raw)
                engine = ForecastEngine(method="recent_weighted", insufficient_history_days=7)
                self.cached_forecast_report = engine.generate_forecast_report(products_raw, aggregated_sales, date_metadata)
            except Exception as e:
                self.cached_forecast_report = None
                # Helpful error fallback card if database read or forecasting fails
                err_scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(4))
                err_box = BoxLayout(orientation="vertical", spacing=dp(16), padding=dp(20), size_hint_y=None)
                err_box.bind(minimum_height=err_box.setter("height"))

                err_card = RoundedCard(
                    bg_color=C_WHITE,
                    border_color=C_DANGER,
                    padding=dp(16),
                    spacing=dp(10),
                    orientation="vertical",
                    size_hint_y=None,
                    height=dp(150)
                )
                err_title = Label(
                    text="[b]Forecasting Service Notice[/b]",
                    markup=True,
                    font_size="15sp",
                    color=C_DANGER,
                    size_hint_y=None,
                    height=dp(24),
                    halign="left"
                )
                err_title.bind(size=err_title.setter("text_size"))
                err_card.add_widget(err_title)

                err_msg = Label(
                    text=f"Unable to compute forecasts from current database records:\n{str(e)}",
                    font_size="11.5sp",
                    color=C_DARK_TEXT,
                    size_hint_y=None,
                    height=dp(44),
                    halign="left"
                )
                err_msg.bind(size=err_msg.setter("text_size"))
                err_card.add_widget(err_msg)

                ret_btn = PrimaryButton(text="Return to Dashboard", size_hint_y=None, height=dp(38))
                ret_btn.bind(on_release=lambda *a: self.show_dashboard())
                err_card.add_widget(ret_btn)

                err_box.add_widget(err_card)
                err_scroll.add_widget(err_box)
                root.add_widget(err_scroll)

                self.root.clear_widgets()
                self.root.add_widget(root)
                return

        report = self.cached_forecast_report
        forecast_items = report.products_forecast

        total_prods = len(forecast_items)
        risk_7d_items = [p for p in forecast_items if p.is_7_day_stockout_risk]
        restock_items = [p for p in forecast_items if p.is_restock_recommended]
        at_reorder_items = [p for p in forecast_items if p.is_at_reorder_point]
        safe_items = [p for p in forecast_items if (not p.is_7_day_stockout_risk) and (not p.is_restock_recommended) and (not p.is_at_reorder_point)]

        active_days = max((p.historical_active_days for p in forecast_items), default=0)
        if active_days == 0 and report.total_calendar_days > 0:
            active_days = report.total_calendar_days
        if active_days == 0:
            active_days = 4

        scroll = ScrollView(do_scroll_x=False, do_scroll_y=True, bar_width=dp(4))
        content = BoxLayout(orientation="vertical", spacing=dp(12), padding=[dp(14), dp(12), dp(14), dp(24)], size_hint_y=None)
        content.bind(minimum_height=content.setter("height"))

        # -------------------------------------------------------------
        # 1. SUMMARY KPI CARDS (Next-Day & 7-Day Revenue/Units + Catalog Status)
        # -------------------------------------------------------------
        def make_forecast_stat(title, val, sub, val_col):
            b = RoundedCard(bg_color=C_WHITE, padding=[dp(8), dp(6)], orientation="vertical", spacing=dp(2))
            tl = Label(text=title, font_size="9sp", color=C_SEC_TEXT, halign="center", valign="middle")
            tl.bind(size=tl.setter("text_size"))
            vl = Label(text=f"[b]{val}[/b]", markup=True, font_size="15.5sp", color=val_col, halign="center", valign="middle")
            vl.bind(size=vl.setter("text_size"))
            sl = Label(text=sub, font_size="8.5sp", color=C_SEC_TEXT, halign="center", valign="middle")
            sl.bind(size=sl.setter("text_size"))
            b.add_widget(tl)
            b.add_widget(vl)
            b.add_widget(sl)
            return b

        # Row 1: Estimated Projections (Next-day and 7-day revenue & units)
        forecast_kpi_grid = GridLayout(cols=2, spacing=dp(8), size_hint_y=None, height=dp(136))
        forecast_kpi_grid.add_widget(make_forecast_stat(
            "NEXT-DAY ESTIMATED REVENUE",
            f"₹{report.estimated_daily_revenue:,.2f}",
            "projected revenue / day",
            C_DEEP_EMERALD
        ))
        forecast_kpi_grid.add_widget(make_forecast_stat(
            "NEXT-DAY ESTIMATED UNITS",
            f"{report.estimated_daily_units:.1f} units",
            "projected unit demand / day",
            C_DEEP_EMERALD
        ))
        forecast_kpi_grid.add_widget(make_forecast_stat(
            "7-DAY ESTIMATED REVENUE",
            f"₹{report.estimated_next_7_days_revenue:,.2f}",
            "projected 7-day revenue",
            C_EMERALD
        ))
        forecast_kpi_grid.add_widget(make_forecast_stat(
            "7-DAY ESTIMATED UNITS",
            f"{report.estimated_next_7_days_units:.1f} units",
            "projected 7-day demand",
            C_EMERALD
        ))
        content.add_widget(forecast_kpi_grid)

        # Row 2: Catalog Inventory Status
        inventory_kpi_grid = GridLayout(cols=3, spacing=dp(8), size_hint_y=None, height=dp(68))
        inventory_kpi_grid.add_widget(make_forecast_stat("CATALOG PRODUCTS", str(total_prods), "in active catalog", C_DARK_TEXT))
        inventory_kpi_grid.add_widget(make_forecast_stat(
            "7-DAY STOCK RISK",
            str(len(risk_7d_items)),
            "demand > stock",
            C_DANGER if risk_7d_items else C_SUCCESS
        ))
        inventory_kpi_grid.add_widget(make_forecast_stat(
            "RESTOCK NEEDED",
            str(len(restock_items)),
            "below reorder pt",
            C_WARNING if restock_items else C_SUCCESS
        ))
        content.add_widget(inventory_kpi_grid)

        # -------------------------------------------------------------
        # 2. PRELIMINARY BASELINE & REFRESH BANNER
        # -------------------------------------------------------------
        disc_card = RoundedCard(
            bg_color=C_PALE_SURFACE,
            radius=dp(10),
            border_color=C_SOFT_MINT,
            orientation="vertical",
            padding=[dp(12), dp(10)],
            spacing=dp(6),
            size_hint_y=None
        )
        disc_card.bind(minimum_height=disc_card.setter("height"))

        disc_header = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(6))
        disc_tag = Label(
            text=f"[b]PRELIMINARY BASELINE — only {active_days} active trading days[/b]",
            markup=True,
            font_size="11sp",
            color=C_DEEP_EMERALD,
            size_hint_x=0.68,
            halign="left",
            valign="middle"
        )
        disc_tag.bind(size=disc_tag.setter("text_size"))
        disc_header.add_widget(disc_tag)

        refresh_btn = SecondaryButton(
            text="↻ Refresh Forecast",
            size_hint=(None, None),
            size=(dp(125), dp(30)),
            font_size="10.5sp"
        )
        refresh_btn.bind(on_release=lambda *a: self.show_forecast(refresh=True))
        disc_header.add_widget(refresh_btn)
        disc_card.add_widget(disc_header)

        method_lbl = Label(
            text=f"Primary Baseline: {report.forecast_method.replace('_', ' ').title()} (WMA)  •  Offline-First Pure Python",
            font_size="9.5sp",
            color=C_SEC_TEXT,
            size_hint_y=None,
            height=dp(16),
            halign="left",
            valign="middle"
        )
        method_lbl.bind(size=method_lbl.setter("text_size"))
        disc_card.add_widget(method_lbl)

        disc_body = Label(
            text=(
                "EXPERIMENTAL BASELINE: Statistical weighted moving averages on active sales days. "
                "These projections provide transparent inventory replenishment guidance, not guaranteed predictions. "
                f"Model evaluation metrics (MAE, RMSE, MAPE) are withheld because history is insufficient ({active_days} active days < 14-day threshold)."
            ),
            font_size="10sp",
            color=C_DARK_TEXT,
            size_hint_y=None,
            height=dp(42),
            halign="left",
            valign="top"
        )
        disc_body.bind(size=disc_body.setter("text_size"))
        disc_card.add_widget(disc_body)
        content.add_widget(disc_card)

        # -------------------------------------------------------------
        # 3. SEARCH & FILTER CONTROLS
        # -------------------------------------------------------------
        sec_tbl_hdr = BoxLayout(size_hint_y=None, height=dp(26), spacing=dp(8))
        tbl_title = Label(
            text="[b]Product Demand Forecast & Runway Table[/b]",
            markup=True,
            font_size="15sp",
            color=C_DARK_TEXT,
            halign="left",
            valign="middle"
        )
        tbl_title.bind(size=tbl_title.setter("text_size"))
        sec_tbl_hdr.add_widget(tbl_title)

        tbl_count_lbl = Label(text="", font_size="11sp", color=C_SEC_TEXT, halign="right", valign="middle")
        tbl_count_lbl.bind(size=tbl_count_lbl.setter("text_size"))
        sec_tbl_hdr.add_widget(tbl_count_lbl)
        content.add_widget(sec_tbl_hdr)

        ctrl_card = RoundedCard(bg_color=C_WHITE, padding=[dp(10), dp(10)], spacing=dp(8), size_hint_y=None, height=dp(90), orientation="vertical")
        search_box = StyledInput(text=self.forecast_search_query, hint_text="Search by product name or product ID...", size_hint_y=None, height=dp(34))
        ctrl_card.add_widget(search_box)

        filter_scroll = ScrollView(do_scroll_x=True, do_scroll_y=False, size_hint_y=None, height=dp(30), bar_width=0)
        filter_row = BoxLayout(spacing=dp(6), size_hint=(None, 1))

        tab_all = Button(text=f"All ({total_prods})", size_hint=(0.25, 1), background_normal="", font_size="10.5sp")
        tab_risk = Button(text=f"7-Day Risk ({len(risk_7d_items)})", size_hint=(0.25, 1), background_normal="", font_size="10.5sp")
        tab_restock = Button(text=f"Restock Needed ({len(restock_items)})", size_hint=(0.25, 1), background_normal="", font_size="10.5sp")
        tab_safe = Button(text=f"Safe ({len(safe_items)})", size_hint=(0.25, 1), background_normal="", font_size="10.5sp")

        filter_buttons = [
            (tab_all, "all"),
            (tab_risk, "risk"),
            (tab_restock, "restock"),
            (tab_safe, "safe")
        ]

        def update_tab_buttons():
            for btn, key in filter_buttons:
                if self.forecast_filter == key:
                    btn.background_color = C_EMERALD
                    btn.color = C_WHITE
                else:
                    btn.background_color = (0.94, 0.96, 0.95, 1.0)
                    btn.color = C_DARK_TEXT

        def update_filter_geom(*args):
            avail_w = max(ctrl_card.width - dp(20), dp(440))
            filter_row.width = avail_w
            filter_scroll.width = max(ctrl_card.width - dp(20), dp(100))

        ctrl_card.bind(width=update_filter_geom)

        for btn, key in filter_buttons:
            def on_tab_click(*a, k=key):
                self.forecast_filter = k
                update_tab_buttons()
                render_table_rows()
            btn.bind(on_release=on_tab_click)
            filter_row.add_widget(btn)

        update_tab_buttons()
        filter_scroll.add_widget(filter_row)
        ctrl_card.add_widget(filter_scroll)
        content.add_widget(ctrl_card)

        # -------------------------------------------------------------
        # 4. HORIZONTALLY SCROLLABLE FORECAST TABLE CARD
        # -------------------------------------------------------------
        table_card = RoundedCard(bg_color=C_WHITE, padding=[dp(8), dp(8)], spacing=dp(4), size_hint_y=None)
        table_scroll = ScrollView(do_scroll_x=True, do_scroll_y=False, size_hint_y=None, bar_width=dp(3))
        table_layout = BoxLayout(orientation="vertical", size_hint=(None, None), spacing=dp(2))
        table_layout.bind(minimum_height=table_layout.setter("height"))

        def update_table_geom(*args):
            avail_w = max(table_card.width - dp(16), dp(860))
            table_layout.width = avail_w
            table_scroll.width = max(table_card.width - dp(16), dp(100))

        table_card.bind(width=update_table_geom)
        table_layout.bind(height=lambda inst, val: (
            setattr(table_scroll, "height", val),
            setattr(table_card, "height", val + dp(18))
        ))

        # Table Header Row (Consistent 8-Column Layout)
        th_bar = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(4), padding=[dp(6), dp(0)])
        with th_bar.canvas.before:
            Color(0.92, 0.95, 0.93, 1.0)
            th_bg = RoundedRectangle(pos=th_bar.pos, size=th_bar.size, radius=[dp(6)])
        th_bar.bind(
            pos=lambda inst, val: setattr(th_bg, "pos", val),
            size=lambda inst, val: setattr(th_bg, "size", val)
        )

        def make_th_cell(title, ratio, halign):
            lbl = Label(
                text=f"[b]{title}[/b]",
                markup=True,
                font_size="10sp",
                color=C_DEEP_EMERALD,
                size_hint_x=ratio,
                halign=halign,
                valign="middle"
            )
            lbl.bind(size=lbl.setter("text_size"))
            return lbl

        th_bar.add_widget(make_th_cell("PRODUCT", 0.22, "left"))
        th_bar.add_widget(make_th_cell("STOCK", 0.10, "center"))
        th_bar.add_widget(make_th_cell("DAILY DEMAND", 0.11, "center"))
        th_bar.add_widget(make_th_cell("7-DAY DEMAND", 0.11, "center"))
        th_bar.add_widget(make_th_cell("RUNWAY", 0.10, "center"))
        th_bar.add_widget(make_th_cell("REORDER PT", 0.11, "center"))
        th_bar.add_widget(make_th_cell("LEAD-TIME STATUS", 0.13, "center"))
        th_bar.add_widget(make_th_cell("7-DAY RISK", 0.12, "center"))

        def render_table_rows():
            table_layout.clear_widgets()
            table_layout.add_widget(th_bar)

            q = self.forecast_search_query.strip().lower()
            filtered = []
            for item in forecast_items:
                if q and (q not in item.product_name.lower() and q not in item.product_id.lower()):
                    continue
                if self.forecast_filter == "risk" and not item.is_7_day_stockout_risk:
                    continue
                if self.forecast_filter == "restock" and not item.is_restock_recommended:
                    continue
                if self.forecast_filter == "safe" and (item.is_7_day_stockout_risk or item.is_restock_recommended or item.is_at_reorder_point):
                    continue
                filtered.append(item)

            tbl_count_lbl.text = f"Showing {len(filtered)} of {total_prods} products"

            if not filtered:
                empty_row = BoxLayout(size_hint_y=None, height=dp(54))
                empty_lbl = Label(text="No products match the selected filter or search query.", font_size="12sp", color=C_SEC_TEXT, halign="center", valign="middle")
                empty_lbl.bind(size=empty_lbl.setter("text_size"))
                empty_row.add_widget(empty_lbl)
                table_layout.add_widget(empty_row)
                return

            for idx, item in enumerate(filtered):
                t_row = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(4), padding=[dp(6), dp(0)])

                # 1. Product (ID & Name)
                p_col = BoxLayout(orientation="vertical", size_hint_x=0.22, spacing=dp(1), pos_hint={"center_y": 0.5})
                pid_lbl = Label(text=f"[b]{item.product_id}[/b]", markup=True, font_size="11sp", color=C_DEEP_EMERALD, size_hint_y=None, height=dp(18), halign="left", valign="middle")
                pid_lbl.bind(size=pid_lbl.setter("text_size"))
                pname_lbl = Label(text=item.product_name, font_size="11sp", color=C_DARK_TEXT, size_hint_y=None, height=dp(18), halign="left", valign="middle", shorten=True, shorten_from="right")
                pname_lbl.bind(size=pname_lbl.setter("text_size"))
                p_col.add_widget(pid_lbl)
                p_col.add_widget(pname_lbl)
                t_row.add_widget(p_col)

                # 2. Current Stock
                c_stock = Label(text=f"[b]{item.current_stock}[/b] units", markup=True, font_size="11sp", color=C_DARK_TEXT, size_hint_x=0.10, halign="center", valign="middle")
                c_stock.bind(size=c_stock.setter("text_size"))
                t_row.add_widget(c_stock)

                # 3. Estimated Daily Demand (Show "No observed demand" if 0)
                if item.estimated_daily_demand > 0:
                    daily_txt = f"{item.estimated_daily_demand:.2f} / day"
                    daily_col = C_DARK_TEXT
                else:
                    daily_txt = "No observed demand"
                    daily_col = C_SEC_TEXT
                c_daily = Label(text=daily_txt, font_size="10.5sp", color=daily_col, size_hint_x=0.11, halign="center", valign="middle")
                c_daily.bind(size=c_daily.setter("text_size"))
                t_row.add_widget(c_daily)

                # 4. Estimated 7-Day Demand
                if item.estimated_next_7_days_demand > 0:
                    d7_txt = f"{item.estimated_next_7_days_demand:.2f} units"
                    d7_col = C_DARK_TEXT
                else:
                    d7_txt = "No observed demand"
                    d7_col = C_SEC_TEXT
                c_7d = Label(text=d7_txt, font_size="10.5sp", color=d7_col, size_hint_x=0.11, halign="center", valign="middle")
                c_7d.bind(size=c_7d.setter("text_size"))
                t_row.add_widget(c_7d)

                # 5. Stockout Runway
                if item.stockout_runway_days is not None and item.estimated_daily_demand > 0:
                    runway_val = item.stockout_runway_days
                    runway_txt = f"{runway_val:.1f} days"
                    if runway_val <= 3.0:
                        runway_col = C_DANGER
                    elif runway_val <= 7.0:
                        runway_col = C_WARNING
                    else:
                        runway_col = C_SUCCESS
                else:
                    runway_txt = "No observed demand"
                    runway_col = C_SEC_TEXT

                c_runway = Label(text=f"[b]{runway_txt}[/b]", markup=True, font_size="10.5sp", color=runway_col, size_hint_x=0.10, halign="center", valign="middle")
                c_runway.bind(size=c_runway.setter("text_size"))
                t_row.add_widget(c_runway)

                # 6. Reorder Point (Threshold)
                reorder_col = BoxLayout(orientation="vertical", size_hint_x=0.11, spacing=dp(1), pos_hint={"center_y": 0.5})
                ro_pt_lbl = Label(text=f"[b]{item.reorder_point}[/b] units", markup=True, font_size="11sp", color=C_DARK_TEXT, size_hint_y=None, height=dp(18), halign="center", valign="middle")
                ro_pt_lbl.bind(size=ro_pt_lbl.setter("text_size"))
                ro_sub_lbl = Label(text=f"Lead:{item.supplier_lead_days}d Safe:{item.safety_stock}", font_size="8.5sp", color=C_SEC_TEXT, size_hint_y=None, height=dp(16), halign="center", valign="middle")
                ro_sub_lbl.bind(size=ro_sub_lbl.setter("text_size"))
                reorder_col.add_widget(ro_pt_lbl)
                reorder_col.add_widget(ro_sub_lbl)
                t_row.add_widget(reorder_col)

                # 7. Lead-Time Reorder Status (Policy Decision)
                badge_box_lt = BoxLayout(size_hint_x=0.13, padding=[dp(2), dp(6)])
                if item.is_restock_recommended:
                    badge_bg_lt = (0.98, 0.90, 0.90, 1.0)
                    badge_fg_lt = C_DANGER
                    badge_txt_lt = f"RESTOCK (+{item.suggested_order_quantity})"
                elif item.is_at_reorder_point:
                    badge_bg_lt = (1.0, 0.96, 0.88, 1.0)
                    badge_fg_lt = C_WARNING
                    badge_txt_lt = "AT THRESHOLD"
                else:
                    badge_bg_lt = (0.90, 0.97, 0.92, 1.0)
                    badge_fg_lt = C_SUCCESS
                    badge_txt_lt = "SUFFICIENT"

                inner_badge_lt = BoxLayout(pos_hint={"center_y": 0.5})
                with inner_badge_lt.canvas.before:
                    Color(*badge_bg_lt)
                    b_rect_lt = RoundedRectangle(pos=inner_badge_lt.pos, size=inner_badge_lt.size, radius=[dp(6)])
                inner_badge_lt.bind(
                    pos=lambda inst, val, r=b_rect_lt: setattr(r, "pos", val),
                    size=lambda inst, val, r=b_rect_lt: setattr(r, "size", val)
                )
                b_lbl_lt = Label(text=f"[b]{badge_txt_lt}[/b]", markup=True, font_size="9sp", color=badge_fg_lt, halign="center", valign="middle")
                b_lbl_lt.bind(size=b_lbl_lt.setter("text_size"))
                inner_badge_lt.add_widget(b_lbl_lt)
                badge_box_lt.add_widget(inner_badge_lt)
                t_row.add_widget(badge_box_lt)

                # 8. 7-Day Stockout Risk Status (Planning Horizon)
                badge_box_7d = BoxLayout(size_hint_x=0.12, padding=[dp(2), dp(6)])
                if item.is_7_day_stockout_risk:
                    badge_bg_7d = (0.98, 0.90, 0.90, 1.0)
                    badge_fg_7d = C_DANGER
                    badge_txt_7d = f"DEFICIT ({item.demand_7_day_deficit:.1f})"
                else:
                    badge_bg_7d = (0.90, 0.97, 0.92, 1.0)
                    badge_fg_7d = C_SUCCESS
                    badge_txt_7d = "SAFE"

                inner_badge_7d = BoxLayout(pos_hint={"center_y": 0.5})
                with inner_badge_7d.canvas.before:
                    Color(*badge_bg_7d)
                    b_rect_7d = RoundedRectangle(pos=inner_badge_7d.pos, size=inner_badge_7d.size, radius=[dp(6)])
                inner_badge_7d.bind(
                    pos=lambda inst, val, r=b_rect_7d: setattr(r, "pos", val),
                    size=lambda inst, val, r=b_rect_7d: setattr(r, "size", val)
                )
                b_lbl_7d = Label(text=f"[b]{badge_txt_7d}[/b]", markup=True, font_size="9sp", color=badge_fg_7d, halign="center", valign="middle")
                b_lbl_7d.bind(size=b_lbl_7d.setter("text_size"))
                inner_badge_7d.add_widget(b_lbl_7d)
                badge_box_7d.add_widget(inner_badge_7d)
                t_row.add_widget(badge_box_7d)

                table_layout.add_widget(t_row)

                if idx < len(filtered) - 1:
                    divider = Widget(size_hint_y=None, height=dp(1))
                    with divider.canvas:
                        Color(*C_DIVIDER)
                        div_rect = Rectangle(pos=divider.pos, size=(divider.width, dp(1)))
                    divider.bind(
                        pos=lambda inst, val, r=div_rect: setattr(r, "pos", val),
                        size=lambda inst, val, r=div_rect, d=divider: setattr(r, "size", (d.width, dp(1)))
                    )
                    table_layout.add_widget(divider)

        search_box.bind(text=lambda inst, val: (
            setattr(self, "forecast_search_query", val),
            render_table_rows()
        ))

        table_scroll.add_widget(table_layout)
        table_card.add_widget(table_scroll)
        content.add_widget(table_card)
        update_table_geom()
        render_table_rows()

        # Action Buttons: Jump to Stock Management + Refresh action
        action_btn_box = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(10))
        restock_nav_btn = PrimaryButton(text="Open Stock Management to Restock Items", size_hint=(0.7, 1), height=dp(42))
        restock_nav_btn.bind(on_release=lambda *a: self.open_section("Stock Management"))
        action_btn_box.add_widget(restock_nav_btn)

        ref_btn_bottom = SecondaryButton(text="↻ Refresh Forecast Data", size_hint=(0.3, 1), height=dp(42))
        ref_btn_bottom.bind(on_release=lambda *a: self.show_forecast(refresh=True))
        action_btn_box.add_widget(ref_btn_bottom)
        content.add_widget(action_btn_box)

        scroll.add_widget(content)
        root.add_widget(scroll)

        self.root.clear_widgets()
        self.root.add_widget(root)

    def logout(self, instance=None):
        self.show_login()


if __name__ == "__main__":
    SmartKadaiApp().run()
