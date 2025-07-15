"""OSD for wayland."""

import argparse
from ctypes import CDLL
import logging
import os
import re
import sys
import threading
import typing as t

# https://pycairo.readthedocs.io/en/latest/reference/index.html
import cairo

# For GTK4 Layer Shell to get linked before libwayland-client we must
# explicitly load it before importing with gi
CDLL("libgtk4-layer-shell.so")

# yapf: disable
# pylint: disable=wrong-import-position
import gi
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
# https://amolenaar.pages.gitlab.gnome.org/pygobject-docs/
from gi.repository import Gio
from gi.repository import Gdk
from gi.repository import GLib
from gi.repository import Gtk
# https://github.com/wmww/gtk4-layer-shell
from gi.repository import Gtk4LayerShell

from .version import __version__
# pylint: enable=wrong-import-position
# yapf: enable

logger: logging.Logger = logging.getLogger(__name__)

CONFIG_DIRS_SEARCH = [
    os.path.expanduser("~/.wlosd/"),
    # insert "${XDG_CONFIG_HOME}/wlosd/" here, see below
    os.path.expanduser("~/.config/wlosd/"),
    "/etc/xdg/wlosd/"
]
if "XDG_CONFIG_HOME" in os.environ:
    CONFIG_DIRS_SEARCH.insert(1,
                              os.path.expandvars("${XDG_CONFIG_HOME}/wlosd/"))


def find_config_file(name: str) -> t.Optional[str]:
    for directory in CONFIG_DIRS_SEARCH:
        path = os.path.join(directory, name)
        if os.path.isfile(path):
            return path
    return None


class MainApp(Gtk.Application):

    def __init__(self, css_file: t.Optional[str]) -> None:
        super().__init__(
            application_id="com.wlosd",
            # Allow multiple instances.
            flags=Gio.ApplicationFlags.NON_UNIQUE)

        self._windows: dict[str, Gtk.Window] = {}
        self._show_timers: dict[str, int] = {}

        self._display: Gdk.Display = Gdk.DisplayManager.get(
        ).get_default_display()

        self._css_file = css_file
        self._css_provider = None

        if self._css_file is not None:
            self._css_provider = Gtk.CssProvider()
            self._css_provider.load_from_path(self._css_file)
            Gtk.StyleContext.add_provider_for_display(
                self._display, self._css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_USER)

    def get_uids(self) -> t.Iterable[str]:
        return self._windows.keys()

    def on_activate(self, _src) -> None:
        self.hold()

    def cancel_hide_timer(self, uid: str) -> None:
        if uid not in self._show_timers:
            return
        GLib.source_remove(self._show_timers[uid])
        del self._show_timers[uid]

    def on_exit(self) -> bool:
        self.quit()
        return GLib.SOURCE_REMOVE

    def set_input_region(self, src):
        surface = src.get_native().get_surface()
        if surface:
            # pylint: disable-next=no-member
            surface.set_input_region(cairo.Region([]))

    def on_show(self, uid: str, text: str, is_markup: bool,
                hide_sec: float | None, classes: list[str], output: str | None,
                position: list) -> bool:
        self.cancel_hide_timer(uid)

        if uid not in self._windows:
            window = Gtk.Window(name=uid)
            window.connect("realize", self.set_input_region)

            # layout = Gtk.Fixed()
            # window.set_child(layout)

            label = Gtk.Label()
            # layout.put(label, 0, 0)
            window.set_child(label)

            Gtk4LayerShell.init_for_window(window)
            Gtk4LayerShell.set_layer(window, Gtk4LayerShell.Layer.OVERLAY)

            self._windows[uid] = window
        else:
            window = self._windows[uid]
            label = window.get_child()

        if output:
            found_monitor = False
            for monitor in self._display.get_monitors():
                if monitor.get_connector() == output:
                    Gtk4LayerShell.set_monitor(window, monitor)
                    break
            if not found_monitor:
                logger.warning("did not find output: %s", output)

        for gtk_edge in [
                Gtk4LayerShell.Edge.LEFT, Gtk4LayerShell.Edge.RIGHT,
                Gtk4LayerShell.Edge.TOP, Gtk4LayerShell.Edge.BOTTOM
        ]:
            Gtk4LayerShell.set_anchor(window, gtk_edge, gtk_edge in position)

        if is_markup:
            label.set_markup(text)
        else:
            label.set_text(text)

        label.set_css_classes(classes)

        # Make the window resize to match the label.
        window.set_default_size(1, 1)

        window.present()

        if hide_sec is not None:
            self._show_timers[uid] = GLib.timeout_add(int(hide_sec * 1000),
                                                      self.on_hide, uid)

        return GLib.SOURCE_REMOVE

    def on_hide(self, uids: list[str]) -> bool:
        for uid in uids:
            self.cancel_hide_timer(uid)
            if uid not in self._windows:
                logger.warning("no such id: %s", uid)
                continue

            self._windows[uid].destroy()
            del self._windows[uid]
        return GLib.SOURCE_REMOVE

    def on_reload_css(self) -> bool:
        if self._css_provider is None:
            return GLib.SOURCE_REMOVE
        self._css_provider.load_from_path(self._css_file)
        return GLib.SOURCE_REMOVE


class ParsingError(Exception):

    @staticmethod
    def throw(message: str) -> t.NoReturn:
        raise ParsingError(message)

    def __init__(self, message: str) -> None:
        self.message = message

    def __str__(self) -> str:
        return self.message


def cmds_listener(app: MainApp) -> None:
    commands = {
        "exit": "Terminate the program.",
        "help": "Display help information about cmd.",
        "hide": "Hide messages.",
        "list-uids": "List all currently showing uids.",
        "quit": "Terminate the program.",
        "reload-css": "Reload and reapply the css file.",
        "show":
            "Show a message."
            " The following input lines will compose the message text."
            " The text can include Pango markup."
            " By default, lines are read until the first empty line."
            " The --end-mark option can be used to change the end of input marker."
            " By default, the message will be displayed in the centre of the"
            " screen."
            " Use the -t, -b, -l, -r options to change the position."
            " A combination like -tl can be used to display the message in a"
            " corner (top-left in this case)."
            " The margin property in the style sheet can be used to further"
            " adjust the position.",
    }

    parser = argparse.ArgumentParser(
        exit_on_error=False,
        add_help=False,
        prog="",
        epilog="'help cmd' for more information about 'cmd'.")
    parser.error = ParsingError.throw  # type: ignore[method-assign]

    cmd_parsers = parser.add_subparsers(dest="command",
                                        required=True,
                                        title="Commands",
                                        metavar="cmd",
                                        help=f"one of {{{','.join(commands)}}}")

    parsers = {}
    for cmd, description in commands.items():
        parsers[cmd] = cmd_parsers.add_parser(cmd,
                                              prog=cmd,
                                              add_help=False,
                                              description=description)
        parsers[cmd].error = ParsingError.throw  # type: ignore[method-assign]

    # yapf: disable
    parsers["help"].add_argument("help_cmd", default=None, nargs="?",
                                 choices=([""] + list(commands)),
                                 metavar=",".join(commands))

    parsers["show"].add_argument("-b", "--bottom", dest="position", default=[],
                                 action="append_const", const=Gtk4LayerShell.Edge.BOTTOM,
                                 help="Display the message at the bottom of the screen.")
    parsers["show"].add_argument("-c", "--class", action="append", dest="classes",
                                 default=[], help="Assign CLASS to the window"
                                 " element of the message (for use with css).")
    parsers["show"].add_argument("-e", "--end-mark", default="", metavar="MARK",
                                 help="(default: \"\") terminate the message"
                                 " input when reading MARK.")
    parsers["show"].add_argument("-l", "--left", dest="position", default=[],
                                 action="append_const", const=Gtk4LayerShell.Edge.LEFT,
                                 help="Display the message on the left side of the screen.")
    parsers["show"].add_argument("-m", "--markup", action="store_true",
                                 help="Indicate that Pango markup is used in"
                                 " the text (<, > and & characters must be"
                                 " escaped as '&lt;', '&gt;', and '&amp;').")
    parsers["show"].add_argument("-o", "--output", default=None, metavar="OUT",
                                 help="Show the message on output OUT (e.g. DP-1).")
    parsers["show"].add_argument("-r", "--right", dest="position", default=[],
                                 action="append_const", const=Gtk4LayerShell.Edge.RIGHT,
                                 help="Display the message on the right side of the screen.")
    parsers["show"].add_argument("-s", "--sec", type=float, default=None,
                                 help="Hide the message after SEC seconds.")
    parsers["show"].add_argument("-t", "--top", dest="position", default=[],
                                 action="append_const", const=Gtk4LayerShell.Edge.TOP,
                                 help="Display the message at the top of the screen.")
    parsers["show"].add_argument("uid", help="A unique identifier; can be used"
                                 " to replace the message (by another show"
                                 " command) or hide it.")

    parsers["hide"].add_argument("-r", "--regex", action="store_true",
                                 help="Interpret uid as a (Python's re library) regular expression.")
    parsers["hide"].add_argument("uids", metavar="uid", nargs="+",
                                 help="uids to hide.")
    # yapf: enable

    while True:
        cmd_line: str = sys.stdin.readline()

        if cmd_line == "":
            logger.info("stdin was closed")
            GLib.idle_add(app.on_exit)
            return

        try:
            args = parser.parse_args(cmd_line.removesuffix("\n").split(" "))
        except argparse.ArgumentError as e:
            logger.warning("parsing error: %s", e)
            continue
        except argparse.ArgumentTypeError as e:
            logger.warning("type error: %s", e)
            continue
        except ParsingError as e:
            logger.warning("error: %s", e)
            continue

        match args.command:
            case "exit" | "quit":
                GLib.idle_add(app.on_exit)
                return

            case "help":
                if args.help_cmd:
                    parsers[args.help_cmd].print_help()
                else:
                    parser.print_help()

            case "hide":
                if args.regex:
                    hide_uids = [
                        uid for uid in app.get_uids() if any(
                            re.search(pattern, uid) for pattern in args.uids)
                    ]
                else:
                    hide_uids = [ uid for uid in args.uids if uid in app.get_uids() ]

                GLib.idle_add(app.on_hide, hide_uids)

            case "list-uids":
                uids = app.get_uids()
                if uids:
                    print("\n".join(uids))

            case "reload-css":
                GLib.idle_add(app.on_reload_css)

            case "show":
                text = read_text(args.end_mark)

                GLib.idle_add(app.on_show, args.uid, text, args.markup,
                              args.sec, args.classes, args.output,
                              args.position)

            case _:
                assert False, f"unknown command: {cmd_line}"


def read_text(end_mark: str) -> str:
    text = ""
    for line in sys.stdin:
        if line[:-1] == end_mark:
            break
        text += line
    return text.removesuffix("\n")


def main() -> None:
    """Entry point."""
    logging.basicConfig(level=logging.WARN)

    prog, _py = os.path.splitext(os.path.basename(__file__))

    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog=prog,
        description=__doc__,
        epilog="If the --css option is not used, look for style.css in the"
        " following directories (in order):\n"
        "~/.wlosd/\n"
        "${XDG_CONFIG_HOME}/wlosd/\n"
        "~/.config/wlosd/\n"
        "/etc/xdg/wlosd/\n",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    # yapf: disable
    parser.add_argument("-c", "--css", default=find_config_file("style.css"),
                        help="set the css file")
    parser.add_argument("-v", "--verbosity", action="count", default=0,
                        help="increase output verbosity")
    parser.add_argument("-V", "--version", action="version",
                        version=f"%(prog)s {__version__}")
    # yapf: enable

    args = parser.parse_args()

    match args.verbosity:
        case 0:
            logger.setLevel(logging.ERROR)
        case 1:
            logger.setLevel(logging.WARN)
        case 2:
            logger.setLevel(logging.INFO)
        case _:
            logger.setLevel(logging.DEBUG)

    app: MainApp = MainApp(args.css)
    app.connect("activate", app.on_activate)

    threading.Thread(target=cmds_listener, args=(app,), daemon=True).start()
    app.run(None)
