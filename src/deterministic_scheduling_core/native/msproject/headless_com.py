"""Actual Microsoft Project desktop automation for headless characterisation.

The import is safe on non-Windows hosts: pywin32 is loaded only when a native
operation is requested.  No scheduling fallback exists.
"""

from __future__ import annotations

import contextlib
import ctypes
from ctypes import wintypes
import hashlib
import locale
import ntpath
import os
import platform
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

try:  # pragma: no cover - the import itself is platform-specific
    import winreg
except ImportError:  # Linux CI must still be able to import the fail-closed adapter.
    winreg = None  # type: ignore[assignment]

from .headless import (
    ORIGIN,
    TRACK_ID,
    parse_project_xml_observation,
    sha256_file,
    validated_cal24x7_calendar,
)


PROG_ID = "MSProject.Application"
PROJECT_EXE_NAME = "WINPROJ.EXE"
SVCHOST_EXE_NAME = "svchost.exe"
PJ_MANUAL = 0
PJ_FIXED_DURATION = 1
PJ_SNET = 4
PJ_PROJECT_START = 1
PJ_DO_NOT_SAVE = 0
LINK_TYPES = {"FF": 0, "FS": 1, "SF": 2, "SS": 3}
LINK_NAMES = {value: key for key, value in LINK_TYPES.items()}
PJ_HOURS = 5

StageCallback = Callable[[str, str, Mapping[str, Any]], None]


class ProjectAutomationError(RuntimeError):
    """Base fail-closed native automation error."""


class ProjectNotInstalledError(ProjectAutomationError):
    pass


class ProjectComError(ProjectAutomationError):
    pass


class RequiredNativePropertyError(ProjectAutomationError):
    pass


class NativeTransformationError(ProjectAutomationError):
    """Raised by callers after transformation evidence has been retained."""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def _emit(callback: StageCallback | None, stage: str, phase: str, **details: Any) -> None:
    if callback:
        callback(stage, phase, {"observed_at": _now(), **details})


@contextlib.contextmanager
def _stage(callback: StageCallback | None, name: str, **details: Any):
    _emit(callback, name, "start", **details)
    started = time.monotonic()
    try:
        yield
    except Exception as error:
        _emit(
            callback,
            name,
            "error",
            elapsed_milliseconds=int((time.monotonic() - started) * 1000),
            error_type=type(error).__name__,
            error=str(error),
        )
        raise
    else:
        _emit(
            callback,
            name,
            "complete",
            elapsed_milliseconds=int((time.monotonic() - started) * 1000),
        )


def _load_pywin32() -> tuple[Any, Any, Any]:
    if os.name != "nt":
        raise ProjectNotInstalledError("Microsoft Project COM automation requires Windows")
    try:
        import pythoncom  # type: ignore
        import win32api  # type: ignore
        import win32com.client  # type: ignore
    except ImportError as error:
        raise ProjectNotInstalledError(
            "pywin32 is required for MSProject.Application (install the Windows native extra)"
        ) from error
    return pythoncom, win32api, win32com.client


def registered_project_executable() -> Path:
    if os.name != "nt" or winreg is None:
        raise ProjectNotInstalledError("WINPROJ.EXE registration requires Windows")
    candidates = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\WINPROJ.EXE"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\WINPROJ.EXE"),
    )
    for hive, key_name in candidates:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                raw, _ = winreg.QueryValueEx(key, None)
        except OSError:
            continue
        path = Path(str(raw)).resolve(strict=False)
        if path.is_file():
            return path
    raise ProjectNotInstalledError("WINPROJ.EXE is not registered or installed")


TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

OWNED_PROCESS_IDENTITY_FIELDS = (
    "pid",
    "executable_path",
    "creation_time_100ns",
    "ownership_caption",
    "ownership_hwnd",
    "activation_parent_pid",
    "activation_parent_executable_path",
    "activation_parent_creation_time_100ns",
    "ownership_origin_verified",
)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _configured_kernel32() -> Any:
    """Return kernel32 with pointer-width-safe HANDLE signatures."""

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESSENTRY32W),
    ]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESSENTRY32W),
    ]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    return kernel32


def _configured_user32(callback_type: Any) -> Any:
    """Return user32 with pointer-width-safe HWND signatures."""

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    ]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    ]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsWindowEnabled.argtypes = [wintypes.HWND]
    user32.IsWindowEnabled.restype = wintypes.BOOL
    return user32


def _system_svchost_path() -> str | None:
    windows_root = os.environ.get("SystemRoot")
    if not windows_root:
        return None
    return ntpath.normcase(
        ntpath.normpath(ntpath.join(windows_root, "System32", SVCHOST_EXE_NAME))
    )


def _valid_activation_parent(
    *,
    child_pid: Any,
    child_creation_time_100ns: Any,
    parent_pid: Any,
    parent_executable_path: Any,
    parent_creation_time_100ns: Any,
) -> bool:
    """Validate the retained DCOM-launch parent without trusting a basename."""

    system_svchost = _system_svchost_path()
    if system_svchost is None or not isinstance(parent_executable_path, str):
        return False
    if (
        not isinstance(child_pid, int)
        or child_pid <= 0
        or not isinstance(parent_pid, int)
        or parent_pid <= 0
        or parent_pid == child_pid
        or not isinstance(child_creation_time_100ns, int)
        or child_creation_time_100ns <= 0
        or not isinstance(parent_creation_time_100ns, int)
        or parent_creation_time_100ns <= 0
        or parent_creation_time_100ns >= child_creation_time_100ns
    ):
        return False
    observed_parent = ntpath.normcase(ntpath.normpath(parent_executable_path))
    return observed_parent == system_svchost


def _query_process_path(pid: int) -> str | None:
    kernel32 = _configured_kernel32()
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        return _query_process_path_from_handle(kernel32, handle)
    finally:
        kernel32.CloseHandle(handle)


def _query_process_path_from_handle(kernel32: Any, handle: Any) -> str | None:
    """Query the executable identity from the already-authorized handle."""

    size = wintypes.DWORD(32768)
    buffer = ctypes.create_unicode_buffer(size.value)
    if not kernel32.QueryFullProcessImageNameW(
        handle, 0, buffer, ctypes.byref(size)
    ):
        return None
    return buffer.value


def _query_process_creation_time_100ns(pid: int) -> int | None:
    """Return the immutable Windows process creation FILETIME value."""

    if os.name != "nt":
        return None
    kernel32 = _configured_kernel32()
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        return _query_process_creation_time_from_handle(kernel32, handle)
    finally:
        kernel32.CloseHandle(handle)


def _query_process_creation_time_from_handle(
    kernel32: Any, handle: Any
) -> int | None:
    """Query creation FILETIME through the same handle used for termination."""

    creation = wintypes.FILETIME()
    exit_time = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    if not kernel32.GetProcessTimes(
        handle,
        ctypes.byref(creation),
        ctypes.byref(exit_time),
        ctypes.byref(kernel),
        ctypes.byref(user),
    ):
        return None
    return (int(creation.dwHighDateTime) << 32) | int(creation.dwLowDateTime)


def list_winproj_processes() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    kernel32 = _configured_kernel32()
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise ProjectComError(f"CreateToolhelp32Snapshot failed: {ctypes.get_last_error()}")
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    results: list[dict[str, Any]] = []
    try:
        success = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while success:
            if entry.szExeFile.upper() == PROJECT_EXE_NAME:
                pid = int(entry.th32ProcessID)
                results.append(
                    {
                        "pid": pid,
                        "parent_pid": int(entry.th32ParentProcessID),
                        "executable_name": entry.szExeFile,
                        "executable_path": _query_process_path(pid),
                        "creation_time_100ns": _query_process_creation_time_100ns(pid),
                    }
                )
            success = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return sorted(results, key=lambda item: item["pid"])


def _find_new_project_process(
    before: set[int],
    expected_path: Path,
    *,
    activation_not_before_100ns: int,
    timeout: float = 15.0,
) -> dict[str, Any]:
    """Find one new exact-path process with retained COM-activation provenance.

    This helper is deliberately unsuitable for destructive cleanup by itself;
    the returned creation identity must subsequently be bound to the COM
    object's unique caption and retained in the worker journal.
    """

    deadline = time.monotonic() + timeout
    last: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        last = [item for item in list_winproj_processes() if item["pid"] not in before]
        matching = [
            item
            for item in last
            if item.get("executable_path")
            and Path(item["executable_path"]).resolve(strict=False) == expected_path.resolve(strict=False)
        ]
        if len(matching) == 1:
            candidate = dict(matching[0])
            creation = candidate.get("creation_time_100ns")
            if not isinstance(creation, int):
                raise ProjectComError("new Project process has no queryable creation identity")
            if creation < activation_not_before_100ns:
                raise ProjectComError(
                    "new Project process predates the DispatchEx activation window"
                )
            parent_pid = candidate.get("parent_pid")
            if not isinstance(parent_pid, int) or parent_pid <= 0:
                raise ProjectComError("new Project process has no retained parent PID")
            parent_path = _query_process_path(parent_pid)
            parent_creation = _query_process_creation_time_100ns(parent_pid)
            if not _valid_activation_parent(
                child_pid=candidate.get("pid"),
                child_creation_time_100ns=creation,
                parent_pid=parent_pid,
                parent_executable_path=parent_path,
                parent_creation_time_100ns=parent_creation,
            ):
                raise ProjectComError(
                    "new Project process lacks valid Windows COM activation-parent provenance"
                )
            candidate.update(
                {
                    "activation_parent_pid": parent_pid,
                    "activation_parent_executable_path": parent_path,
                    "activation_parent_creation_time_100ns": parent_creation,
                    "ownership_origin_verified": True,
                }
            )
            return candidate
        if len(matching) > 1:
            raise ProjectComError(
                f"multiple new exact-path Project processes appeared during activation: {matching}"
            )
        time.sleep(0.1)
    raise ProjectComError(
        "could not bind the DispatchEx object to exactly one new exact-path "
        f"WINPROJ process; observed {last}"
    )


def windows_for_pid(pid: int) -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    results: list[dict[str, Any]] = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32 = _configured_user32(callback_type)

    @callback_type
    def callback(hwnd: int, _lparam: int) -> bool:
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, 256)
        results.append(
            {
                "handle": int(hwnd),
                "title": buffer.value,
                "class_name": class_buffer.value,
                "visible": bool(user32.IsWindowVisible(hwnd)),
                "enabled": bool(user32.IsWindowEnabled(hwnd)),
            }
        )
        return True

    user32.EnumWindows(callback, 0)
    return results


def _bind_process_to_caption(
    process: Mapping[str, Any],
    expected_path: Path,
    ownership_caption: str,
    *,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Bind a previously unique new process to the exact COM caption token."""

    pid = int(process["pid"])
    creation = process.get("creation_time_100ns")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _query_process_path(pid) is None:
            break
        current_creation = _query_process_creation_time_100ns(pid)
        if creation is None or current_creation != creation:
            raise ProjectComError(f"Project process identity changed before caption binding: {pid}")
        for window in windows_for_pid(pid):
            if ownership_caption in str(window.get("title", "")):
                bound = dict(process)
                bound["ownership_caption"] = ownership_caption
                bound["ownership_hwnd"] = int(window["handle"])
                return bound
        time.sleep(0.05)
    raise ProjectComError(
        f"new Project process {pid} was not bound to the COM ownership caption"
    )


def _owned_process_identity_matches(process: Mapping[str, Any], expected_path: Path) -> bool:
    """Revalidate PID, image, creation time, HWND, and caption token."""

    if any(process.get(key) in (None, "") for key in OWNED_PROCESS_IDENTITY_FIELDS):
        return False
    if process.get("ownership_origin_verified") is not True:
        return False
    if not _valid_activation_parent(
        child_pid=process.get("pid"),
        child_creation_time_100ns=process.get("creation_time_100ns"),
        parent_pid=process.get("activation_parent_pid"),
        parent_executable_path=process.get("activation_parent_executable_path"),
        parent_creation_time_100ns=process.get(
            "activation_parent_creation_time_100ns"
        ),
    ):
        return False
    pid = int(process["pid"])
    actual = _query_process_path(pid)
    if not actual or Path(actual).resolve(strict=False) != expected_path.resolve(strict=False):
        return False
    if _query_process_creation_time_100ns(pid) != int(process["creation_time_100ns"]):
        return False
    caption = str(process["ownership_caption"])
    hwnd = int(process["ownership_hwnd"])
    return any(
        int(window.get("handle", 0)) == hwnd
        and caption in str(window.get("title", ""))
        for window in windows_for_pid(pid)
    )


def _owned_process_identity_details(process: Mapping[str, Any]) -> dict[str, Any]:
    """Return the complete journal identity or fail before emitting authority."""

    missing = [
        field
        for field in OWNED_PROCESS_IDENTITY_FIELDS
        if process.get(field) in (None, "")
    ]
    if missing or process.get("ownership_origin_verified") is not True:
        raise ProjectComError(
            f"owned Project process identity is incomplete: {missing or ['ownership_origin_verified']}"
        )
    if not _valid_activation_parent(
        child_pid=process.get("pid"),
        child_creation_time_100ns=process.get("creation_time_100ns"),
        parent_pid=process.get("activation_parent_pid"),
        parent_executable_path=process.get("activation_parent_executable_path"),
        parent_creation_time_100ns=process.get(
            "activation_parent_creation_time_100ns"
        ),
    ):
        raise ProjectComError("owned Project process activation origin is invalid")
    return {field: process[field] for field in OWNED_PROCESS_IDENTITY_FIELDS}


def terminate_verified_project_process(
    pid: int,
    expected_path: Path,
    *,
    process_identity: Mapping[str, Any] | None = None,
) -> bool:
    if process_identity is None or int(process_identity.get("pid", -1)) != pid:
        raise ProjectComError(
            f"refusing to terminate Project process {pid} without its full ownership identity"
        )
    _owned_process_identity_details(process_identity)
    if Path(str(process_identity["executable_path"])).resolve(
        strict=False
    ) != expected_path.resolve(strict=False):
        raise ProjectComError(
            f"refusing to terminate Project process {pid}: retained executable changed"
        )
    kernel32 = _configured_kernel32()
    handle = kernel32.OpenProcess(PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        # Authorization is derived from the same kernel handle that will be
        # terminated.  PID-based checks performed before OpenProcess are
        # inherently vulnerable to exit/reuse between lookup and termination.
        actual = _query_process_path_from_handle(kernel32, handle)
        creation = _query_process_creation_time_from_handle(kernel32, handle)
        if (
            not actual
            or Path(actual).resolve(strict=False)
            != expected_path.resolve(strict=False)
            or creation != int(process_identity["creation_time_100ns"])
        ):
            raise ProjectComError(
                f"refusing to terminate Project process {pid}: handle identity changed"
            )
        caption = str(process_identity["ownership_caption"])
        hwnd = int(process_identity["ownership_hwnd"])
        if not any(
            int(window.get("handle", 0)) == hwnd
            and caption in str(window.get("title", ""))
            for window in windows_for_pid(pid)
        ):
            raise ProjectComError(
                f"refusing to terminate Project process {pid}: ownership window changed"
            )
        return bool(kernel32.TerminateProcess(handle, 0xDEAD))
    finally:
        kernel32.CloseHandle(handle)


def _wait_process_exit(pid: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _query_process_path(pid) is None:
            return True
        time.sleep(0.1)
    return _query_process_path(pid) is None


def _required_get(obj: Any, name: str) -> Any:
    try:
        return getattr(obj, name)
    except Exception as error:
        raise RequiredNativePropertyError(f"required native property is unavailable: {name}") from error


def _required_set(obj: Any, name: str, value: Any) -> None:
    try:
        setattr(obj, name, value)
        observed = getattr(obj, name)
    except Exception as error:
        raise RequiredNativePropertyError(f"required native property cannot be set/read: {name}") from error
    if isinstance(value, datetime) and isinstance(observed, datetime):
        # Project dates are local wall-clock values. Some pywin32 builds attach
        # an unrelated tzinfo label, so converting it would silently shift the
        # schedule. Compare the displayed components without timezone math.
        matches = value.replace(tzinfo=None, microsecond=0) == observed.replace(
            tzinfo=None, microsecond=0
        )
    elif isinstance(value, bool):
        matches = bool(observed) is value
    elif isinstance(value, int):
        matches = int(observed) == value
    else:
        matches = observed == value
    if not matches:
        raise RequiredNativePropertyError(
            f"required native property {name} readback mismatch: supplied {value!r}, observed {observed!r}"
        )


def _optional_get(obj: Any, name: str) -> Any:
    try:
        return getattr(obj, name)
    except Exception as error:
        return {"unavailable": True, "error": f"{type(error).__name__}: {error}"}


def _optional_call(obj: Any, name: str) -> Any:
    value = _optional_get(obj, name)
    if not callable(value):
        return value
    try:
        return value()
    except Exception as error:
        return {"unavailable": True, "error": f"{type(error).__name__}: {error}"}


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        return format(value, ".15g")
    if isinstance(value, datetime):
        observed_offset = datetime.now().astimezone().utcoffset()
        if observed_offset is None:
            raise ProjectComError("local UTC offset is unavailable")
        # Preserve Project wall-clock components. Do not trust or convert the
        # tzinfo attached by pywintypes; it has been observed to be unrelated
        # to the Project schedule's configured local wall clock.
        wall_clock = value.replace(tzinfo=None)
        return wall_clock.replace(tzinfo=timezone(observed_offset)).isoformat(
            timespec="seconds"
        )
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    observed_offset = datetime.now().astimezone().utcoffset()
    if observed_offset is None:
        raise ProjectComError("local UTC offset is unavailable")
    return parsed.replace(tzinfo=None).replace(
        tzinfo=timezone(observed_offset)
    ).isoformat(timespec="seconds")


class _ProjectSession:
    def __init__(self, app: Any, pythoncom: Any, process: Mapping[str, Any], executable: Path):
        self.app = app
        self.pythoncom = pythoncom
        self.process = dict(process)
        self.executable = executable
        self.closed = False

    @property
    def pid(self) -> int:
        return int(self.process["pid"])

    def close_project(self) -> None:
        if not _owned_process_identity_matches(self.process, self.executable):
            raise ProjectComError(
                f"refusing to close project after ownership identity changed: {self.pid}"
            )
        try:
            if _optional_get(self.app, "Projects") not in (None,):
                self.app.FileCloseEx(PJ_DO_NOT_SAVE)
        except Exception:
            with contextlib.suppress(Exception):
                self.app.FileClose(PJ_DO_NOT_SAVE)

    def quit(self) -> dict[str, Any]:
        if self.closed:
            return {"pid": self.pid, "already_closed": True}
        ownership_revalidated = _owned_process_identity_matches(
            self.process, self.executable
        )
        termination_error: str | None = None
        if ownership_revalidated:
            with contextlib.suppress(Exception):
                self.app.Quit(PJ_DO_NOT_SAVE)
        else:
            termination_error = (
                "refused Application.Quit because the retained Project process "
                "identity no longer matched PID/path/creation/HWND/caption"
            )
        exited = _wait_process_exit(self.pid, 10.0)
        terminated = False
        if not exited:
            try:
                terminated = terminate_verified_project_process(
                    self.pid,
                    self.executable,
                    process_identity=self.process,
                )
            except ProjectComError as error:
                cleanup_error = str(error)
                termination_error = (
                    f"{termination_error}; {cleanup_error}"
                    if termination_error
                    else cleanup_error
                )
            exited = _wait_process_exit(self.pid, 5.0)
        self.closed = True
        self.app = None
        self.pythoncom.CoUninitialize()
        return {
            "pid": self.pid,
            "exited": exited,
            "forced_termination": terminated,
            "termination_error": termination_error,
            "ownership_revalidated_before_quit": ownership_revalidated,
            "process_identity": self.process,
        }


def _open_application(callback: StageCallback | None, *, stage_name: str = "project_startup") -> _ProjectSession:
    pythoncom, _win32api, client = _load_pywin32()
    executable = registered_project_executable()
    before_processes = list_winproj_processes()
    if before_processes:
        raise ProjectComError(
            "refusing COM activation while any Microsoft Project process already exists; "
            "close or separately preserve the existing session before a future run"
        )
    before = {int(item["pid"]) for item in before_processes}
    pythoncom.CoInitialize()
    app = None
    process: dict[str, Any] | None = None
    ownership_confirmed = False
    try:
        with _stage(callback, stage_name, prog_id=PROG_ID, existing_project_pids=sorted(before)):
            activation_not_before_100ns = (
                116_444_736_000_000_000 + time.time_ns() // 100
            )
            app = client.DispatchEx(PROG_ID)
            # Read-only checks and a unique, new, exact-image process identity
            # precede every mutation of the COM object.  Project exposes no HWND
            # on its Application interface, so the unique caption is then used
            # to bind that immutable process identity to this exact object.
            if bool(_required_get(app, "Visible")):
                raise ProjectComError("new Microsoft Project COM object was unexpectedly visible")
            process = _find_new_project_process(
                before,
                executable,
                activation_not_before_100ns=activation_not_before_100ns,
            )
            if any(bool(window.get("visible")) for window in windows_for_pid(int(process["pid"]))):
                raise ProjectComError("new Project process had a visible window before ownership binding")
            ownership_caption = f"Codex headless Project {os.getpid()}-{time.monotonic_ns()}"
            _emit(
                callback,
                stage_name,
                "ownership_token_issued",
                ownership_caption=ownership_caption,
                candidate_pid=process["pid"],
                candidate_creation_time_100ns=process["creation_time_100ns"],
                activation_parent_pid=process["activation_parent_pid"],
                activation_parent_executable_path=process[
                    "activation_parent_executable_path"
                ],
                activation_parent_creation_time_100ns=process[
                    "activation_parent_creation_time_100ns"
                ],
                ownership_origin_verified=True,
            )
            _required_set(app, "Caption", ownership_caption)
            process = _bind_process_to_caption(process, executable, ownership_caption)
            ownership_confirmed = True
            _required_set(app, "Visible", False)
            identity_details = _owned_process_identity_details(process)
            _emit(
                callback,
                stage_name,
                "ownership_caption_set",
                **identity_details,
            )
            _emit(
                callback,
                stage_name,
                "process_identified",
                **identity_details,
            )
        assert process is not None
        session = _ProjectSession(app, pythoncom, process, executable)
        return session
    except Exception:
        if app is not None and ownership_confirmed and process is not None:
            with contextlib.suppress(Exception):
                if _owned_process_identity_matches(process, executable):
                    app.Quit(PJ_DO_NOT_SAVE)
        pythoncom.CoUninitialize()
        raise


def _configure_blank_project(session: _ProjectSession, callback: StageCallback | None) -> Any:
    app = session.app
    pythoncom = session.pythoncom
    with _stage(callback, "project_creation", pid=session.pid):
        _required_set(app, "Calculation", PJ_MANUAL)
        result = app.FileNew()
        if result is False:
            raise ProjectComError("Application.FileNew returned False")
        project = _required_get(app, "ActiveProject")
        # The installed Project 16.0 type library declares omitted optional
        # arguments as VT_EMPTY (its generated wrapper uses pythoncom.Empty).
        # DISP_E_PARAMNOTFOUND makes this build enter the interactive command.
        omitted = pythoncom.Empty
        arguments = [omitted] * 16
        # Project treats an omitted Project argument as the interactive
        # Project Information command on this desktop build.  Bind the active
        # project explicitly so this call is unambiguously non-interactive.
        arguments[0] = str(_required_get(project, "Name"))
        arguments[8] = datetime(2026, 1, 5, 8, 0, 0)
        arguments[10] = PJ_PROJECT_START
        arguments[12] = "24 Hours"
        if app.ProjectSummaryInfo(*arguments) is False:
            raise ProjectComError("ProjectSummaryInfo returned False")
        _required_set(project, "ScheduleFromStart", True)
        _required_set(project, "ProjectStart", datetime(2026, 1, 5, 8, 0, 0))
        _required_set(project, "NewTasksCreatedAsManual", False)
        _required_set(project, "DefaultTaskType", PJ_FIXED_DURATION)
        _required_set(project, "DefaultEffortDriven", False)
        _required_set(project, "NewTasksEstimated", False)
        _required_set(app, "AutoLevel", False)
        if app.LevelingOptions(False) is False:
            raise ProjectComError("LevelingOptions(False) returned False")
        if bool(app.AutoLevel):
            raise ProjectComError("resource leveling remained automatic")
        calendar = _required_get(project, "Calendar")
        if str(_required_get(calendar, "Name")) != "24 Hours":
            raise ProjectComError(f"project calendar readback is not 24 Hours: {calendar.Name!r}")
        if int(app.Calculation) != PJ_MANUAL:
            raise ProjectComError("calculation mode transformed away from Manual")
    return project


def _duration_text(hours: Any) -> str:
    if not isinstance(hours, int) or hours < 0:
        raise ProjectComError(f"invalid source duration hours: {hours!r}")
    return f"{hours}h"


def _lag_text(hours: Any) -> str:
    if not isinstance(hours, int):
        raise ProjectComError(f"invalid source lag hours: {hours!r}")
    return f"{hours}h"


def _build_source_project(project: Any, facts: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    tasks: dict[str, Any] = {}
    requested_tasks: list[dict[str, Any]] = []
    origin = datetime.fromisoformat(str(facts["time_axis"]["origin"])).replace(tzinfo=None)
    for source in facts["activity_inputs"]:
        task = project.Tasks.Add(source["name"])
        _required_set(task, "Manual", False)
        _required_set(task, "Type", PJ_FIXED_DURATION)
        _required_set(task, "EffortDriven", False)
        _required_set(task, "Calendar", "24 Hours")
        duration_supplied = _duration_text(source["duration"])
        try:
            task.Duration = duration_supplied
            duration_readback = int(task.Duration)
        except Exception as error:
            raise RequiredNativePropertyError("task Duration string assignment/readback failed") from error
        expected_minutes = int(source["duration"]) * 60
        if duration_readback != expected_minutes:
            raise RequiredNativePropertyError(
                f"task duration transformed: supplied {duration_supplied}, read back {duration_readback} minutes"
            )
        for constraint in source.get("constraints", []):
            if constraint.get("type") != "start_no_earlier_than" or not isinstance(constraint.get("value"), int):
                raise ProjectComError(f"unsupported source constraint: {constraint!r}")
            _required_set(task, "ConstraintType", PJ_SNET)
            _required_set(task, "ConstraintDate", origin + timedelta(hours=constraint["value"]))
        tasks[source["id"]] = task
        requested_tasks.append(
            {
                "source_id": source["id"],
                "name": source["name"],
                "duration_source_hours": source["duration"],
                "duration_native_supplied": duration_supplied,
                "duration_native_readback_minutes": duration_readback,
            }
        )
    relationship = facts["relationship_inputs"][0]
    native_type = LINK_TYPES[relationship["type"]]
    lag_supplied = _lag_text(relationship["lag"])
    successor = tasks[relationship["successor_id"]]
    predecessor = tasks[relationship["predecessor_id"]]
    try:
        dependency = successor.TaskDependencies.Add(predecessor, native_type, lag_supplied)
    except Exception as error:
        raise ProjectComError("TaskDependencies.Add failed") from error
    assignment = {
        "relationship_id": relationship["id"],
        "source_type": relationship["type"],
        "source_lag_hours": relationship["lag"],
        "native_type_supplied": native_type,
        "native_lag_supplied": lag_supplied,
        "native_type_readback": int(dependency.Type),
        "native_lag_readback_minutes": int(dependency.Lag),
        "native_lag_type_readback": int(dependency.LagType),
        "native_from_task_id": int(dependency.From.ID),
        "native_to_task_id": int(dependency.To.ID),
    }
    assignment["type_transformed"] = assignment["native_type_readback"] != native_type
    assignment["lag_transformed"] = (
        assignment["native_lag_readback_minutes"] != int(relationship["lag"]) * 60
        or assignment["native_lag_type_readback"] != PJ_HOURS
    )
    return {"tasks": requested_tasks}, assignment


def _capture_task(task: Any) -> dict[str, Any]:
    dependencies: list[dict[str, Any]] = []
    collection = _required_get(task, "TaskDependencies")
    for index in range(1, int(collection.Count) + 1):
        dependency = collection.Item(index)
        dependencies.append(
            {
                "index": int(dependency.Index),
                "from_task_id": int(dependency.From.ID),
                "from_task_unique_id": int(dependency.From.UniqueID),
                "to_task_id": int(dependency.To.ID),
                "to_task_unique_id": int(dependency.To.UniqueID),
                "type": int(dependency.Type),
                "type_name": LINK_NAMES.get(int(dependency.Type), "unknown"),
                "lag_minutes": int(dependency.Lag),
                "lag_type": int(dependency.LagType),
            }
        )
    return {
        "id": int(_required_get(task, "ID")),
        "unique_id": int(_required_get(task, "UniqueID")),
        "name": str(_required_get(task, "Name")),
        "start": _json_value(_required_get(task, "Start")),
        "finish": _json_value(_required_get(task, "Finish")),
        "duration_minutes": int(_required_get(task, "Duration")),
        "manual": bool(_required_get(task, "Manual")),
        "type": int(_required_get(task, "Type")),
        "effort_driven": bool(_required_get(task, "EffortDriven")),
        "calendar": str(_required_get(task, "Calendar")),
        "constraint_type": int(_required_get(task, "ConstraintType")),
        "constraint_date": _json_value(_required_get(task, "ConstraintDate")),
        "predecessors": str(_required_get(task, "Predecessors")),
        "task_dependencies": dependencies,
        "actual_start": _json_value(_optional_get(task, "ActualStart")),
        "actual_finish": _json_value(_optional_get(task, "ActualFinish")),
        "percent_complete": _json_value(_optional_get(task, "PercentComplete")),
        "resource_names": str(_optional_get(task, "ResourceNames")),
    }


def _capture_project(app: Any, project: Any, *, session: _ProjectSession) -> dict[str, Any]:
    tasks = []
    for index in range(1, int(project.Tasks.Count) + 1):
        task = project.Tasks.Item(index)
        if task is not None:
            tasks.append(_capture_task(task))
    project_record = {
        "name": str(_required_get(project, "Name")),
        "start": _json_value(_required_get(project, "ProjectStart")),
        "finish": _json_value(_required_get(project, "ProjectFinish")),
        "schedule_from_start": bool(_required_get(project, "ScheduleFromStart")),
        "calendar": str(_required_get(_required_get(project, "Calendar"), "Name")),
        "status_date": _json_value(_optional_get(project, "StatusDate")),
        "resource_count": int(_required_get(project.Resources, "Count")),
        "default_task_type": int(_required_get(project, "DefaultTaskType")),
        "default_effort_driven": bool(_required_get(project, "DefaultEffortDriven")),
        "new_tasks_created_as_manual": bool(_required_get(project, "NewTasksCreatedAsManual")),
        "calculation_mode": int(_required_get(app, "Calculation")),
        "resource_leveling_automatic": bool(_required_get(app, "AutoLevel")),
        "process_id": session.pid,
        "process_executable": session.process.get("executable_path"),
        "captured_at": _now(),
    }
    return {"project": project_record, "tasks": tasks}


def _save_mpp(app: Any, path: Path) -> None:
    if path.exists():
        raise ProjectComError(f"refusing to overwrite MPP evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if app.FileSaveAs(str(path), 0) is False:
        raise ProjectComError("FileSaveAs MPP returned False")
    if not path.is_file() or path.stat().st_size == 0:
        raise ProjectComError("FileSaveAs did not produce a non-empty MPP")


def _export_xml(app: Any, pythoncom: Any, path: Path) -> None:
    if path.exists():
        raise ProjectComError(f"refusing to overwrite XML evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    omitted = pythoncom.Empty
    arguments = [str(path)] + [omitted] * 8 + ["MSProject.XML"]
    if app.FileSaveAs(*arguments) is False:
        raise ProjectComError("FileSaveAs Project XML returned False")
    if not path.is_file() or path.stat().st_size == 0:
        raise ProjectComError("FileSaveAs did not produce non-empty Project XML")


def _open_file(app: Any, path: Path) -> Any:
    if app.FileOpenEx(str(path)) is False:
        raise ProjectComError(f"FileOpenEx returned False for {path}")
    return _required_get(app, "ActiveProject")


def _open_project_xml(app: Any, path: Path) -> Any:
    """Open the exact exported XML text without invoking the Import Wizard."""

    try:
        xml_text = path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise ProjectComError(f"Project XML is not readable UTF-8: {path}") from error
    result = app.OpenXML(xml_text)
    if int(result) != 0:
        raise ProjectComError(f"Application.OpenXML returned {result!r} for {path}")
    return _required_get(app, "ActiveProject")


def _native_setting_transformations(capture: Mapping[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    project = capture["project"]
    expected_project = {
        "schedule_from_start": True,
        "calendar": "24 Hours",
        "calculation_mode": PJ_MANUAL,
        "resource_leveling_automatic": False,
        "default_task_type": PJ_FIXED_DURATION,
        "default_effort_driven": False,
        "new_tasks_created_as_manual": False,
    }
    for field, expected in expected_project.items():
        if project.get(field) != expected:
            findings.append({"scope": "project", "field": field, "expected": expected, "observed": project.get(field)})
    for task in capture["tasks"]:
        for field, expected in {
            "manual": False,
            "type": PJ_FIXED_DURATION,
            "effort_driven": False,
            "calendar": "24 Hours",
        }.items():
            if task.get(field) != expected:
                findings.append(
                    {"scope": f"task:{task.get('name')}", "field": field, "expected": expected, "observed": task.get(field)}
                )
    return findings


def _unset_native_value(value: Any) -> bool:
    return value is None or value == "" or str(value).upper() == "NA"


_WALL_CLOCK_PATTERN = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?P<offset>Z|[+-]\d{2}:\d{2})?\Z"
)


def _wall_clock(value: Any, *, require_offset: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    match = _WALL_CLOCK_PATTERN.fullmatch(value)
    if match is None or (require_offset and match.group("offset") is None):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None).isoformat(timespec="seconds")


def _append_required_xml_com_wall_clock_condition(
    conditions: list[dict[str, Any]],
    *,
    stage: str,
    field: str,
    com_value: Any,
    xml_value: Any,
) -> None:
    com_wall_clock = _wall_clock(com_value, require_offset=True)
    xml_wall_clock = _wall_clock(xml_value)
    if com_wall_clock is None or xml_wall_clock is None:
        conditions.append(
            {
                "condition": "required_schedule_timestamp_invalid",
                "stage": stage,
                "field": field,
                "com": com_value,
                "xml": xml_value,
                "com_timestamp_valid": com_wall_clock is not None,
                "xml_timestamp_valid": xml_wall_clock is not None,
            }
        )
    elif com_wall_clock != xml_wall_clock:
        conditions.append(
            {
                "condition": "xml_com_wall_clock_mismatch",
                "stage": stage,
                "field": field,
                "com": com_value,
                "xml": xml_value,
            }
        )


def _capture_task_map(capture: Mapping[str, Any]) -> dict[str, Mapping[str, Any]] | None:
    tasks = capture.get("tasks")
    if not isinstance(tasks, list):
        return None
    mapped: dict[str, Mapping[str, Any]] = {}
    for task in tasks:
        if not isinstance(task, Mapping) or not isinstance(task.get("name"), str):
            return None
        name = str(task["name"])
        if name in mapped:
            return None
        mapped[name] = task
    return mapped if set(mapped) == {"A", "B"} else None


def _case_capture_stop_conditions(
    capture: Mapping[str, Any],
    facts: Mapping[str, Any],
    assignment: Mapping[str, Any],
    *,
    stage: str,
) -> list[dict[str, Any]]:
    conditions: list[dict[str, Any]] = []
    project = capture.get("project")
    tasks = _capture_task_map(capture)
    if not isinstance(project, Mapping) or tasks is None:
        return [
            {
                "condition": "native_capture_task_structure_changed",
                "stage": stage,
                "observed_task_names": [
                    item.get("name") if isinstance(item, Mapping) else None
                    for item in capture.get("tasks", [])
                ]
                if isinstance(capture.get("tasks"), list)
                else None,
            }
        ]
    for finding in _native_setting_transformations(capture):
        conditions.append(
            {
                "condition": "task_or_project_setting_transformed",
                "stage": stage,
                **finding,
            }
        )
    if project.get("resource_count") != 0:
        conditions.append(
            {
                "condition": "unexpected_native_resources",
                "stage": stage,
                "observed": project.get("resource_count"),
            }
        )
    if not _unset_native_value(project.get("status_date")):
        conditions.append(
            {
                "condition": "unexpected_native_status_date",
                "stage": stage,
                "observed": project.get("status_date"),
            }
        )
    for field in ("start", "finish"):
        if _wall_clock(project.get(field), require_offset=True) is None:
            conditions.append(
                {
                    "condition": "required_schedule_timestamp_invalid",
                    "stage": stage,
                    "field": f"project.{field}",
                    "com": project.get(field),
                    "com_timestamp_valid": False,
                }
            )

    source_by_name = {
        str(item["name"]): item
        for item in facts.get("activity_inputs", [])
        if isinstance(item, Mapping) and isinstance(item.get("name"), str)
    }
    if set(source_by_name) != {"A", "B"}:
        return conditions + [
            {"condition": "source_task_structure_changed", "stage": stage}
        ]
    origin = datetime.fromisoformat(str(facts["time_axis"]["origin"])).replace(
        tzinfo=None
    )
    for name in ("A", "B"):
        task = tasks[name]
        source = source_by_name[name]
        for field in ("start", "finish"):
            if _wall_clock(task.get(field), require_offset=True) is None:
                conditions.append(
                    {
                        "condition": "required_schedule_timestamp_invalid",
                        "stage": stage,
                        "field": f"tasks.{name}.{field}",
                        "com": task.get(field),
                        "com_timestamp_valid": False,
                    }
                )
        if task.get("duration_minutes") != int(source["duration"]) * 60:
            conditions.append(
                {
                    "condition": "native_task_duration_changed",
                    "stage": stage,
                    "task": name,
                    "observed": task.get("duration_minutes"),
                }
            )
        if (
            not _unset_native_value(task.get("actual_start"))
            or not _unset_native_value(task.get("actual_finish"))
            or task.get("percent_complete") != 0
        ):
            conditions.append(
                {
                    "condition": "unexpected_native_progress",
                    "stage": stage,
                    "task": name,
                    "actual_start": task.get("actual_start"),
                    "actual_finish": task.get("actual_finish"),
                    "percent_complete": task.get("percent_complete"),
                }
            )
        if str(task.get("resource_names", "")) != "":
            conditions.append(
                {
                    "condition": "unexpected_native_task_resources",
                    "stage": stage,
                    "task": name,
                    "observed": task.get("resource_names"),
                }
            )
        constraints = source.get("constraints", [])
        if not isinstance(constraints, list) or len(constraints) > 1:
            conditions.append(
                {"condition": "source_constraint_structure_changed", "stage": stage, "task": name}
            )
        elif constraints:
            constraint = constraints[0]
            expected_date = (origin + timedelta(hours=int(constraint["value"]))).isoformat(
                timespec="seconds"
            )
            if task.get("constraint_type") != PJ_SNET or _wall_clock(
                task.get("constraint_date"), require_offset=True
            ) != expected_date:
                conditions.append(
                    {
                        "condition": "native_task_constraint_changed",
                        "stage": stage,
                        "task": name,
                        "observed_type": task.get("constraint_type"),
                        "observed_date": task.get("constraint_date"),
                        "expected_date": expected_date,
                    }
                )
        elif task.get("constraint_type") != 0 or not _unset_native_value(
            task.get("constraint_date")
        ):
            conditions.append(
                {
                    "condition": "unexpected_native_task_constraint",
                    "stage": stage,
                    "task": name,
                    "observed_type": task.get("constraint_type"),
                    "observed_date": task.get("constraint_date"),
                }
            )

    relationship = facts["relationship_inputs"][0]
    predecessor = tasks[str(relationship["predecessor_id"])]
    successor = tasks[str(relationship["successor_id"])]
    expected_dependency = {
        "from_task_id": predecessor.get("id"),
        "from_task_unique_id": predecessor.get("unique_id"),
        "to_task_id": successor.get("id"),
        "to_task_unique_id": successor.get("unique_id"),
        "type": assignment.get("native_type_supplied"),
        "type_name": relationship.get("type"),
        "lag_minutes": int(relationship["lag"]) * 60,
        "lag_type": PJ_HOURS,
    }
    for name, task in tasks.items():
        dependencies = task.get("task_dependencies")
        reduced = []
        if isinstance(dependencies, list):
            for dependency in dependencies:
                if isinstance(dependency, Mapping):
                    reduced.append(
                        {
                            field: dependency.get(field)
                            for field in expected_dependency
                        }
                    )
        if reduced != [expected_dependency]:
            conditions.append(
                {
                    "condition": "native_relationship_readback_changed",
                    "stage": stage,
                    "task": name,
                    "expected": expected_dependency,
                    "observed": reduced,
                }
            )
    return conditions


def _capture_schedule_projection(capture: Mapping[str, Any]) -> dict[str, Any] | None:
    tasks = _capture_task_map(capture)
    project = capture.get("project")
    if tasks is None or not isinstance(project, Mapping):
        return None
    task_fields = (
        "id",
        "unique_id",
        "name",
        "start",
        "finish",
        "duration_minutes",
        "manual",
        "type",
        "effort_driven",
        "calendar",
        "constraint_type",
        "constraint_date",
        "actual_start",
        "actual_finish",
        "percent_complete",
        "resource_names",
        "task_dependencies",
    )
    return {
        "project": {
            field: project.get(field)
            for field in (
                "start",
                "finish",
                "schedule_from_start",
                "calendar",
                "status_date",
                "resource_count",
                "default_task_type",
                "default_effort_driven",
                "new_tasks_created_as_manual",
                "calculation_mode",
                "resource_leveling_automatic",
            )
        },
        "tasks": {
            name: {field: task.get(field) for field in task_fields}
            for name, task in sorted(tasks.items())
        },
    }


def _xml_case_stop_conditions(
    xml_observation: Mapping[str, Any],
    capture: Mapping[str, Any],
    facts: Mapping[str, Any],
    assignment: Mapping[str, Any],
    *,
    stage: str,
) -> list[dict[str, Any]]:
    conditions: list[dict[str, Any]] = []
    try:
        calendar = validated_cal24x7_calendar(xml_observation)
    except Exception as error:
        return [
            {
                "condition": "xml_cal24x7_invalid",
                "stage": stage,
                "error": str(error),
            }
        ]
    project = xml_observation.get("project")
    if not isinstance(project, Mapping):
        return [{"condition": "xml_project_structure_changed", "stage": stage}]
    if not _unset_native_value(project.get("status_date")):
        conditions.append(
            {
                "condition": "unexpected_xml_status_date",
                "stage": stage,
                "observed": project.get("status_date"),
            }
        )
    capture_project = capture.get("project")
    if not isinstance(capture_project, Mapping):
        conditions.append(
            {"condition": "native_capture_project_missing", "stage": stage}
        )
    else:
        for field, xml_field in (("start", "start"), ("finish", "finish")):
            _append_required_xml_com_wall_clock_condition(
                conditions,
                stage=stage,
                field=f"project.{field}",
                com_value=capture_project.get(field),
                xml_value=project.get(xml_field),
            )

    resources = xml_observation.get("resources")
    if not isinstance(resources, list) or any(
        not isinstance(resource, Mapping)
        or resource.get("uid") != "0"
        or resource.get("id") != "0"
        or not _unset_native_value(resource.get("name"))
        or resource.get("actual_work") not in (None, "PT0H0M0S")
        for resource in resources
    ):
        conditions.append(
            {
                "condition": "unexpected_xml_resources",
                "stage": stage,
                "observed": resources,
            }
        )

    raw_tasks = xml_observation.get("tasks")
    capture_tasks = _capture_task_map(capture)
    if not isinstance(raw_tasks, list) or capture_tasks is None:
        return conditions + [
            {"condition": "xml_task_structure_changed", "stage": stage}
        ]
    xml_tasks: dict[str, Mapping[str, Any]] = {}
    summary_count = 0
    for task in raw_tasks:
        if not isinstance(task, Mapping):
            return conditions + [
                {"condition": "xml_task_structure_changed", "stage": stage}
            ]
        if task.get("uid") == "0" and task.get("id") == "0":
            summary_count += 1
            continue
        name = task.get("name")
        if not isinstance(name, str) or name in xml_tasks:
            return conditions + [
                {"condition": "xml_task_structure_changed", "stage": stage}
            ]
        xml_tasks[name] = task
    if summary_count != 1 or set(xml_tasks) != {"A", "B"}:
        return conditions + [
            {
                "condition": "xml_task_structure_changed",
                "stage": stage,
                "summary_task_count": summary_count,
                "task_names": sorted(xml_tasks),
            }
        ]

    source_by_name = {
        str(item["name"]): item for item in facts["activity_inputs"]
    }
    for name in ("A", "B"):
        xml_task = xml_tasks[name]
        com_task = capture_tasks[name]
        source_task = source_by_name[name]
        expected_duration = f"PT{int(source_task['duration'])}H0M0S"
        expected_static = {
            "uid": str(com_task.get("unique_id")),
            "id": str(com_task.get("id")),
            "duration": expected_duration,
            "manual": "0",
            "type": str(PJ_FIXED_DURATION),
            "effort_driven": "0",
            "calendar_uid": calendar["uid"],
            "percent_complete": "0",
            "actual_duration": "PT0H0M0S",
            "actual_work": "PT0H0M0S",
        }
        mismatches = {
            field: {"expected": expected, "observed": xml_task.get(field)}
            for field, expected in expected_static.items()
            if xml_task.get(field) != expected
        }
        if (
            not _unset_native_value(xml_task.get("actual_start"))
            or not _unset_native_value(xml_task.get("actual_finish"))
        ):
            mismatches["actual_dates"] = {
                "expected": None,
                "observed": [
                    xml_task.get("actual_start"),
                    xml_task.get("actual_finish"),
                ],
            }
        if mismatches:
            conditions.append(
                {
                    "condition": "xml_task_properties_changed",
                    "stage": stage,
                    "task": name,
                    "mismatches": mismatches,
                }
            )
        for field in ("start", "finish"):
            _append_required_xml_com_wall_clock_condition(
                conditions,
                stage=stage,
                field=f"tasks.{name}.{field}",
                com_value=com_task.get(field),
                xml_value=xml_task.get(field),
            )
        constraints = source_task.get("constraints", [])
        expected_constraint_type = "4" if constraints else "0"
        if xml_task.get("constraint_type") != expected_constraint_type:
            conditions.append(
                {
                    "condition": "xml_task_constraint_changed",
                    "stage": stage,
                    "task": name,
                    "observed_type": xml_task.get("constraint_type"),
                }
            )
        if constraints:
            _append_required_xml_com_wall_clock_condition(
                conditions,
                stage=stage,
                field=f"tasks.{name}.constraint_date",
                com_value=com_task.get("constraint_date"),
                xml_value=xml_task.get("constraint_date"),
            )
        elif not (
            _unset_native_value(com_task.get("constraint_date"))
            and _unset_native_value(xml_task.get("constraint_date"))
        ):
            conditions.append(
                {
                    "condition": "unexpected_schedule_constraint_timestamp",
                    "stage": stage,
                    "field": f"tasks.{name}.constraint_date",
                    "com": com_task.get("constraint_date"),
                    "xml": xml_task.get("constraint_date"),
                }
            )

    relationship = facts["relationship_inputs"][0]
    predecessor = xml_tasks[str(relationship["predecessor_id"])]
    successor = xml_tasks[str(relationship["successor_id"])]
    expected_link = {
        "predecessor_uid": predecessor.get("uid"),
        "type": str(assignment["native_type_supplied"]),
        "link_lag": str(int(relationship["lag"]) * 60 * 10),
        "lag_format": str(PJ_HOURS),
    }
    if predecessor.get("predecessor_links") != [] or successor.get(
        "predecessor_links"
    ) != [expected_link]:
        conditions.append(
            {
                "condition": "xml_relationship_or_lag_transformed",
                "stage": stage,
                "expected_successor_link": expected_link,
                "observed_predecessor_links": predecessor.get("predecessor_links"),
                "observed_successor_links": successor.get("predecessor_links"),
            }
        )

    assignments = xml_observation.get("assignments")
    expected_task_uids = {xml_tasks["A"]["uid"], xml_tasks["B"]["uid"]}
    assignment_task_uids: list[Any] = []
    if isinstance(assignments, list):
        for item in assignments:
            if not isinstance(item, Mapping):
                assignment_task_uids.append(None)
                continue
            assignment_task_uids.append(item.get("task_uid"))
            if (
                item.get("resource_uid") != "-65535"
                or item.get("percent_work_complete") != "0"
                or not _unset_native_value(item.get("actual_start"))
                or not _unset_native_value(item.get("actual_finish"))
                or item.get("actual_work") not in (None, "PT0H0M0S")
            ):
                conditions.append(
                    {
                        "condition": "unexpected_xml_assignment_resource_or_progress",
                        "stage": stage,
                        "observed": dict(item),
                    }
                )
    if (
        not isinstance(assignments, list)
        or len(assignments) != 2
        or set(assignment_task_uids) != expected_task_uids
        or len(assignment_task_uids) != len(set(assignment_task_uids))
    ):
        conditions.append(
            {
                "condition": "xml_assignment_structure_changed",
                "stage": stage,
                "observed_task_uids": assignment_task_uids,
            }
        )
    return conditions


def _process_cleanup_stop_conditions(
    sessions: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    conditions: list[dict[str, Any]] = []
    for process in sessions:
        if process.get("forced_termination"):
            condition = "project_process_required_forced_termination"
        elif not process.get("exited"):
            condition = "project_process_did_not_exit"
        elif process.get("ownership_revalidated_before_quit") is not True:
            condition = "project_process_ownership_not_revalidated"
        elif process.get("termination_error") not in (None, ""):
            condition = "project_process_cleanup_error"
        else:
            continue
        conditions.append(
            {
                "condition": condition,
                "pid": process.get("pid"),
                "exited": process.get("exited"),
                "termination_error": process.get("termination_error"),
                "ownership_revalidated_before_quit": process.get(
                    "ownership_revalidated_before_quit"
                ),
            }
        )
    return conditions


def run_native_case(
    source_projection: Mapping[str, Any],
    case_workspace: Path,
    stage_callback: StageCallback | None = None,
) -> dict[str, Any]:
    """Construct, calculate, save/export, then reopen/recalculate one case."""

    case_id = str(source_projection["case_id"])
    facts = source_projection["source_facts"]
    case_workspace.mkdir(parents=True, exist_ok=True)
    initial_mpp = case_workspace / "initial-calculated.mpp"
    initial_xml = case_workspace / "initial-calculated.xml"
    reopened_mpp = case_workspace / "reopened-recalculated.mpp"
    reopened_xml = case_workspace / "reopened-recalculated.xml"
    sessions: list[dict[str, Any]] = []
    session = _open_application(stage_callback)
    try:
        project = _configure_blank_project(session, stage_callback)
        construction, assignment = _build_source_project(project, facts)
        with _stage(stage_callback, "calculation", pid=session.pid, case_id=case_id):
            if session.app.CalculateProject() is False:
                raise ProjectComError("CalculateProject returned False")
        initial = _capture_project(session.app, project, session=session)
        with _stage(stage_callback, "save", pid=session.pid, case_id=case_id):
            _save_mpp(session.app, initial_mpp)
        with _stage(stage_callback, "xml_export", pid=session.pid, case_id=case_id):
            _export_xml(session.app, session.pythoncom, initial_xml)
        initial_xml_observation = parse_project_xml_observation(initial_xml)
        with _stage(stage_callback, "close", pid=session.pid, case_id=case_id):
            session.close_project()
        with _stage(stage_callback, "quit", pid=session.pid, case_id=case_id):
            sessions.append({**session.process, **session.quit()})
    except Exception:
        with contextlib.suppress(Exception):
            session.close_project()
        sessions.append({**session.process, **session.quit()})
        raise

    initial_cleanup_conditions = _process_cleanup_stop_conditions(sessions[-1:])
    if initial_cleanup_conditions:
        raise ProjectComError(
            "initial Project process cleanup failed before reopen: "
            f"{initial_cleanup_conditions!r}"
        )

    reopen_session = _open_application(stage_callback, stage_name="reopen_startup")
    try:
        _required_set(reopen_session.app, "Calculation", PJ_MANUAL)
        with _stage(stage_callback, "reopen", pid=reopen_session.pid, case_id=case_id):
            reopened_project = _open_file(reopen_session.app, initial_mpp)
            _required_set(reopen_session.app, "AutoLevel", False)
            if reopen_session.app.LevelingOptions(False) is False:
                raise ProjectComError("reopened LevelingOptions(False) returned False")
        after_open = _capture_project(reopen_session.app, reopened_project, session=reopen_session)
        with _stage(stage_callback, "recalculation", pid=reopen_session.pid, case_id=case_id):
            if reopen_session.app.CalculateProject() is False:
                raise ProjectComError("reopened CalculateProject returned False")
        after_recalculation = _capture_project(reopen_session.app, reopened_project, session=reopen_session)
        with _stage(stage_callback, "reopen_save", pid=reopen_session.pid, case_id=case_id):
            _save_mpp(reopen_session.app, reopened_mpp)
        with _stage(stage_callback, "reopen_xml_export", pid=reopen_session.pid, case_id=case_id):
            _export_xml(reopen_session.app, reopen_session.pythoncom, reopened_xml)
        reopened_xml_observation = parse_project_xml_observation(reopened_xml)
        with _stage(stage_callback, "reopen_close", pid=reopen_session.pid, case_id=case_id):
            reopen_session.close_project()
        with _stage(stage_callback, "reopen_quit", pid=reopen_session.pid, case_id=case_id):
            sessions.append({**reopen_session.process, **reopen_session.quit()})
    except Exception:
        with contextlib.suppress(Exception):
            reopen_session.close_project()
        sessions.append({**reopen_session.process, **reopen_session.quit()})
        raise

    stop_conditions: list[dict[str, Any]] = []
    if assignment["type_transformed"] or assignment["lag_transformed"]:
        stop_conditions.append({"condition": "relationship_or_lag_transformed", "assignment": assignment})
    for stage_name, capture in (
        ("initial_calculated", initial),
        ("after_open", after_open),
        ("after_recalculation", after_recalculation),
    ):
        stop_conditions.extend(
            _case_capture_stop_conditions(
                capture, facts, assignment, stage=stage_name
            )
        )
    initial_projection = _capture_schedule_projection(initial)
    for stage_name, capture in (
        ("after_open", after_open),
        ("after_recalculation", after_recalculation),
    ):
        candidate = _capture_schedule_projection(capture)
        if initial_projection is None or candidate != initial_projection:
            stop_conditions.append(
                {
                    "condition": "reopened_native_schedule_changed",
                    "stage": stage_name,
                    "before": initial_projection,
                    "after": candidate,
                }
            )
    stop_conditions.extend(
        _xml_case_stop_conditions(
            initial_xml_observation,
            initial,
            facts,
            assignment,
            stage="initial_xml",
        )
    )
    stop_conditions.extend(
        _xml_case_stop_conditions(
            reopened_xml_observation,
            after_recalculation,
            facts,
            assignment,
            stage="reopened_xml",
        )
    )
    stop_conditions.extend(_process_cleanup_stop_conditions(sessions))
    return {
        "schema_version": "headless-msproject-native-observation-v0.2",
        "characterisation_label": TRACK_ID,
        "case_id": case_id,
        "captured_at": _now(),
        "source_construction": construction,
        "relationship_assignment": assignment,
        "initial_calculated": initial,
        "initial_xml_observation": initial_xml_observation,
        "reopen_after_open": after_open,
        "reopen_after_recalculate": after_recalculation,
        "reopened_xml_observation": reopened_xml_observation,
        "process_sessions": sessions,
        "artifacts": {
            "initial_mpp": str(initial_mpp),
            "initial_xml": str(initial_xml),
            "reopened_mpp": str(reopened_mpp),
            "reopened_xml": str(reopened_xml),
        },
        "stop_conditions": stop_conditions,
    }


def _file_version_info(path: Path) -> dict[str, Any]:
    _pythoncom, win32api, _client = _load_pywin32()
    info = win32api.GetFileVersionInfo(str(path), "\\")
    ms = int(info["FileVersionMS"])
    ls = int(info["FileVersionLS"])
    numeric = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    translations = win32api.GetFileVersionInfo(str(path), r"\VarFileInfo\Translation")
    fields: dict[str, Any] = {}
    if translations:
        language, codepage = translations[0]
        for key in ("ProductName", "ProductVersion", "FileVersion", "FileDescription", "CompanyName", "OriginalFilename"):
            try:
                fields[key] = win32api.GetFileVersionInfo(
                    str(path), f"\\StringFileInfo\\{language:04x}{codepage:04x}\\{key}"
                )
            except Exception:
                fields[key] = None
    return {"numeric_file_version": numeric, "string_fields": fields}


def _registry_click_to_run() -> dict[str, Any]:
    if winreg is None:
        return {}
    key_name = r"SOFTWARE\Microsoft\Office\ClickToRun\Configuration"
    names = ("ProductReleaseIds", "VersionToReport", "ClientVersionToReport", "Platform", "InstallationPath", "AudienceData")
    values: dict[str, Any] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_name) as key:
            for name in names:
                try:
                    values[name] = winreg.QueryValueEx(key, name)[0]
                except OSError:
                    values[name] = None
    except OSError:
        pass
    return values


def _format_utc_offset(value: timedelta | None) -> str | None:
    if value is None:
        return None
    total_seconds = int(value.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_minutes = abs(total_seconds) // 60
    hours, minutes = divmod(total_minutes, 60)
    return f"{sign}{hours:02d}:{minutes:02d}"


def _capture_windows_time_zone() -> dict[str, Any]:
    local = datetime.now().astimezone()
    windows_name: str | None = None
    registry_bias_minutes: int | None = None
    if winreg is not None:
        key_name = r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation"
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_name) as key:
                try:
                    raw_name = winreg.QueryValueEx(key, "TimeZoneKeyName")[0]
                    windows_name = str(raw_name).rstrip("\x00") or None
                except OSError:
                    windows_name = None
                try:
                    registry_bias_minutes = int(winreg.QueryValueEx(key, "Bias")[0])
                except (OSError, TypeError, ValueError):
                    registry_bias_minutes = None
        except OSError:
            pass
    observed_offset = _format_utc_offset(local.utcoffset())
    return {
        "windows_name": windows_name,
        "local_tzname": local.tzname(),
        "utc_offset": observed_offset,
        "registry_bias_minutes": registry_bias_minutes,
        "expected_perth_windows_name": "W. Australia Standard Time",
        "expected_perth_utc_offset": "+08:00",
        "matches_required_perth_zone": (
            windows_name == "W. Australia Standard Time"
            and observed_offset == "+08:00"
        ),
    }


def _windows_locale_name(function_name: str) -> str | None:
    if os.name != "nt":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = getattr(kernel32, function_name, None)
    if function is None:
        return None
    buffer = ctypes.create_unicode_buffer(85)
    if int(function(buffer, len(buffer))) <= 0:
        return None
    return buffer.value


def _capture_windows_locale() -> dict[str, Any]:
    return {
        "preferred_encoding": locale.getpreferredencoding(False),
        "python_locale": str(locale.getlocale()),
        "windows_user_locale_name": _windows_locale_name(
            "GetUserDefaultLocaleName"
        ),
        "windows_system_locale_name": _windows_locale_name(
            "GetSystemDefaultLocaleName"
        ),
    }


def capture_environment(stage_callback: StageCallback | None = None) -> dict[str, Any]:
    executable = registered_project_executable()
    session = _open_application(stage_callback, stage_name="environment_project_startup")
    try:
        app = session.app
        product = {
            "name": _json_value(_required_get(app, "Name")),
            "edition_native": _json_value(_required_get(app, "Edition")),
            "edition": {0: "Standard", 1: "Professional"}.get(int(app.Edition), f"unknown:{app.Edition}"),
            "version": _json_value(_required_get(app, "Version")),
            "build": _json_value(_required_get(app, "Build")),
            "file_build_id": _json_value(_optional_call(app, "FileBuildID")),
            "application_path": _json_value(_required_get(app, "Path")),
            "visible": bool(_required_get(app, "Visible")),
            "com_prog_id": PROG_ID,
            "process_id": session.pid,
            "process_executable": session.process.get("executable_path"),
        }
    finally:
        cleanup = session.quit()
    cleanup_conditions = _process_cleanup_stop_conditions(
        [{**session.process, **cleanup}]
    )
    if cleanup_conditions:
        raise ProjectComError(
            f"environment Project process cleanup failed: {cleanup_conditions!r}"
        )
    os_key = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
    windows: dict[str, Any] = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, os_key) as key:
            for name in ("ProductName", "DisplayVersion", "CurrentBuildNumber", "UBR", "EditionID", "InstallationType"):
                try:
                    windows[name] = winreg.QueryValueEx(key, name)[0]
                except OSError:
                    windows[name] = None
    except OSError:
        pass
    file_identity = {
        "path": str(executable),
        "size_bytes": executable.stat().st_size,
        "sha256": sha256_file(executable),
        "version_info": _file_version_info(executable),
    }
    return {
        "schema_version": "headless-msproject-environment-v0.1",
        "captured_at": _now(),
        "microsoft_project": product,
        "project_process_cleanup": cleanup,
        "project_executable": file_identity,
        "click_to_run": _registry_click_to_run(),
        "windows": {
            **windows,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "architecture": platform.architecture()[0],
        },
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
            "architecture": platform.architecture()[0],
        },
        "locale": _capture_windows_locale(),
        "time_zone": _capture_windows_time_zone(),
    }


def run_preflight(workspace: Path, stage_callback: StageCallback | None = None) -> dict[str, Any]:
    observed_time_zone = _capture_windows_time_zone()
    if observed_time_zone.get("matches_required_perth_zone") is not True:
        raise ProjectComError(
            "native preflight requires the observed W. Australia Standard Time / +08:00 zone; "
            f"observed {observed_time_zone!r}"
        )
    projection = {
        "case_id": "PREFLIGHT",
        "source_facts": {
            "time_axis": {"origin": ORIGIN},
            "activity_inputs": [
                {"id": "A", "name": "A", "duration": 1, "constraints": []},
                {"id": "B", "name": "B", "duration": 1, "constraints": []},
            ],
            "relationship_inputs": [
                {"id": "R1", "predecessor_id": "A", "successor_id": "B", "type": "FS", "lag": -1}
            ],
        },
    }
    result = run_native_case(projection, workspace, stage_callback)
    required = {
        "create_blank_project": True,
        "remain_hidden": True,
        "set_calculation_mode": True,
        "set_project_start": True,
        "create_tasks": True,
        "set_durations": True,
        "set_task_mode": True,
        "set_task_type": True,
        "set_effort_driven": True,
        "set_predecessors": True,
        "set_signed_lag": True,
        "assign_24_hours_calendar": True,
        "invoke_native_calculation": True,
        "read_start_finish": True,
        "save_mpp": True,
        "close": True,
        "reopen": True,
        "recalculate": True,
        "export_project_xml": True,
        "quit_cleanly": all(
            item.get("exited") and not item.get("forced_termination")
            for item in result["process_sessions"]
        ),
    }
    if result["stop_conditions"] or not all(required.values()):
        raise ProjectComError(f"headless preflight failed: {result['stop_conditions']!r}, {required!r}")
    return {
        "schema_version": "headless-msproject-preflight-v0.1",
        "characterisation_label": TRACK_ID,
        "completed_at": _now(),
        "observed_time_zone": observed_time_zone,
        "required_operations": required,
        "process_sessions": result["process_sessions"],
        "xml_observation": result["initial_xml_observation"],
        "artifact_paths": result["artifacts"],
    }


def run_calendar_characterisation(
    workspace: Path, stage_callback: StageCallback | None = None
) -> dict[str, Any]:
    """Author/export 24 Hours, reopen that exact XML, recalc and re-export."""

    workspace.mkdir(parents=True, exist_ok=True)
    authored_mpp = workspace / "project-authored-24-hours.mpp"
    authored_xml = workspace / "project-authored-24-hours.xml"
    reopened_xml = workspace / "project-authored-24-hours-reexported.xml"
    sessions: list[dict[str, Any]] = []
    session = _open_application(stage_callback, stage_name="calendar_startup")
    try:
        project = _configure_blank_project(session, stage_callback)
        task = project.Tasks.Add("CAL-24X7-characterisation")
        _required_set(task, "Manual", False)
        _required_set(task, "Type", PJ_FIXED_DURATION)
        _required_set(task, "EffortDriven", False)
        _required_set(task, "Calendar", "24 Hours")
        task.Duration = "24h"
        with _stage(stage_callback, "calendar_calculation", pid=session.pid):
            if session.app.CalculateProject() is False:
                raise ProjectComError("calendar CalculateProject returned False")
        before_dates = _capture_project(session.app, project, session=session)
        with _stage(stage_callback, "calendar_save", pid=session.pid):
            _save_mpp(session.app, authored_mpp)
        with _stage(stage_callback, "calendar_xml_export", pid=session.pid):
            _export_xml(session.app, session.pythoncom, authored_xml)
        first_xml = parse_project_xml_observation(authored_xml)
        session.close_project()
        sessions.append({**session.process, **session.quit()})
    except Exception:
        with contextlib.suppress(Exception):
            session.close_project()
        sessions.append({**session.process, **session.quit()})
        raise

    authored_cleanup_conditions = _process_cleanup_stop_conditions(sessions[-1:])
    if authored_cleanup_conditions:
        raise ProjectComError(
            "calendar authoring process cleanup failed before XML reopen: "
            f"{authored_cleanup_conditions!r}"
        )

    reopen = _open_application(stage_callback, stage_name="calendar_reopen_startup")
    try:
        _required_set(reopen.app, "Calculation", PJ_MANUAL)
        with _stage(stage_callback, "calendar_xml_reopen", pid=reopen.pid):
            project = _open_project_xml(reopen.app, authored_xml)
            _required_set(reopen.app, "AutoLevel", False)
            if reopen.app.LevelingOptions(False) is False:
                raise ProjectComError("calendar reopened LevelingOptions(False) returned False")
        after_open_dates = _capture_project(reopen.app, project, session=reopen)
        with _stage(stage_callback, "calendar_recalculation", pid=reopen.pid):
            if reopen.app.CalculateProject() is False:
                raise ProjectComError("calendar reopened CalculateProject returned False")
        after_recalculate_dates = _capture_project(reopen.app, project, session=reopen)
        with _stage(stage_callback, "calendar_reexport", pid=reopen.pid):
            _export_xml(reopen.app, reopen.pythoncom, reopened_xml)
        second_xml = parse_project_xml_observation(reopened_xml)
        reopen.close_project()
        sessions.append({**reopen.process, **reopen.quit()})
    except Exception:
        with contextlib.suppress(Exception):
            reopen.close_project()
        sessions.append({**reopen.process, **reopen.quit()})
        raise
    first_calendar = validated_cal24x7_calendar(first_xml)
    second_calendar = validated_cal24x7_calendar(second_xml)
    if first_calendar != second_calendar:
        raise ProjectComError(
            "CAL-24X7 representation changed after exact XML reopen/recalculate/re-export"
        )
    cleanup_conditions = _process_cleanup_stop_conditions(sessions)
    if cleanup_conditions:
        raise ProjectComError(
            f"calendar characterisation process cleanup failed: {cleanup_conditions!r}"
        )
    return {
        "schema_version": "headless-msproject-cal24x7-characterisation-v0.1",
        "characterisation_label": TRACK_ID,
        "completed_at": _now(),
        "project_authored_xml": first_xml,
        "reexported_xml": second_xml,
        "calendar_representation_before": first_calendar,
        "calendar_representation_after": second_calendar,
        "calendar_representation_stable": True,
        "xml_reopen_method": "Application.OpenXML(exact_exported_utf8_text)",
        "xml_reopen_source_sha256": sha256_file(authored_xml),
        "task_dates_before_xml_reopen": before_dates,
        "task_dates_after_xml_open": after_open_dates,
        "task_dates_after_xml_recalculate": after_recalculate_dates,
        "automatic_track_c_unblock": False,
        "process_sessions": sessions,
        "artifacts": {
            "authored_mpp": str(authored_mpp),
            "authored_xml": str(authored_xml),
            "reexported_xml": str(reopened_xml),
        },
    }


def failure_record(error: BaseException, *, stage_state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "headless-msproject-failure-v0.1",
        "characterisation_label": TRACK_ID,
        "classification": "characterisation_inconclusive",
        "failed_at": _now(),
        "error_type": type(error).__name__,
        "error": str(error),
        "stage_state": dict(stage_state or {}),
        "traceback": traceback.format_exception(type(error), error, error.__traceback__),
    }
