"""OSD for wayland."""

import argparse
from ctypes import CDLL
import logging
import os
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

ARGS: t.Optional[argparse.Namespace] = None


class MainApp(Gtk.Application):

    def __init__(self) -> None:
        assert ARGS
        super().__init__(
            application_id="com.wlosd",
            # Allow multiple instances.
            flags=Gio.ApplicationFlags.NON_UNIQUE)

        self._windows: dict[str, Gtk.Window] = {}
        self._show_sec_timers: dict[str, int] = {}

        self._display: Gdk.Display = Gdk.DisplayManager.get(
        ).get_default_display()

        if ARGS.css is not None:
            self._css_provider = Gtk.CssProvider()
            self._css_provider.load_from_path(ARGS.css)
            Gtk.StyleContext.add_provider_for_display(
                self._display, self._css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_USER)

    def get_uids(self) -> t.Iterable[str]:
        return self._windows.keys()

    def on_activate(self, _src) -> None:
        self.hold()

    def cancel_hide_sec_timer(self, uid: str) -> None:
        if uid not in self._show_sec_timers:
            return
        GLib.source_remove(self._show_sec_timers[uid])
        del self._show_sec_timers[uid]

    def on_exit(self) -> bool:
        self.quit()
        return GLib.SOURCE_REMOVE

    def set_input_region(self, src):
        surface = src.get_native().get_surface()
        if surface:
            # pylint: disable-next=no-member
            surface.set_input_region(cairo.Region([]))

    def on_show(self, uid: str, text: str, hide_sec: float | None,
                classes: list[str], output: str | None, position: list) -> bool:
        self.cancel_hide_sec_timer(uid)

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

        label.set_markup(text)
        label.set_css_classes(classes)

        window.present()

        if hide_sec is not None:
            self._show_sec_timers[uid] = GLib.timeout_add(
                int(hide_sec * 1000), self.on_hide, uid)

        return GLib.SOURCE_REMOVE

    def on_hide(self, uid: str) -> bool:
        self.cancel_hide_sec_timer(uid)
        if uid not in self._windows:
            logger.warning("no such id: %s", uid)
            return GLib.SOURCE_REMOVE

        self._windows[uid].destroy()
        del self._windows[uid]
        return GLib.SOURCE_REMOVE

    def on_reload_css(self) -> bool:
        if ARGS.css is None:
            logger.warning("no css file to reload")
            return GLib.SOURCE_REMOVE
        self._css_provider.load_from_path(ARGS.css)
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
    commands = [
        "help", "exit", "quit", "show", "hide", "list-uids", "reload-css"
    ]

    parser = argparse.ArgumentParser(
        exit_on_error=False,
        add_help=False,
        prog="",
        epilog="'help CMD' for more information about CMD.")
    parser.error = ParsingError.throw  # type: ignore[method-assign]

    subparser = parser.add_subparsers(dest="command",
                                      required=True,
                                      title="Commands",
                                      metavar="CMD",
                                      help=f"one of {{{','.join(commands)}}}")

    parsers = {}
    for cmd in commands:
        parsers[cmd] = subparser.add_parser(cmd, prog=cmd, add_help=False)
        parsers[cmd].error = ParsingError.throw  # type: ignore[method-assign]

    parsers["help"].description = "Display help information about CMD."
    parsers["help"].add_argument("help_cmd",
                                 default=None,
                                 choices=([""] + commands),
                                 nargs="?",
                                 metavar=",".join(commands))

    parsers["show"].add_argument("-s", "--sec", type=float, default=None)
    parsers["show"].add_argument("-e", "--end-mark", default="")
    parsers["show"].add_argument("-c", "--class", action="append", dest="classes",
                                 default=[]) # yapf: disable
    parsers["show"].add_argument("-o", "--output", default=None)
    parsers["show"].add_argument("-t", "--top", dest="position", default=[],
                                 action="append_const",
                                 const=Gtk4LayerShell.Edge.TOP)  # yapf: disable
    parsers["show"].add_argument("-b", "--bottom", dest="position", default=[],
                                 action="append_const",
                                 const=Gtk4LayerShell.Edge.BOTTOM)  # yapf: disable
    parsers["show"].add_argument("-l", "--left", dest="position", default=[],
                                 action="append_const",
                                 const=Gtk4LayerShell.Edge.LEFT)  # yapf: disable
    parsers["show"].add_argument("-r", "--right", dest="position", default=[],
                                 action="append_const",
                                 const=Gtk4LayerShell.Edge.RIGHT)  # yapf: disable
    parsers["show"].add_argument("uid")

    parsers["hide"].add_argument("uid")

    # Process commands from stdin
    while True:
        cmd_line: str = sys.stdin.readline()

        if cmd_line == "":
            logger.info("stdin was closed")
            GLib.idle_add(app.on_exit)
            return

        # split to words
        cmd: list[str] = cmd_line.removesuffix("\n").split(" ")

        try:
            args = parser.parse_args(cmd)
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
            case "help":
                if args.help_cmd:
                    parsers[args.help_cmd].print_help()
                else:
                    parser.print_help()

            case "exit" | "quit":
                GLib.idle_add(app.on_exit)
                return

            case "show":
                text = read_text(args.end_mark)

                GLib.idle_add(app.on_show, args.uid, text, args.sec,
                              args.classes, args.output, args.position)

            case "hide":
                GLib.idle_add(app.on_hide, args.uid)

            case "reload-css":
                GLib.idle_add(app.on_reload_css)

            case "list-uids":
                print("\n".join(app.get_uids()))

            case _:
                logger.warning("unknown command: %s", cmd_line)


def read_text(end_mark: str) -> str:
    text: str = ""
    for line in sys.stdin:
        if line[:-1] == end_mark:
            break
        text += line
    return text.removesuffix("\n")


def main() -> None:
    """Entry point."""
    logging.basicConfig(level=logging.WARN)

    prog, _ = os.path.splitext(os.path.basename(__file__))

    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        prog=prog, description=__doc__)
    # yapf: disable
    parser.add_argument("-c", "--css", default=None,
                        help="set the css file")
    parser.add_argument("-v", "--verbosity", action="count", default=0,
                        help="increase output verbosity")
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    # yapf: enable

    global ARGS  # pylint: disable=global-statement
    ARGS = parser.parse_args()

    match ARGS.verbosity:
        case 0:
            logger.setLevel(logging.ERROR)
        case 1:
            logger.setLevel(logging.WARN)
        case 2:
            logger.setLevel(logging.INFO)
        case _:
            logger.setLevel(logging.DEBUG)

    app: MainApp = MainApp()
    app.connect("activate", app.on_activate)

    threading.Thread(target=cmds_listener, args=(app,), daemon=True).start()
    app.run(None)
