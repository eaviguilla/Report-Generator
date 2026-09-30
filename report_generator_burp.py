# -*- coding: utf-8 -*-
"""Report Generator launcher for Burp Suite: one Jython 2.7 file on Burp's legacy Extender API.

It starts the Report Generator web app as a separate Python 3 process (`app/init.py`, in the folder this
file sits in), shows its output, and stops it. The app, its page and its data are unchanged, and
nothing is hidden: the folder, the exact command and the address are printed in the tab.

Three sections:
  1. ServerProcess, LineBuffer and helpers: no `burp` import, so any Jython can run them.
  2. LauncherPanel: plain Swing, with everything Burp-specific injected, so it can be driven headless.
  3. BurpExtender: the only place the `burp` package is touched.

Jython 2.7 rules kept throughout: Python 2 syntax only, `u""` literals for text that meets Java,
paths through java.io.File, every wait on a worker thread and never on the Swing thread, and an
`except (Exception, Throwable)` wherever a Java exception can arrive.
"""
import json
import sys
import threading
import traceback
from collections import deque

from java.awt import BorderLayout, Desktop, FlowLayout, Font
from java.awt.event import ActionListener
from java.io import BufferedReader, File, InputStreamReader
from java.lang import Object, ProcessBuilder, Runnable, System, Throwable
from java.lang import Thread as JThread
from java.net import InetSocketAddress, Proxy, Socket, URI, URL
from java.util import ArrayList
from java.util.concurrent import TimeUnit
from javax.swing import JButton, JFileChooser, JLabel, JOptionPane, JPanel, JScrollPane, JTextArea, JTextField, SwingUtilities
from javax.swing import Timer
from jarray import array

# Shared with app/init.py (a test pins both): what its "ready" line starts with, and the variable that tells it
# it was started from here. Nothing else is shared: the data folder and the port stay entirely in app/init.py.
ADDRESS_LINE = u"Report Generator is running at "
BURP_FLAG = u"VULNREPORT_STARTED_BY_BURP"

MAX_LINES = 2000
TICK_MS = 250
NOTE = u"[launcher] "


# --- 1. process handling ------------------------------------------------------------------------------

class LineBuffer(object):
    """The last MAX_LINES lines of output, written by the reader thread and read by the tab's timer."""

    def __init__(self):
        self._lock = threading.Lock()
        self._lines = deque(maxlen=MAX_LINES)
        self._count = 0
        self.address = None

    def add(self, line):
        with self._lock:
            self._lines.append(line)
            self._count += 1
            if self.address is None and line.startswith(ADDRESS_LINE):
                self.address = line[len(ADDRESS_LINE):]  # exactly as printed: never rewritten

    def note(self, text):
        self.add(NOTE + text)

    def snapshot(self):
        with self._lock:
            return self._count, list(self._lines)

    def forget_address(self):
        with self._lock:
            self.address = None


class _Reader(Runnable):
    """Drains the server's output. It waits on nothing but the pipe: a full pipe would stall the server."""

    def __init__(self, process, buffer):
        self._process = process
        self._buffer = buffer

    def run(self):
        try:
            reader = BufferedReader(InputStreamReader(self._process.getInputStream(), u"UTF-8"))
            while True:
                line = reader.readLine()
                if line is None:
                    break
                self._buffer.add(line)
        except (Exception, Throwable):
            pass


def is_windows():
    return System.getProperty(u"os.name").lower().startswith(u"windows")


def _arguments(words):
    arguments = ArrayList()  # a java.util.List, so ProcessBuilder's List constructor is the one chosen
    for word in words:
        arguments.add(word)
    return arguments


def launcher_file(app_folder):
    """The app's launcher, written once: <release folder>/app/init.py (Jython 2.7's File has no varargs join)."""
    return File(File(app_folder, u"app"), u"init.py")


class ServerProcess(object):
    """The app's process: start, stop by closing its input, Force stop, and whether it is still alive."""

    def __init__(self, buffer, app_folder, python_words):
        self.buffer = buffer
        self.app_folder = app_folder
        self.python_words = list(python_words)
        self.process = None

    def command(self):
        return self.python_words + [launcher_file(self.app_folder).getPath()]

    def start(self):
        builder = ProcessBuilder(_arguments(self.command()))
        builder.directory(File(self.app_folder))
        builder.redirectErrorStream(True)
        environment = builder.environment()
        environment.put(u"PYTHONUNBUFFERED", u"1")
        environment.put(u"PYTHONIOENCODING", u"utf-8")
        environment.put(BURP_FLAG, u"1")
        try:
            self.process = builder.start()
        except (Exception, Throwable) as error:
            self.buffer.note(u"Could not start: %s" % error)
            return False
        reader = JThread(_Reader(self.process, self.buffer))
        reader.setDaemon(True)
        reader.setName(u"report-generator-output")
        reader.start()
        return True

    def is_alive(self):
        return self.process is not None and self.process.isAlive()

    def exit_code(self):
        return self.process.exitValue()

    def wait_for(self, seconds):
        return self.process.waitFor(int(seconds), TimeUnit.SECONDS)

    def stop(self):
        """Close the server's standard input: app/init.py treats end of input as "finish what you are doing and exit"."""
        if self.process is None:
            return
        try:
            self.process.getOutputStream().close()
        except (Exception, Throwable):
            pass

    def force_stop(self):
        """End the server and the processes it had when this was called. Never by process name.

        Returns the handles it killed, so a check can confirm they are gone.
        """
        killed = []
        if self.process is None:
            return killed
        try:
            iterator = self.process.toHandle().descendants().iterator()  # needs Java 9 or newer
            while iterator.hasNext():
                killed.append(iterator.next())
            listed = True
        except (Exception, Throwable):
            listed = False
        for handle in killed:
            try:
                handle.destroyForcibly()
            except (Exception, Throwable):
                pass
        try:
            killed.insert(0, self.process.toHandle())
        except (Exception, Throwable):
            pass
        self.process.destroyForcibly()
        if not listed:
            self.buffer.note(u"Could not list child processes; only the main process was ended.")
        return killed


def run_command(words, folder=None, on_line=None):
    """Run a command to its end and return (exit code, output). Blocks: worker threads only."""
    builder = ProcessBuilder(_arguments(words))
    if folder is not None:
        builder.directory(File(folder))
    builder.redirectErrorStream(True)
    process = builder.start()
    reader = BufferedReader(InputStreamReader(process.getInputStream(), u"UTF-8"))
    lines = []
    while True:
        line = reader.readLine()
        if line is None:
            break
        lines.append(line)
        if on_line is not None:
            on_line(line)
    return process.waitFor(), u"\n".join(lines)


def resolve_python(field):
    """The interpreter to run: the tab's field when filled in, else the first usual name that says Python 3."""
    field = (field or u"").strip()
    if field:
        return [field]
    candidates = [[u"py", u"-3"], [u"python"]] if is_windows() else [[u"python3"]]
    for words in candidates:
        try:
            code, text = run_command(words + [u"--version"])
        except (Exception, Throwable):
            continue
        if code == 0 and text.strip().startswith(u"Python 3"):
            return words
    return None


def data_status(app_folder, python_words):
    """app/init.py --data-status as a dict, or None when it cannot be read. It changes nothing on disk."""
    try:
        code, text = run_command(python_words + [launcher_file(app_folder).getPath(), u"--data-status"], app_folder)
    except (Exception, Throwable):
        return None
    for line in reversed(text.splitlines()):
        if line.startswith(u"{"):
            try:
                return json.loads(line)
            except ValueError:
                return None
    return None


def http_status(url, timeout_ms):
    connection = URL(url).openConnection(Proxy.NO_PROXY)
    connection.setConnectTimeout(timeout_ms)
    connection.setReadTimeout(timeout_ms)
    try:
        return connection.getResponseCode()
    finally:
        connection.disconnect()


def port_answers(url):
    port = int(url.rsplit(u":", 1)[1].split(u"/")[0])
    sock = Socket()
    try:
        sock.connect(InetSocketAddress(u"127.0.0.1", port), 1000)
        return True
    except (Exception, Throwable):
        return False
    finally:
        try:
            sock.close()
        except (Exception, Throwable):
            pass


# --- 2. the panel -------------------------------------------------------------------------------------

_error_sink = [None]


def _report_error():
    """Put a traceback where the tester can see it: the tab if it exists, else Extender's Errors pane."""
    text = traceback.format_exc()
    sink = _error_sink[0]
    if sink is not None:
        sink(text)
    else:
        sys.stderr.write(text)


class _Call(Runnable):
    """A callable as a Runnable. An exception inside a Java callback would otherwise be lost."""

    def __init__(self, function, *arguments):
        self._function = function
        self._arguments = arguments

    def run(self):
        try:
            self._function(*self._arguments)
        except (Exception, Throwable):
            _report_error()


def in_background(function, *arguments):
    thread = JThread(_Call(function, *arguments))
    thread.setDaemon(True)
    thread.start()


def on_swing(function, *arguments):
    SwingUtilities.invokeLater(_Call(function, *arguments))


def wait_on_swing(function):
    """Run on the Swing thread and hand back the result; a worker thread is the caller."""
    box = []

    def call():
        box.append(function())

    if SwingUtilities.isEventDispatchThread():
        call()
    else:
        SwingUtilities.invokeAndWait(_Call(call))
    return box[0] if box else None


class _Click(ActionListener):
    def __init__(self, panel, name):
        self._panel = panel
        self._name = name

    def actionPerformed(self, event):
        try:
            self._panel.click(self._name)
        except (Exception, Throwable):
            _report_error()


class _Tick(ActionListener):
    def __init__(self, panel):
        self._panel = panel

    def actionPerformed(self, event):
        try:
            self._panel.tick()
        except (Exception, Throwable):
            _report_error()


class SwingDialogs(object):
    """The first-run question. Called from a worker; each dialog is shown on the Swing thread."""

    def ask_bring_over(self, folder):
        def choose():
            options = array([u"Bring reports over...", u"Start fresh", u"Cancel"], Object)
            picked = JOptionPane.showOptionDialog(
                None,
                u"This Report Generator folder has no reports yet:\n%s\n\n"
                u"Bring reports over from a previous release folder (they are moved, not copied,\n"
                u"and the previous .venv is copied so packages are not downloaded again), or start fresh?" % folder,
                u"Report Generator", JOptionPane.DEFAULT_OPTION, JOptionPane.QUESTION_MESSAGE, None, options, options[0])
            if picked == 1:
                return (u"fresh", None)
            if picked != 0:
                return (u"cancel", None)
            stopped = JOptionPane.showConfirmDialog(
                None,
                u"Is the previous Report Generator stopped?\n(Press Stop in Burp, or close its console window.)\n"
                u"Its reports are moved out of its folder, so it must not be running.",
                u"Report Generator", JOptionPane.YES_NO_OPTION)
            if stopped != JOptionPane.YES_OPTION:
                return (u"cancel", None)
            chooser = JFileChooser()
            chooser.setDialogTitle(u"Choose the previous Report Generator folder")
            chooser.setFileSelectionMode(JFileChooser.DIRECTORIES_ONLY)
            if chooser.showOpenDialog(None) != JFileChooser.APPROVE_OPTION:
                return (u"cancel", None)
            return (u"bring", chooser.getSelectedFile().getPath())

        return wait_on_swing(choose) or (u"cancel", None)


class LauncherPanel(object):
    """The tab. `settings` has get(key) and put(key, value); `open_browser(url)` opens a browser;
    `dialogs.ask_bring_over(folder)` asks the first-run question; `log(text)` records a problem."""

    def __init__(self, app_folder, settings, open_browser, dialogs, log):
        self.app_folder = app_folder
        self.settings = settings
        self.open_browser = open_browser
        self.dialogs = dialogs
        self.log = log
        self.buffer = LineBuffer()
        self.server = None
        self.state = u"stopped"
        self.last_exit_code = None
        self._opened = False
        self._shown = 0
        self.installed = launcher_file(app_folder).isFile()

        self.status = JLabel()
        self.python_field = JTextField(settings.get(u"python") or u"", 24)
        self.start_button = JButton(u"Start")
        self.stop_button = JButton(u"Stop")
        self.open_button = JButton(u"Open")
        self.output = JTextArea(24, 100)
        self.output.setEditable(False)
        self.output.setLineWrap(True)
        self.output.setFont(Font(Font.MONOSPACED, Font.PLAIN, self.output.getFont().getSize()))

        top = JPanel(FlowLayout(FlowLayout.LEFT))
        for widget in (JLabel(u"Python:"), self.python_field, self.start_button, self.stop_button, self.open_button):
            top.add(widget)
        header = JPanel(BorderLayout())
        header.add(self.status, BorderLayout.NORTH)
        header.add(top, BorderLayout.SOUTH)
        self.component = JPanel(BorderLayout())
        self.component.add(header, BorderLayout.NORTH)
        self.component.add(JScrollPane(self.output), BorderLayout.CENTER)

        for button, name in ((self.start_button, u"start"), (self.stop_button, u"stop"), (self.open_button, u"open")):
            button.addActionListener(_Click(self, name))
        _error_sink[0] = self.show_problem
        self.timer = Timer(TICK_MS, _Tick(self))
        self._go(u"stopped")
        self.timer.start()

    # -- state, always on the Swing thread

    def _go(self, state):
        self.state = state
        self.start_button.setEnabled(state == u"stopped" and self.installed)
        self.stop_button.setEnabled(state in (u"setting_up", u"running", u"stopping"))
        self.stop_button.setText(u"Force stop" if state == u"stopping" else u"Stop")
        self.open_button.setEnabled(state == u"running")
        self.python_field.setEnabled(state == u"stopped")
        self.status.setText(self._status_text())

    def _status_text(self):
        where = u"Folder: %s.  " % self.app_folder
        if not self.installed:
            return where + u"Load this file from the Report Generator folder (the one that contains app/init.py)."
        if self.state == u"starting":
            return where + u"Starting..."
        if self.state == u"setting_up":
            return where + u"Setting up (a first run installs packages)..."
        if self.state == u"running":
            return where + u"Running at %s" % self.buffer.address
        if self.state == u"stopping":
            return where + u"Stopping: waiting for running work (a report being generated, or setup) to finish. Force stop ends it now."
        if self.last_exit_code not in (None, 0):
            return where + u"Stopped (exit code %s)." % self.last_exit_code
        return where + u"Stopped."

    def show_problem(self, text):
        self.buffer.note(u"Problem in the launcher:\n" + text)
        self.log(text)

    # -- what the buttons do

    def click(self, name):
        if name == u"start":
            if self.state != u"stopped":
                return
            self._go(u"starting")
            in_background(self._start_job, (self.python_field.getText() or u"").strip())
        elif name == u"stop":
            if self.state == u"stopping":
                in_background(self._force_stop)
            elif self.state in (u"setting_up", u"running") and self.server is not None:
                self.server.stop()
                self._go(u"stopping")
        elif name == u"open":
            if self.buffer.address:
                self.open_browser(self.buffer.address)

    def _force_stop(self):
        if self.server is not None:
            self.server.force_stop()

    # -- starting, on a worker thread: nothing here may wait on the Swing thread except through wait_on_swing

    def _start_job(self, python_text):
        try:
            self.settings.put(u"python", python_text or None)
            words = resolve_python(python_text)
            if words is None:
                self.buffer.note(u"Could not find Python 3. Install it, or type the path to its executable in the Python field.")
                on_swing(self._go, u"stopped")
                return
            if not self._settle_data(words):
                on_swing(self._go, u"stopped")
                return
            server = ServerProcess(self.buffer, self.app_folder, words)
            self.buffer.forget_address()
            self.buffer.note(u"Folder: %s" % self.app_folder)
            self.buffer.note(u"Command: %s" % u" ".join(server.command()))
            if server.start():
                on_swing(self._begin, server)
            else:
                on_swing(self._go, u"stopped")
        except (Exception, Throwable):
            _report_error()
            on_swing(self._go, u"stopped")

    def _settle_data(self, words):
        """On a first Start with no reports, offer to bring a previous release's reports over. False to stop."""
        status = data_status(self.app_folder, words)
        fresh_key = u"fresh:" + self.app_folder
        if status is None or status.get(u"reports") != 0 or status.get(u"locked") or self.settings.get(fresh_key) == u"1":
            return True
        action, old_folder = self.dialogs.ask_bring_over(self.app_folder)
        if action == u"cancel":
            return False
        if action == u"fresh":
            self.settings.put(fresh_key, u"1")
            return True
        self.buffer.note(u"Bringing reports over from %s" % old_folder)
        code, _ = run_command(words + [launcher_file(self.app_folder).getPath(), u"--bring-over", old_folder], self.app_folder, self.buffer.add)
        if code != 0:
            self.buffer.note(u"Nothing was moved. Fix the problem above, or choose Start fresh.")
            return False
        return True

    def _begin(self, server):
        self.server = server
        self._opened = False
        self._go(u"setting_up")

    # -- the timer, on the Swing thread

    def tick(self):
        count, lines = self.buffer.snapshot()
        new = min(count - self._shown, len(lines))
        if new > 0:
            self._shown = count
            self.output.append(u"\n".join(lines[len(lines) - new:]) + u"\n")
            if self.output.getLineCount() > MAX_LINES + 500:
                self.output.setText(u"\n".join(lines) + u"\n")
            self.output.setCaretPosition(self.output.getDocument().getLength())
        server = self.server
        if server is None or server.process is None:
            return
        if server.is_alive():
            if self.state == u"setting_up" and self.buffer.address:
                self._go(u"running")
                if not self._opened:
                    self._opened = True
                    self.open_browser(self.buffer.address)
        else:
            self.last_exit_code = server.exit_code()
            self.server = None
            self._go(u"stopped")

    def shutdown(self):
        """The extension is unloading (any thread): close the server's input and let it finish. Nothing is killed."""
        server = self.server
        if server is not None:
            server.stop()
        on_swing(self.timer.stop)


# --- 3. Burp ------------------------------------------------------------------------------------------

try:
    from burp import IBurpExtender, ITab, IExtensionStateListener
except ImportError:  # loaded by a plain Jython for the self-checks
    class IBurpExtender(object):
        pass

    class ITab(object):
        pass

    class IExtensionStateListener(object):
        pass


class BurpSettings(object):
    """Burp's saved extension settings. Whether they are kept per project or per user is Burp's choice."""

    def __init__(self, callbacks):
        self._callbacks = callbacks

    def get(self, key):
        try:
            return self._callbacks.loadExtensionSetting(key)
        except (Exception, Throwable):
            return None

    def put(self, key, value):
        try:
            self._callbacks.saveExtensionSetting(key, value)
        except (Exception, Throwable):
            pass


def open_in_browser(url):
    try:
        if Desktop.isDesktopSupported() and Desktop.getDesktop().isSupported(Desktop.Action.BROWSE):
            Desktop.getDesktop().browse(URI(url))
            return True
    except (Exception, Throwable):
        pass
    return False


class _BuildTab(Runnable):
    def __init__(self, extender):
        self._extender = extender

    def run(self):
        extender = self._extender
        try:
            callbacks = extender.callbacks
            folder = File(callbacks.getExtensionFilename()).getParentFile().getPath()

            def open_browser(url):
                if not open_in_browser(url):
                    extender.panel.buffer.note(u"Could not open a browser. Copy the address from the status line: %s" % url)

            extender.panel = LauncherPanel(folder, BurpSettings(callbacks), open_browser, SwingDialogs(), callbacks.printError)
            callbacks.customizeUiComponent(extender.panel.component)
            output = extender.panel.output  # Burp's styling resets the font, so choose the monospaced one after it
            output.setFont(Font(Font.MONOSPACED, Font.PLAIN, output.getFont().getSize()))
            callbacks.addSuiteTab(extender)
        except (Exception, Throwable):
            _report_error()


class BurpExtender(IBurpExtender, ITab, IExtensionStateListener):
    def __init__(self):
        self.callbacks = None
        self.panel = None

    def registerExtenderCallbacks(self, callbacks):
        self.callbacks = callbacks
        callbacks.setExtensionName(u"Report Generator")
        callbacks.registerExtensionStateListener(self)  # first, so unloading works even if the tab fails to build
        SwingUtilities.invokeLater(_BuildTab(self))

    def getTabCaption(self):
        return u"Report Generator"

    def getUiComponent(self):
        return self.panel.component

    def extensionUnloaded(self):
        if self.panel is not None:
            self.panel.shutdown()


# --- self-checks, run by tests/test_launcher.py under a plain Jython --------------------------------------

def _say(text):
    sys.stdout.write(text + u"\n")
    sys.stdout.flush()


def _wait_until(condition, seconds):
    deadline = System.currentTimeMillis() + int(seconds * 1000)
    while System.currentTimeMillis() < deadline:
        if condition():
            return True
        JThread.sleep(200)
    return condition()


def self_check(app_folder, python_exe):
    """Start the app, flood its output, stop it, start it again and force-stop it. 0 when all of it held."""
    words = [python_exe]
    status = data_status(app_folder, words)
    if status is None:
        _say(u"FAIL: app/init.py --data-status could not be read")
        return 1
    if status.get(u"reports") != 0:
        _say(u"Refusing to run: the data folder %s holds %s report(s), and the self-check must never touch real reports."
             % (status.get(u"data"), status.get(u"reports")))
        return 2
    failures = []

    def check(passed, text):
        _say((u"ok:   " if passed else u"FAIL: ") + text)
        if not passed:
            failures.append(text)

    buffer = LineBuffer()
    server = ServerProcess(buffer, app_folder, words)
    check(server.start(), u"the app starts")
    check(_wait_until(lambda: buffer.address is not None, 180), u"the address line arrives (a first run installs packages)")
    address = buffer.address
    if address:
        try:
            check(http_status(address, 30000) == 200, u"the address answers")
            answered = 0
            for _ in range(50):
                http_status(address + u"/" + u"a" * 4096, 30000)  # a 404 with a long access-log line
                answered += 1
            check(answered == 50, u"50 long requests were all answered while nothing read the output buffer")
        except (Exception, Throwable) as error:
            check(False, u"requests to the app failed: %s" % error)
    server.stop()
    check(server.wait_for(15), u"Stop ends the app within 15 seconds")
    check(not server.is_alive() and server.exit_code() == 0, u"Stop exits with code 0")
    if address:
        check(not port_answers(address), u"the port is closed after Stop")

    second = LineBuffer()
    again = ServerProcess(second, app_folder, words)
    check(again.start(), u"the app starts again")
    check(_wait_until(lambda: second.address is not None, 180), u"the address line arrives the second time")
    killed = again.force_stop()
    check(_wait_until(lambda: not any(handle.isAlive() for handle in killed), 15), u"Force stop ends every process it saw")
    if second.address:
        check(not port_answers(second.address), u"the port is closed after Force stop")

    missing = LineBuffer()
    check(not ServerProcess(missing, app_folder, [u"/no/such/python"]).start(), u"a missing Python is refused without an exception")
    check(any(u"Could not start" in line for line in missing.snapshot()[1]), u"and the reason is written to the output")
    return 1 if failures else 0


class _FakeSettings(object):
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def put(self, key, value):
        if value is None:
            self.values.pop(key, None)
        else:
            self.values[key] = value


class _FakeDialogs(object):
    def __init__(self):
        self.asked = 0

    def ask_bring_over(self, folder):
        self.asked += 1
        return (u"fresh", None)


def self_check_panel(app_folder, python_exe):
    """Drive the tab headless with fakes: Start, wait for Running, Stop. 0 when it behaved."""
    settings, dialogs, opened, problems = _FakeSettings(), _FakeDialogs(), [], []
    holder = []
    SwingUtilities.invokeAndWait(_Call(lambda: holder.append(LauncherPanel(app_folder, settings, opened.append, dialogs, problems.append))))
    if not holder:
        _say(u"FAIL: the panel could not be built")
        return 1
    panel = holder[0]
    failures = []

    def check(passed, text):
        _say((u"ok:   " if passed else u"FAIL: ") + text)
        if not passed:
            failures.append(text)

    SwingUtilities.invokeAndWait(_Call(lambda: panel.python_field.setText(python_exe)))
    for round_number in (1, 2):
        SwingUtilities.invokeAndWait(_Call(panel.start_button.doClick))
        check(_wait_until(lambda: panel.state == u"running", 240), u"round %d: the panel reaches Running" % round_number)
        SwingUtilities.invokeAndWait(_Call(panel.stop_button.doClick))
        check(_wait_until(lambda: panel.state == u"stopped", 30), u"round %d: Stop brings it back to Stopped" % round_number)
        check(panel.last_exit_code == 0, u"round %d: the app exited with code 0" % round_number)
    check(len(opened) == 2 and all(url.startswith(u"http://127.0.0.1:") for url in opened), u"the browser opened once per Start, at the printed address")
    check(dialogs.asked == 1, u"the first-run question was asked once, and Start fresh was remembered")
    check(settings.get(u"fresh:" + app_folder) == u"1", u"Start fresh is saved for this folder")
    check(not problems, u"no problem was reported: %s" % problems)
    SwingUtilities.invokeAndWait(_Call(panel.shutdown))
    return 1 if failures else 0


def _run_self_check(argv):
    if len(argv) < 4:
        _say(u"usage: report_generator_burp.py --self-check|--self-check-panel <app folder> <python>")
        return 64
    try:
        return (self_check_panel if argv[1] == u"--self-check-panel" else self_check)(argv[2], argv[3])
    except (Exception, Throwable):
        _say(traceback.format_exc())
        return 1


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1].startswith("--self-check"):
    System.exit(_run_self_check(sys.argv))
