"""One Manager at a time.

Two copies each start their own voice bridges: both tail dcs.log and transmit every ATC
reply, and both reach for the microphone. The symptoms look like faults in the module,
which is what makes this worth enforcing rather than documenting.
"""

import sys

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "manager"))

import single_instance  # noqa: E402


class FakeKernel32(object):
    """Stands in for the Windows mutex API."""

    def __init__(self, already_exists=False, handle=1234):
        self.already_exists = already_exists
        self.handle = handle
        self.created = []
        self.closed = []

    def CreateMutexW(self, attributes, initial_owner, name):
        self.created.append(name)
        return self.handle

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True


@pytest.fixture
def on_windows(monkeypatch):
    monkeypatch.setattr(single_instance, "available", lambda: True)


class TestTheLock:
    def test_the_first_copy_gets_the_lock(self, on_windows):
        lock = single_instance.Lock(kernel32=FakeKernel32(), last_error=lambda: 0)
        assert lock.acquire() is True
        assert lock.already_running is False

    def test_a_second_copy_is_refused(self, on_windows):
        kernel32 = FakeKernel32()
        lock = single_instance.Lock(
            kernel32=kernel32,
            last_error=lambda: single_instance.ERROR_ALREADY_EXISTS)
        assert lock.acquire() is False
        assert lock.already_running is True
        assert kernel32.closed, "the duplicate handle must be released"

    def test_the_handle_is_kept_so_the_mutex_is_held(self, on_windows):
        """Letting it be collected would release the mutex and let a second Manager
        start while the first is still running."""
        lock = single_instance.Lock(kernel32=FakeKernel32(), last_error=lambda: 0)
        lock.acquire()
        assert lock._handle is not None

    def test_releasing_closes_the_handle(self, on_windows):
        kernel32 = FakeKernel32()
        lock = single_instance.Lock(kernel32=kernel32, last_error=lambda: 0)
        lock.acquire()
        lock.release()
        assert kernel32.closed == [kernel32.handle]
        assert lock._handle is None

    def test_releasing_twice_is_harmless(self, on_windows):
        lock = single_instance.Lock(kernel32=FakeKernel32(), last_error=lambda: 0)
        lock.acquire()
        lock.release()
        lock.release()


class TestItNeverBlocksStartup:
    """Failing to check must not stop the app running: the worst case of not knowing is
    the behaviour we already have."""

    def test_off_windows_it_always_allows(self, monkeypatch):
        monkeypatch.setattr(single_instance, "available", lambda: False)
        assert single_instance.Lock().acquire() is True

    def test_a_failed_mutex_call_allows(self, on_windows):
        class Broken(object):
            def CreateMutexW(self, *args):
                raise OSError("no")

        assert single_instance.Lock(kernel32=Broken()).acquire() is True

    def test_a_null_handle_allows(self, on_windows):
        assert single_instance.Lock(kernel32=FakeKernel32(handle=0),
                                    last_error=lambda: 0).acquire() is True

    def test_a_global_name_so_it_spans_sessions(self):
        """A per-session name would let a second copy start under another login and
        fight over the same microphone and log file."""
        assert single_instance.MUTEX_NAME.startswith("Global\\")


class TestShowingTheExistingWindow:
    def test_off_windows_it_does_nothing(self, monkeypatch):
        monkeypatch.setattr(single_instance, "available", lambda: False)
        assert single_instance.show_existing_window() is False

    def test_a_broken_api_is_not_an_error(self, on_windows):
        class Broken(object):
            def EnumWindows(self, *args):
                raise OSError("no")

        assert single_instance.show_existing_window(user32=Broken()) is False


class TestWiring:
    def test_main_takes_the_lock_before_building_a_window(self):
        """Checked first, so a second copy never gets as far as starting bridges."""
        source = (ROOT / "manager" / "app.py").read_text(encoding="utf-8")
        body = source.split("def main():", 1)[1]
        lock_at = body.index("single_instance.Lock()")
        window_at = body.index("tk.Tk()")
        assert lock_at < window_at

    def test_closing_releases_the_lock(self):
        source = (ROOT / "manager" / "app.py").read_text(encoding="utf-8")
        assert "lock.release()" in source
