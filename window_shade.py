"""창 제목 표시줄 더블클릭으로 창을 접었다/펴는 기능 (Windows 전용).

- 제목 표시줄을 더블클릭하면 제목만 남기고 접는다. 접힌 창은 제목을 12글자까지만 보여 주고 가로 폭도 줄인다.
- 접힌 창을 더블클릭하면 그 제목 칸 바로 아래에서 원래 크기로 펼친다. 옆에 펼쳐진 창과 겹치면 오른쪽으로 민다.
  그래서 우측의 다른 접힌 창 제목을 가리지 않는다.
- 펼친 창을 다시 더블클릭하면 처음 접혀 있던 제목 칸 위치로 돌아간다.
- 제목 표시줄 자체를 그대로 쓰므로 드래그 이동은 기존과 똑같다.
- 최대화된 상태에서는 기존처럼 더블클릭이 일반 크기 복원으로 동작한다.

사용법: root를 만든 뒤 `shade = install_title_shade(root)` 한 줄만 추가한다.
창 위치를 저장할 때는 `root.geometry()` 대신 `shade.geometry()` 를 쓴다(접힌 상태에서도 펼친 크기를 저장).
창 목록은 %APPDATA%\\WindowShade\\collapsed.json 에 공유하며, QuickLauncher(C#)도 같은 형식을 쓴다.
"""
import atexit
import ctypes
import json
import os
import queue
import sys
import time
from ctypes import wintypes
from tkinter import font as tkfont

# WinDLL은 호출 동안 GIL을 놓는다. 제목 표시줄을 끄는 동안 Windows의 이동 루프가 콜백 안에서 돌기 때문에,
# GIL을 쥐고 있으면 이동 중에 화면이 멈춘다.
user32 = ctypes.WinDLL("user32", use_last_error=True)

WM_NCLBUTTONDOWN = 0x00A1
WM_NCLBUTTONUP = 0x00A2
WM_NCLBUTTONDBLCLK = 0x00A3
DBL_GUARD_SEC = 0.6  # 접힌 칸을 한 번 클릭해 펼친 뒤 이어지는 두 번째 클릭은 접기로 보지 않는다
WM_SYSCOMMAND = 0x0112
SC_MAXIMIZE = 0xF030
HTCAPTION = 2
GWLP_WNDPROC = -4
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
WM_CLOSE = 0x0010
GWL_HWNDPARENT = -8
WS_POPUP = 0x80000000
SM_CYCAPTION = 4  # 제목 표시줄 높이 (단추 한 개의 가로 길이는 높이의 두 배로 본다)
SM_CXSMICON = 49  # 작은 아이콘의 가로 길이
SHADE_TITLE_LEN = 12  # 접힌 상태에서 보여 줄 제목 글자 수 (띄어쓰기 포함)
TEXT_MARGIN = 1.25  # Windows 제목 글꼴이 Tk 측정값보다 넓어서 여유를 둔다
VK_LBUTTON = 0x01  # 마우스 왼쪽 버튼이 지금 눌려 있는지 확인할 때 쓴다
VK_RBUTTON = 0x02
IDLE_COLLAPSE_SEC = 20.0  # 배지에서 펼친 뒤 클릭·이동이 이만큼 없으면 배지로 되돌린다
POLL_MS = 50
SYNC_EVERY = 3  # POLL_MS 세 번마다(150ms) 공유 목록을 갱신한다
STALE_SEC = 3.0  # 이 시간 동안 갱신이 없으면 죽은 창으로 보고 목록에서 뺀다
GAP = 4  # 접힌 제목 칸과 펼친 창 사이, 그리고 옆 창과의 간격
TAB_WIDTH = 344  # 접힌 제목 칸의 가로 길이 (모든 프로그램 동일: 3종세트가 빈틈없이 붙도록)

REGISTRY_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "WindowShade")
REGISTRY_FILE = os.path.join(REGISTRY_DIR, "collapsed.json")

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
user32.SetWindowLongPtrW.restype = ctypes.c_void_p
user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CallWindowProcW.restype = ctypes.c_ssize_t
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetSystemMetrics.restype = ctypes.c_int
user32.IsZoomed.argtypes = [wintypes.HWND]
user32.IsZoomed.restype = wintypes.BOOL
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
user32.CreateWindowExW.restype = wintypes.HWND
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL


def _read_registry():
    """살아 있는 창 목록을 읽는다. 파일이 쓰이는 중이면 빈 목록으로 본다."""
    try:
        with open(REGISTRY_FILE, encoding="utf-8") as f:
            entries = json.load(f)
    except (OSError, ValueError):
        return {}
    now = time.time()
    return {key: e for key, e in entries.items() if now - e.get("ts", 0) < STALE_SEC}


def _write_registry(entries):
    os.makedirs(REGISTRY_DIR, exist_ok=True)
    tmp = f"{REGISTRY_FILE}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False)
    os.replace(tmp, REGISTRY_FILE)


def find_running_exe(app_id):
    """같은 프로그램(app_id)이 실행 중이면 그 실행 파일 경로를 돌려준다."""
    for e in _read_registry().values():
        if e.get("app") == app_id and e.get("exe"):
            return e["exe"]
    return None


def close_other_instances(app_id, timeout=3.0):
    """같은 프로그램의 기존 실행본을 정상 종료(창 닫기)시킨다. 새로 실행한 쪽이 기존 것을 대신한다."""
    # 기다리지 않는다: 여러 개가 동시에 뜰 때 서로를 기다리다 둘 다 시작하지 못하는 것을 막기 위해서다.
    mine = os.getpid()
    for e in _read_registry().values():
        if e.get("app") == app_id and e.get("pid") != mine:
            user32.PostMessageW(e["hwnd"], WM_CLOSE, 0, 0)


def tab_slot_from_argv():
    """--tab-x=N --tab-y=N 이 있으면 (x, y) 를 돌려준다. 있으면 접힌 제목 칸으로 시작한다."""
    import sys
    values = {}
    for arg in sys.argv[1:]:
        if arg.startswith(("--tab-x=", "--tab-y=")):
            key, _, value = arg[2:].partition("=")
            values[key] = int(value)
    if "tab-x" in values and "tab-y" in values:
        return values["tab-x"], values["tab-y"]
    return None


def hide_from_taskbar(root):
    """창을 작업표시줄에서 뺀다. 숨겨진 소유자 창을 붙이는 방법이라 창 모양(제목 표시줄)은 그대로 둔다."""
    root.update_idletasks()
    owner = user32.CreateWindowExW(0, "Static", "owner", WS_POPUP, 0, 0, 0, 0, None, None, None, None)
    user32.SetWindowLongPtrW(user32.GetParent(root.winfo_id()), GWL_HWNDPARENT, owner)
    return owner


def _log_tray_error(error):
    try:
        os.makedirs(REGISTRY_DIR, exist_ok=True)
        with open(os.path.join(REGISTRY_DIR, "tray_error.txt"), "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {type(error).__name__}: {error}\n")
    except OSError:
        pass


class Tray:
    """작업표시줄 오른쪽 트레이 아이콘. 왼쪽 클릭/"열기"는 창을 보이게, "종료"는 프로그램을 끝낸다.
    pystray가 없으면 available 이 False 이고, 프로그램은 창을 숨기지 않는다."""

    def __init__(self, root, title):
        self.root = root
        self.queue = queue.Queue()
        self.icon = None
        try:
            import pystray
            from PIL import Image, ImageDraw
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            ImageDraw.Draw(img).ellipse([2, 2, 61, 61], fill=(47, 125, 209, 255))
            self.icon = pystray.Icon(
                title, img, title,
                menu=pystray.Menu(
                    pystray.MenuItem("열기", lambda: self.queue.put("show"), default=True),
                    pystray.MenuItem("종료", lambda: self.queue.put("quit")),
                ),
            )
            self.icon.run_detached()
        except Exception as e:  # 트레이를 만들지 못하면 창을 숨기지 않는다
            self.icon = None
            _log_tray_error(e)
            return
        # 창이 닫히면(창 닫기, 다른 실행본이 닫음) 트레이 아이콘도 함께 없앤다. 남으면 프로그램이 끝나지 않는다.
        root.bind("<Destroy>", self._on_destroy, add="+")
        root.after(100, self._pump)

    def _on_destroy(self, event):
        if event.widget is self.root and self.icon is not None:
            try:
                self.icon.stop()
            except Exception as e:
                _log_tray_error(e)
            self.icon = None

    @property
    def available(self):
        return self.icon is not None

    def _pump(self):
        while True:
            try:
                action = self.queue.get_nowait()
            except queue.Empty:
                break
            if action == "show":
                self.root.deiconify()
                self.root.lift()
            elif action == "quit":
                self._quit()
                return
        self.root.after(100, self._pump)

    def _quit(self):
        self.icon.stop()
        command = self.root.protocol("WM_DELETE_WINDOW")  # 창의 닫기 처리(저장 포함)를 그대로 거친다
        if command:
            self.root.tk.call(command)
        else:
            self.root.destroy()


def _overlaps(a, b):
    """두 사각형 (x, y, w, h) 이 겹치는지."""
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


class TitleShade:
    def __init__(self, root, set_content_visible=None, app_id=None):
        self.root = root
        self.app_id = app_id  # 같은 프로그램을 구분하는 이름 (중복 실행 시 기존 것을 닫는 데 쓴다)
        # Tk 창의 실제 최상위 창(제목 표시줄을 가진 프레임)
        self.hwnd = user32.GetParent(root.winfo_id())
        self.full_title = root.title()
        self.key = f"{os.getpid()}-{self.hwnd}"
        self.started = time.time()  # 먼저 뜬 실행본은 나중에 뜬 같은 프로그램이 닫는다
        self.set_content_visible = set_content_visible  # 크기를 바꾸는 동안 내용을 숨겨 다시 그리는 비용을 줄인다
        self.saved = None  # 펼친 크기 (바깥 가로, 바깥 세로, 클라이언트 가로, 클라이언트 세로)
        self.tab_pos = None  # 접힌 제목 칸의 위치 (펼칠 때 기억해 두었다가 다시 접을 때 돌아간다)
        self.pending_toggle = False  # 제목 칸을 한 번 클릭함 (펼치기/접기는 Tk 주기 확인 때 한다)
        self._press_pos = None  # 제목 칸을 누른 자리 (끌어서 옮긴 것과 클릭을 구분한다)
        self._press_active = False  # 제목 칸을 누르고 있는 중
        self._expanded_at = 0.0
        self._min = None  # 접는 동안 줄여 둔 최소 크기 (펼치면 되돌린다)
        self._title_shortened = False  # 접힌 동안 제목을 줄여 두었는지
        self._content_hidden = False  # 내용을 숨겨 둔 상태 (다음 주기에 다시 보여 준다)
        self._auto_collapse = False  # 배지에서 펼친 상태: 한동안 조작이 없으면 배지로 되돌린다
        self._last_activity = 0.0
        self._last_rect = None
        self._tick = 0
        self._proc = WNDPROC(self._wndproc)  # 가비지 수집되지 않도록 보관
        self._old_proc = user32.SetWindowLongPtrW(self.hwnd, GWLP_WNDPROC,
                                                  ctypes.cast(self._proc, ctypes.c_void_p))
        atexit.register(self._unpublish)
        root.after(POLL_MS, self._poll)

    @property
    def shaded(self):
        return self.saved is not None

    def geometry(self):
        """창 위치/크기 저장용 Tk 지오메트리 문자열. 접힌 상태면 펼친 크기를 돌려준다."""
        if not self.saved:
            return self.root.geometry()
        _, _, client_w, client_h = self.saved
        left, top = self._position()
        return f"{client_w}x{client_h}+{left}+{top}"

    def _wndproc(self, hwnd, msg, wparam, lparam):
        # 이 콜백 안에서는 Tk 명령을 부르지 않는다. 표시만 바꾸고 나머지는 _poll 에서 처리한다.
        if msg == WM_NCLBUTTONDOWN and wparam == HTCAPTION:
            # 실제 마우스로 누르면 Windows가 끌기 루프를 돌리면서 버튼 놓기 메시지를 가져가 버린다.
            # 그래서 놓았는지는 주기 확인(_poll_once)에서 실제 버튼 상태로 본다.
            self._press_pos = self._position()
            self._press_active = True
        if msg == WM_NCLBUTTONDBLCLK and wparam == HTCAPTION and not user32.IsZoomed(hwnd):
            return 0  # 기본 동작(최대화)을 막는다. 클릭 두 번은 위의 한 번 클릭 동작으로 처리한다
        if msg == WM_SYSCOMMAND and (wparam & 0xFFF0) == SC_MAXIMIZE and self.shaded:
            self._expand_in_place()  # 접힌 상태에서 최대화 단추를 누르면 먼저 펼친다
        return user32.CallWindowProcW(self._old_proc, hwnd, msg, wparam, lparam)

    def _poll(self):
        try:
            self._poll_once()
        except Exception as e:  # 한 번 실패해도 주기 확인이 멈추지 않게 한다
            _log_tray_error(e)
        self.root.after(POLL_MS, self._poll)

    def _poll_once(self):
        if self._press_active and not (user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000):
            self._press_active = False  # 버튼을 놓았다: 끌지 않았으면 한 번 클릭으로 본다
            if self._position() == self._press_pos and time.time() - self._expanded_at > DBL_GUARD_SEC:
                self.pending_toggle = True  # 제목 칸을 한 번 클릭: 펼치거나 접는다
        if self._auto_collapse and not self.shaded:
            if self._had_activity():
                self._last_activity = time.time()
            elif time.time() - self._last_activity > IDLE_COLLAPSE_SEC:
                self._auto_collapse = False
                self.pending_toggle = True  # 조작이 없었으므로 배지로 되돌린다
        if self.pending_toggle:
            self.pending_toggle = False
            if self.shaded:
                self._expand()
            else:
                self._auto_collapse = False
                self._collapse()
            self._expanded_at = time.time()  # 이어지는 두 번째 클릭이 다시 토글하지 않도록 잠깐 막는다
        if self._content_hidden and not self.shaded and self.set_content_visible:
            self.set_content_visible(True)
            self._content_hidden = False
        if not self.shaded:
            if self._title_shortened:
                self.root.title(self.full_title)
                self._title_shortened = False
            if self._min:
                self.root.wm_minsize(*self._min)  # 최소 크기 제한 때문에 접히지 않는 것을 막기 위해 잠깐 풀어 둔 값
                self._min = None
        self._tick += 1
        if self._tick % SYNC_EVERY == 0:
            self._sync()

    def _short_title(self):
        title = self.full_title
        if len(title) <= SHADE_TITLE_LEN:
            return title
        return title[:SHADE_TITLE_LEN] + "..."

    def _shaded_width(self, title):
        """접힌 제목 칸의 가로 길이: 12글자 제목과 단추가 들어가는 고정 폭."""
        return TAB_WIDTH

    def _collapse(self):
        if user32.IsZoomed(self.hwnd):
            return
        rect = wintypes.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        origin = wintypes.POINT(0, 0)
        user32.ClientToScreen(self.hwnd, ctypes.byref(origin))
        caption_h = origin.y - rect.top  # 제목 표시줄 + 위쪽 테두리 높이
        self.saved = (rect.right - rect.left, rect.bottom - rect.top,
                      self.root.winfo_width(), self.root.winfo_height())
        if self.set_content_visible:
            self.set_content_visible(False)
        self._min = self.root.wm_minsize()
        self.root.wm_minsize(1, 1)
        title = self._short_title()
        self.root.title(title)
        self._title_shortened = True
        # 처음 접을 때는 지금 자리에, 펼쳤다가 접을 때는 원래 제목 칸 자리로 돌아간다
        left, top = self.tab_pos if self.tab_pos else (rect.left, rect.top)
        user32.SetWindowPos(self.hwnd, None, left, top,
                            self._shaded_width(title), caption_h, SWP_NOZORDER | SWP_NOACTIVATE)

    def _expand(self):
        """제목 칸 바로 아래에서 펼친다 (Tk 주기 안에서만 호출)."""
        left, top = self._position()  # 접힌 제목 칸의 위치
        self.tab_pos = (left, top)
        width, height = self.saved[0], self.saved[1]
        rect = wintypes.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        top = top + (rect.bottom - rect.top) + GAP  # 제목 칸 바로 아래
        left = self._clear_of_open_windows(left, top, width, height)
        self.saved = None
        if self.set_content_visible:
            self.set_content_visible(False)
        self._move(left, top, width, height)
        if self.set_content_visible:
            self.set_content_visible(True)  # 최종 크기에서 한 번만 내용을 맞춘다
        self._arm_auto_collapse()

    def _arm_auto_collapse(self):
        self._auto_collapse = True
        self._last_activity = time.time()
        self._last_rect = None

    def _had_activity(self):
        """창 안에서 마우스 버튼이 눌렸거나, 창이 움직였거나 크기가 바뀌었으면 True."""
        rect = wintypes.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        now_rect = (rect.left, rect.top, rect.right, rect.bottom)
        moved = self._last_rect is not None and now_rect != self._last_rect
        self._last_rect = now_rect
        cursor = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(cursor))
        inside = rect.left <= cursor.x < rect.right and rect.top <= cursor.y < rect.bottom
        pressed = (user32.GetAsyncKeyState(VK_LBUTTON) | user32.GetAsyncKeyState(VK_RBUTTON)) & 0x8000
        return moved or (inside and bool(pressed))

    def _expand_in_place(self):
        """최대화 단추를 눌렀을 때: 콜백 안이라 Tk를 부르지 않고 제자리에서 펼친다."""
        left, top = self._position()
        width, height = self.saved[0], self.saved[1]
        self.saved = None
        self._content_hidden = self.set_content_visible is not None
        self._move(left, top, width, height)

    def _move(self, left, top, width, height):
        user32.SetWindowPos(self.hwnd, None, left, top, width, height, SWP_NOZORDER | SWP_NOACTIVATE)

    def _clear_of_open_windows(self, left, top, width, height):
        """펼쳐진 다른 창과 겹치면 그 창의 오른쪽으로 민다."""
        others = [e for key, e in _read_registry().items()
                  if key != self.key and e.get("state") == "open"]
        for _ in range(len(others)):
            target = (left, top, width, height)
            hit = next((e for e in others if _overlaps(target, (e["x"], e["y"], e["w"], e["h"]))), None)
            if hit is None:
                break
            left = hit["x"] + hit["w"] + GAP
        return left

    def _position(self):
        rect = wintypes.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        return rect.left, rect.top

    def collapse_at(self, x, y):
        """접힌 제목 칸을 (x, y) 자리에 둔다. 이미 접혀 있으면 그 자리로 옮긴다."""
        self.tab_pos = (x, y)
        if self.shaded:
            rect = wintypes.RECT()
            user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
            user32.SetWindowPos(self.hwnd, None, x, y, rect.right - rect.left, rect.bottom - rect.top,
                                SWP_NOZORDER | SWP_NOACTIVATE)
        else:
            self._collapse()

    def _state(self):
        if self.root.state() == "withdrawn":
            return "hidden"
        return "tab" if self.shaded else "open"

    def _sync(self):
        """공유 목록에 이 창의 위치, 상태(접힘/펼침), 프로그램 이름과 실행 파일을 적는다."""
        import sys
        rect = wintypes.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        entries = _read_registry()
        for key, e in entries.items():
            if key != self.key and e.get("app") == self.app_id and self.app_id and e.get("started", 0) < self.started:
                user32.PostMessageW(e["hwnd"], WM_CLOSE, 0, 0)  # 같은 프로그램의 먼저 뜬 실행본을 닫는다
        entries[self.key] = {
            "x": rect.left, "y": rect.top, "w": rect.right - rect.left, "h": rect.bottom - rect.top,
            "state": self._state(), "ts": time.time(),
            "app": self.app_id, "pid": os.getpid(), "hwnd": self.hwnd, "started": self.started,
            "exe": sys.executable if getattr(sys, "frozen", False) else "",
        }
        try:
            _write_registry(entries)
        except OSError:
            pass

    def _unpublish(self):
        """프로그램이 끝날 때 목록에서 자기 항목을 지운다."""
        try:
            entries = _read_registry()
            if entries.pop(self.key, None) is not None:
                _write_registry(entries)
        except OSError:
            pass


def install_title_shade(root, set_content_visible=None, app_id=None):
    """root 창의 제목 표시줄 더블클릭 접기/펴기 기능을 켠다.
    set_content_visible(bool) 을 주면 크기를 바꾸는 동안 내용을 숨긴다(빠른 전환용)."""
    root.update_idletasks()  # 창 핸들을 만들어 둔다
    return TitleShade(root, set_content_visible, app_id)
