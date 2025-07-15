# wlosd

An on-screen display for Wayland compositors.

You might also be interested in [wledges](https://github.com/fshaked/wledges)
which provides active edges for Wayland compositors.

## Supported Desktops

Tested on [Sway](https://swaywm.org/), but should work on all Wayland
compositors that support the Layer Shell protocol. More precisely,
it should work on all
[desktops supported](https://github.com/wmww/gtk4-layer-shell?tab=readme-ov-file#supported-desktops)
by gtk4-layer-shell.

## Installation

### Dependencies:

Debian/Ubuntu:

```
sudo apt install libgirepository-1.0-dev gcc libcairo2-dev pkg-config python3-dev gir1.2-gtk-4.0 libgtk4-layer-shell-dev
pip install pygobject
```

Fedora:

```
sudo dnf install gcc gobject-introspection-devel cairo-gobject-devel pkg-config python3-devel gtk4 gtk4-layer-shell-devel
pip install pygobject
```

Arch Linux:

```
sudo pacman -S python cairo pkgconf gobject-introspection gtk4 gcc gtk4-layer-shell
pip install pygobject
```

For other distributions, you will need:
- Python 3: [instructions](https://wiki.python.org/moin/BeginnersGuide/Download)
- pygobject: [instructions](https://pygobject.gnome.org/getting_started.html)
- gtk4-layer-shell: [instructions](https://github.com/wmww/gtk4-layer-shell)

### Install wlosd:
From PyPi:
```
pip install wlosd
```

Or clone this repository.

## Usage

wlosd reads commands from standard input. For example, run in a terminal:

```
wlosd
show --end-mark END test
Some text.
More text.
END
```
(don't kill the process yet)

This should display the two lines before `END` in the centre of the currently
focused display, on top of all other windows. The text is transparent to all
input events. If show is called with the `--markup` option, the text is
interpreted as [Pango markup](https://docs.gtk.org/Pango/pango_markup.html)
('<', '>' and '&' must be escaped as '\&lt;', '\&gt;', and '\&amp;').
The `--css` command line argument (e.g. `wlosd --css style.css`) can be used to
pass a GTK4 style sheet (see
[style.css](https://github.com/fshaked/wlosd/blob/main/style.css) for example,
and [overview](https://docs.gtk.org/gtk4/css-overview.html) and
[properties](https://docs.gtk.org/gtk4/css-properties.html) for documentation).

To hide the text:

```
hide test
```

To see all available commands:

```
help
```

To quit:

```
quit
```

A more useful way to run wlosd would be to put something along the following
lines somewhere in your startup scripts:

```
rm -f "${XDG_RUNTIME_DIR}/wlosdpipe"
mkfifo "${XDG_RUNTIME_DIR}/wlosdpipe"
tail -fn+1 "${XDG_RUNTIME_DIR}/wlosdpipe" | wlosd &
```

And send commands to wlosd like this:

```
printf -- 'show --end-mark END test\nSome text.\nEND\n' > "${XDG_RUNTIME_DIR}/wlosdpipe"
```

## License

MIT, see [LICENSE](https://github.com/fshaked/wlosd/blob/main/LICENSE)
