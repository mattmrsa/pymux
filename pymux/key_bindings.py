"""
Key bindings.
"""
from __future__ import unicode_literals
from prompt_toolkit.enums import IncrementalSearchDirection
from prompt_toolkit.filters import HasFocus, Condition, HasSelection
from prompt_toolkit.key_binding.defaults import load_key_bindings
from prompt_toolkit.key_binding.vi_state import InputMode
from prompt_toolkit.keys import Keys
from prompt_toolkit.selection import SelectionType
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings, ConditionalKeyBindings

from .enums import COMMAND, PROMPT
from .filters import WaitsForConfirmation, HasPrefix, InScrollBuffer, InScrollBufferNotSearching, InScrollBufferSearching
from .key_mappings import pymux_key_to_prompt_toolkit_key_sequence
from .commands.commands import call_command_handler

import six

__all__ = (
    'PymuxKeyBindings',
)


class PymuxKeyBindings(object):
    """
    Pymux key binding manager.
    """
    def __init__(self, pymux):
        self.pymux = pymux

        def get_search_state():
            " Return the currently active SearchState. (The one for the focussed pane.) "
            return pymux.arrangement.get_active_pane().search_state

        self.custom_key_bindings = KeyBindings()

        # Start from this KeyBindingManager from prompt_toolkit, to have basic
        # editing functionality for the command line. These key binding are
        # however only active when the following `enable_all` condition is met.
        self.registry = merge_key_bindings([
#            ConditionalKeyBindings(
#                key_bindings=load_key_bindings(
#                    enable_auto_suggest_bindings=True,
#                    enable_search=False,  # We have our own search bindings, that support multiple panes.
#                    enable_extra_page_navigation=True,
#                    get_search_state=get_search_state),
#                filter=(HasFocus(COMMAND) | HasFocus(PROMPT) |
#                        InScrollBuffer(pymux)) & ~HasPrefix(pymux),
#            ),
            self._load_builtins(),
            _load_search_bindings(pymux),
            self.custom_key_bindings,
        ])

        self._prefix = (Keys.ControlB, )
        self._prefix_binding = None

        # Load initial bindings.
        self._load_prefix_binding()

        # Custom user configured key bindings.
        # { (needs_prefix, key) -> (command, handler) }
        self.custom_bindings = {}

    def _load_prefix_binding(self):
        """
        Load the prefix key binding.
        """
        pymux = self.pymux
        registry = self.custom_key_bindings

        # Remove previous binding.
        if self._prefix_binding:
            self.registry.remove_binding(self._prefix_binding)

        # Create new Python binding.
        @registry.add_binding(*self._prefix, filter=
            ~(HasPrefix(pymux) | HasFocus(COMMAND) | HasFocus(PROMPT) | WaitsForConfirmation(pymux)))
        def enter_prefix_handler(event):
            " Enter prefix mode. "
            pymux.get_client_state().has_prefix = True

        self._prefix_binding = enter_prefix_handler

    @property
    def prefix(self):
        " Get the prefix key. "
        return self._prefix

    @prefix.setter
    def prefix(self, keys):
        """
        Set a new prefix key.
        """
        assert isinstance(keys, tuple)

        self._prefix = keys
        self._load_prefix_binding()

    def _load_builtins(self):
        """
        Fill the Registry with the hard coded key bindings.
        """
        pymux = self.pymux
        kb = KeyBindings()

        # Create filters.
        has_prefix = HasPrefix(pymux)
        waits_for_confirmation = WaitsForConfirmation(pymux)
        prompt_or_command_focus = HasFocus(COMMAND) | HasFocus(PROMPT)
        display_pane_numbers = Condition(lambda: pymux.display_pane_numbers)
        in_scroll_buffer_not_searching = InScrollBufferNotSearching(pymux)
        pane_input_allowed = ~(prompt_or_command_focus | has_prefix |
                               waits_for_confirmation | display_pane_numbers |
                               InScrollBuffer(pymux))

#        @kb.add(Keys.Any, filter=pane_input_allowed, invalidate_ui=False)
#        def _(event):
#            """
#            When a pane has the focus, key bindings are redirected to the
#            process running inside the pane.
#            """
#            # NOTE: we don't invalidate the UI, because for pymux itself,
#            #       nothing in the output changes yet. It's the application in
#            #       the pane that will probably echo back the typed characters.
#            #       When we receive them, they are draw to the UI and it's
#            #       invalidated.
#            w = pymux.arrangement.get_active_window()
#            pane = w.active_pane
#
#            if pane.clock_mode:
#                # Leave clock mode on key press.
#                pane.clock_mode = False
#                pymux.invalidate()
#            else:
#                # Write input to pane. If 'synchronize_panes' is on, write
#                # input to all panes in the current window.
#                panes = w.panes if w.synchronize_panes else [pane]
#                for p in panes:
#                    p.process.write_key(event.key_sequence[0].key)
#
#        @kb.add(Keys.BracketedPaste, filter=pane_input_allowed, invalidate_ui=False)
#        def _(event):
#            """
#            Pasting to the active pane. (Using bracketed paste.)
#            """
#            w = pymux.arrangement.get_active_window()
#            pane = w.active_pane
#
#            if not pane.clock_mode:
#                # Paste input to pane. If 'synchronize_panes' is on, paste
#                # input to all panes in the current window.
#                panes = w.panes if w.synchronize_panes else [pane]
#                for p in panes:
#                    p.process.write_input(event.data, paste=True)

        @kb.add(Keys.Any, filter=has_prefix)
        def _(event):
            " Ignore unknown Ctrl-B prefixed key sequences. "
            pymux.get_client_state().has_prefix = False

        @kb.add('c-c', filter=prompt_or_command_focus & ~has_prefix)
        @kb.add('c-g', filter=prompt_or_command_focus & ~has_prefix)
#        @kb.add('backspace', filter=HasFocus(COMMAND) & ~has_prefix &
#                              Condition(lambda: cli.buffers[COMMAND].text == ''))
        def _(event):
            " Leave command mode. "
            pymux.leave_command_mode(append_to_history=False)

        @kb.add('y', filter=waits_for_confirmation)
        @kb.add('Y', filter=waits_for_confirmation)
        def _(event):
            """
            Confirm command.
            """
            client_state = pymux.get_client_state()

            command = client_state.confirm_command
            client_state.confirm_command = None
            client_state.confirm_text = None

            pymux.handle_command(command)

        @kb.add('n', filter=waits_for_confirmation)
        @kb.add('N', filter=waits_for_confirmation)
        @kb.add('c-c' , filter=waits_for_confirmation)
        def _(event):
            """
            Cancel command.
            """
            client_state = pymux.get_client_state()
            client_state.confirm_command = None
            client_state.confirm_text = None

        @kb.add('c-c', filter=in_scroll_buffer_not_searching)
        @kb.add('enter', filter=in_scroll_buffer_not_searching)
        @kb.add('q', filter=in_scroll_buffer_not_searching)
        def _(event):
            " Exit scroll buffer. "
            pane = pymux.arrangement.get_active_pane()
            pane.exit_scroll_buffer()

        @kb.add(' ', filter=in_scroll_buffer_not_searching)
        def _(event):
            " Enter selection mode when pressing space in copy mode. "
            event.current_buffer.start_selection(selection_type=SelectionType.CHARACTERS)

        @kb.add('enter', filter=in_scroll_buffer_not_searching & HasSelection())
        def _(event):
            " Copy selection when pressing Enter. "
            clipboard_data = event.current_buffer.copy_selection()
            event.app.clipboard.set_data(clipboard_data)

        @kb.add('v', filter=in_scroll_buffer_not_searching & HasSelection())
        def _(event):
            " Toggle between selection types. "
            types = [SelectionType.LINES, SelectionType.BLOCK, SelectionType.CHARACTERS]
            selection_state = event.current_buffer.selection_state

            try:
                index = types.index(selection_state.type)
            except ValueError:  # Not in list.
                index = 0

            selection_state.type = types[(index + 1) % len(types)]

        @kb.add(Keys.Any, filter=display_pane_numbers)
        def _(event):
            " When the pane numbers are shown. Any key press should hide them. "
            pymux.display_pane_numbers = False

        return kb

    def add_custom_binding(self, key_name, command, arguments, needs_prefix=False):
        """
        Add custom binding (for the "bind-key" command.)
        Raises ValueError if the give `key_name` is an invalid name.

        :param key_name: Pymux key name, for instance "C-a" or "M-x".
        """
        assert isinstance(key_name, six.text_type)
        assert isinstance(command, six.text_type)
        assert isinstance(arguments, list)

        # Unbind previous key.
        self.remove_custom_binding(key_name, needs_prefix=needs_prefix)

        # Translate the pymux key name into a prompt_toolkit key sequence.
        # (Can raise ValueError.)
        keys_sequence = pymux_key_to_prompt_toolkit_key_sequence(key_name)

        # Create handler and add to Registry.
        if needs_prefix:
            filter = HasPrefix(self.pymux)
        else:
            filter = ~HasPrefix(self.pymux)

        filter = filter & ~(WaitsForConfirmation(self.pymux) |
                            HasFocus(COMMAND) | HasFocus(PROMPT))

        def key_handler(event):
            " The actual key handler. "
            call_command_handler(command, self.pymux, arguments)
            self.pymux.get_client_state().has_prefix = False

        self.custom_key_bindings.add(*keys_sequence, filter=filter)(key_handler)

        # Store key in `custom_bindings` in order to be able to call
        # "unbind-key" later on.
        k = (needs_prefix, key_name)
        self.custom_bindings[k] = CustomBinding(key_handler, command, arguments)

    def remove_custom_binding(self, key_name, needs_prefix=False):
        """
        Remove custom key binding for a key.

        :param key_name: Pymux key name, for instance "C-A".
        """
        k = (needs_prefix, key_name)

        if k in self.custom_bindings:
            self.custom_key_bindings.remove(self.custom_bindings[k].handler)
            del self.custom_bindings[k]


class CustomBinding(object):
    """
    Record for storing a single custom key binding.
    """
    def __init__(self, handler, command, arguments):
        assert callable(handler)
        assert isinstance(command, six.text_type)
        assert isinstance(arguments, list)

        self.handler = handler
        self.command = command
        self.arguments = arguments


def _load_search_bindings(pymux):
    """
    Load the key bindings for searching. (Vi and Emacs)

    This is different from the ones of prompt_toolkit, because we have a
    individual search buffers for each pane.
    """
    kb = KeyBindings()
    is_searching = InScrollBufferSearching(pymux)
    in_scroll_buffer_not_searching = InScrollBufferNotSearching(pymux)

    def search_buffer_is_empty():
        """ Returns True when the search buffer is empty. """
        return pymux.arrangement.get_active_pane().search_buffer.text == ''

    @kb.add('c-g', filter=is_searching)
    @kb.add('c-c', filter=is_searching)
    @kb.add('backspace', filter=is_searching & Condition(search_buffer_is_empty))
    def _(event):
        """
        Abort an incremental search and restore the original line.
        """
        pane = pymux.arrangement.get_active_pane()
        pane.search_buffer.reset()
        pane.is_searching = False

    @kb.add('enter', filter=is_searching)
    def _(event):
        """
        When enter pressed in isearch, accept search.
        """
        pane = pymux.arrangement.get_active_pane()

        input_buffer = pane.scroll_buffer
        search_buffer = pane.search_buffer

        # Update search state.
        if search_buffer.text:
            pane.search_state.text = search_buffer.text

        # Apply search.
        input_buffer.apply_search(pane.search_state, include_current_position=True)

        # Add query to history of search line.
        search_buffer.append_to_history()

        # Focus previous document again.
        pane.search_buffer.reset()
        pane.is_searching = False

    def enter_search(app):
        vi_state.input_mode = InputMode.INSERT

        pane = pymux.arrangement.get_active_pane()
        pane.is_searching = True
        return pane.search_state

    @kb.add('c-r', filter=in_scroll_buffer_not_searching)
    @kb.add('?', filter=in_scroll_buffer_not_searching)
    def _(event):
        " Enter reverse search. "
        search_state = enter_search(event.app)
        search_state.direction = IncrementalSearchDirection.BACKWARD

    @kb.add('c-s', filter=in_scroll_buffer_not_searching)
    @kb.add('/', filter=in_scroll_buffer_not_searching)
    def _(event):
        " Enter forward search. "
        search_state = enter_search(event.app)
        search_state.direction = IncrementalSearchDirection.FORWARD

    @kb.add('c-r', filter=is_searching)
    @kb.add('up', filter=is_searching)
    def _(event):
        " Repeat reverse search. (While searching.) "
        pane = pymux.arrangement.get_active_pane()

        # Update search_state.
        search_state = pane.search_state
        direction_changed = search_state.direction != IncrementalSearchDirection.BACKWARD

        search_state.text = pane.search_buffer.text
        search_state.direction = IncrementalSearchDirection.BACKWARD

        # Apply search to current buffer.
        if not direction_changed:
            pane.scroll_buffer.apply_search(
                pane.search_state, include_current_position=False, count=event.arg)

    @kb.add('c-s', filter=is_searching)
    @kb.add('down', filter=is_searching)
    def _(event):
        " Repeat forward search. (While searching.) "
        pane = pymux.arrangement.get_active_pane()

        # Update search_state.
        search_state = pane.search_state
        direction_changed = search_state.direction != IncrementalSearchDirection.FORWARD

        search_state.text = pane.search_buffer.text
        search_state.direction = IncrementalSearchDirection.FORWARD

        # Apply search to current buffer.
        if not direction_changed:
            pane.scroll_buffer.apply_search(
                pane.search_state, include_current_position=False, count=event.arg)

    return kb
