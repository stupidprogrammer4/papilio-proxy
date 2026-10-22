"""Native terminal configuration; runtime installation remains in the existing CLI."""

import argparse
import curses
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .configuration import ENVIRONMENTS, Installation, InstallSettings, write_private


class WizardCancelled(Exception):
    """The operator cancelled before installation changes."""


@dataclass
class InputField:
    label: str
    value: str
    help: str
    choices: tuple[str, ...] = ()

    def cycle(self, direction: int = 1) -> None:
        self.value = self.choices[(self.choices.index(self.value) + direction) % len(self.choices)]


@dataclass
class ConfigurationForm:
    environment: InputField
    host: InputField
    scheme: InputField
    instance: InputField
    bind: InputField
    http_port: InputField
    https_port: InputField
    image_mode: InputField

    @classmethod
    def from_settings(cls, settings: InstallSettings) -> "ConfigurationForm":
        return cls(
            environment=InputField(
                "Environment",
                settings.environment,
                "Each environment has separate data, queues and credentials.",
                ENVIRONMENTS,
            ),
            host=InputField(
                "Domain / IPv4",
                settings.host,
                "The address used to open this panel; no URL prefix or path.",
            ),
            scheme=InputField(
                "Web access",
                settings.transport_scheme,
                "HTTP works directly. HTTPS enables Caddy certificate management.",
                ("http", "https"),
            ),
            instance=InputField(
                "Instance",
                settings.instance,
                "Lowercase name; separate instances keep their data isolated.",
            ),
            bind=InputField(
                "Listen address",
                settings.bind_address,
                "0.0.0.0 accepts remote clients; 127.0.0.1 is local only.",
                ("0.0.0.0", "127.0.0.1"),
            ),
            http_port=InputField(
                "HTTP port",
                str(settings.http_port),
                "Only unused ports can be selected; existing services are preserved.",
            ),
            https_port=InputField(
                "HTTPS port",
                str(settings.https_port),
                "Used only for HTTPS. Public certificate challenges need reachable ports.",
            ),
            image_mode=InputField(
                "Application images",
                settings.image_mode,
                "Auto uses a release bundle when present. Prebuilt never builds on this server.",
                ("auto", "prebuilt", "build"),
            ),
        )

    @property
    def fields(self) -> tuple[InputField, ...]:
        return (
            self.environment,
            self.host,
            self.scheme,
            self.instance,
            self.bind,
            self.http_port,
            self.https_port,
            self.image_mode,
        )

    def settings(self) -> InstallSettings:
        try:
            http_port = int(self.http_port.value)
            https_port = int(self.https_port.value)
        except ValueError as error:
            raise ValueError("Both port fields must contain whole numbers.") from error
        settings = InstallSettings(
            environment=self.environment.value,
            instance=self.instance.value,
            host=self.host.value,
            scheme=self.scheme.value,
            bind_address=self.bind.value,
            http_port=http_port,
            https_port=https_port,
            image_mode=self.image_mode.value,
        )
        settings.validate()
        return settings


class TerminalWizard:
    def __init__(self, screen: curses.window, form: ConfigurationForm) -> None:
        self.screen = screen
        self.form = form
        self.selection = 0
        self.advanced = False
        self.message = ""
        self.accent = curses.A_BOLD
        if curses.has_colors():
            curses.start_color()
            curses.init_pair(1, curses.COLOR_CYAN, curses.COLOR_BLACK)
            self.accent |= curses.color_pair(1)
        self.screen.keypad(True)
        self.screen.timeout(250)
        curses.set_escdelay(30)

    def text(self, row: int, value: str, style: int = 0) -> None:
        height, width = self.screen.getmaxyx()
        if not 0 < row < height - 1 or width < 8:
            return
        # A resize can invalidate a row between measurement and drawing.
        with suppress(curses.error):
            self.screen.addnstr(row, 3, value, width - 6, style)

    def read_key(self) -> str | int:
        try:
            key = self.screen.get_wch()
        except curses.error:
            key = curses.KEY_RESIZE
        return key

    def frame(self, title: str) -> bool:
        terminal = os.get_terminal_size(0)
        if self.screen.getmaxyx() != (terminal.lines, terminal.columns):
            curses.resizeterm(terminal.lines, terminal.columns)
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        if height < 22 or width < 68:
            self.text(1, "Resize terminal to 68 x 22; Esc cancels.")
            self.screen.refresh()
            return False
        self.screen.box()
        self.text(1, "PAPILIO  /  Single-server installation", self.accent)
        self.text(3, title, curses.A_BOLD)
        return True

    def visible_fields(self) -> tuple[InputField, ...]:
        return self.form.fields if self.advanced else self.form.fields[:3]

    def render(self) -> None:
        if not self.frame("01  Configure     02  Review     03  Install"):
            return
        fields = self.visible_fields()
        for position, field in enumerate(fields):
            style = curses.A_REVERSE if self.selection == position else 0
            self.text(5 + position, f"{field.label:<20}  {field.value or '(required)'}", style)
        actions = (
            "Hide advanced settings" if self.advanced else "Show advanced settings",
            "Review & continue",
            "Cancel",
        )
        for position, label in enumerate(actions, len(fields)):
            style = curses.A_REVERSE if self.selection == position else self.accent
            self.text(6 + position, f"[ {label} ]", style)
        height, _ = self.screen.getmaxyx()
        help_text = (
            fields[self.selection].help
            if self.selection < len(fields)
            else "No service changes until you continue."
        )
        self.text(height - 5, self.message or help_text)
        self.text(height - 3, "Tab / arrows: move   Enter: edit   Space: choose   F2: review")
        self.text(height - 2, "F3: advanced   Ctrl-U: clear while editing   Esc: cancel")
        self.screen.refresh()

    def edit(self, field: InputField) -> None:
        if field.choices:
            field.cycle()
            return
        previous = field.value
        while True:
            self.message = "Editing: Enter saves; Esc restores; Ctrl-U clears."
            self.render()
            key = self.read_key()
            if key in ("\n", "\r", curses.KEY_ENTER):
                break
            if key == "\x1b":
                field.value = previous
                break
            if key == "\x15":
                field.value = ""
            elif key in ("\b", "\x7f", curses.KEY_BACKSPACE):
                field.value = field.value[:-1]
            elif isinstance(key, str) and key.isprintable() and len(field.value) < 253:
                field.value += key
        self.message = ""

    def review(self) -> InstallSettings | None:
        try:
            settings = self.form.settings()
        except ValueError as error:
            self.message = str(error)
            return None
        while True:
            ready = self.frame("02  Review your installation")
            if ready:
                for position, field in enumerate(self.form.fields):
                    self.text(5 + position, f"{field.label:<20}  {field.value}")
                self.text(14, f"Panel address: {settings.origin}", self.accent)
                self.text(16, "PostgreSQL + Redis + RabbitMQ + API + workers + Beat + web")
                self.text(18, "Enter: continue to install   Esc: return to settings", curses.A_BOLD)
                self.screen.refresh()
            key = self.read_key()
            if ready and key in ("\n", "\r", curses.KEY_ENTER):
                return settings
            if key in ("\x1b", "q"):
                return None

    def run(self) -> InstallSettings:
        while True:
            self.render()
            key = self.read_key()
            if key in ("\x1b", "q"):
                raise WizardCancelled()
            fields = self.visible_fields()
            if key in ("\x12", curses.KEY_F2):
                result = self.review()
                if result is not None:
                    return result
            elif key in ("\x01", curses.KEY_F3):
                self.advanced = not self.advanced
                self.selection = 0
            elif key in ("\t", curses.KEY_DOWN):
                self.selection = (self.selection + 1) % (len(fields) + 3)
            elif key in (curses.KEY_UP, curses.KEY_BTAB):
                self.selection = (self.selection - 1) % (len(fields) + 3)
            elif key in ("\n", "\r", " ", curses.KEY_ENTER):
                result = self.activate(fields)
                if result is not None:
                    return result

    def activate(self, fields: tuple[InputField, ...]) -> InstallSettings | None:
        if self.selection < len(fields):
            self.edit(fields[self.selection])
        elif self.selection == len(fields):
            self.advanced = not self.advanced
            self.selection = 0
        elif self.selection == len(fields) + 1:
            return self.review()
        else:
            raise WizardCancelled()
        return None


@contextmanager
def controlling_terminal() -> Iterator[None]:
    """Support a curl|bash bootstrap whose inherited stdin is a pipe."""
    sys.stdout.flush()
    saved_input, saved_output = os.dup(0), os.dup(1)
    try:
        with open("/dev/tty", "r+b", buffering=0) as terminal:
            os.dup2(terminal.fileno(), 0)
            os.dup2(terminal.fileno(), 1)
            yield
            sys.stdout.flush()
    finally:
        os.dup2(saved_input, 0)
        os.dup2(saved_output, 1)
        os.close(saved_input)
        os.close(saved_output)


def plain_settings(form: ConfigurationForm) -> InstallSettings:
    print("\nPAPILIO / Single-server installation\n" + "=" * 48)
    print("Blank keeps the current value; Ctrl-C cancels.\n")
    while True:
        for field in form.fields:
            value = input(f"{field.label} [{field.value}]: ").strip()
            if value:
                field.value = value
        try:
            settings = form.settings()
        except ValueError as error:
            print(f"\nPlease correct: {error}\n")
            continue
        print(f"\nReview: {settings.environment} / {settings.instance} / {settings.origin}")
        action = input("Enter continues; e edits; q cancels: ").strip().lower()
        if action == "q":
            raise WizardCancelled()
        if not action:
            return settings


def run_window(screen: curses.window, form: ConfigurationForm) -> InstallSettings:
    return TerminalWizard(screen, form).run()


def interactive_settings(initial: InstallSettings) -> InstallSettings:
    form = ConfigurationForm.from_settings(initial)
    with controlling_terminal():
        if os.environ.get("TERM", "dumb") in {"", "dumb"}:
            settings = plain_settings(form)
        else:
            try:
                settings = curses.wrapper(run_window, form)
            except curses.error:
                settings = plain_settings(form)
    return settings


def initial_settings(args: argparse.Namespace) -> InstallSettings:
    if args.existing_root is not None:
        initial = Installation.load(args.existing_root).settings
    else:
        initial = InstallSettings.from_options(
            environment=args.environment, instance=args.instance, host=""
        )
    return replace(
        initial,
        host=args.host if args.host is not None else initial.host,
        scheme=args.scheme if args.scheme is not None else initial.scheme,
        bind_address=args.bind if args.bind is not None else initial.bind_address,
        http_port=args.port if args.port is not None else initial.http_port,
        https_port=args.https_port if args.https_port is not None else initial.https_port,
        image_mode=args.image_mode if args.image_mode is not None else initial.image_mode,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Papilio terminal installation settings")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--existing-root", type=Path)
    parser.add_argument("--environment", choices=ENVIRONMENTS, default="production")
    parser.add_argument("--instance", default="default")
    parser.add_argument("--host")
    parser.add_argument("--scheme", choices=("http", "https"))
    parser.add_argument("--bind")
    parser.add_argument("--port", type=int)
    parser.add_argument("--https-port", type=int)
    parser.add_argument("--image-mode", choices=("auto", "prebuilt", "build"))
    args = parser.parse_args()
    initial = initial_settings(args)
    try:
        settings = interactive_settings(initial)
        write_private(args.output, json.dumps(asdict(settings), indent=2) + "\n")
    except (WizardCancelled, KeyboardInterrupt, EOFError):
        print("Installation cancelled; no services changed.", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
