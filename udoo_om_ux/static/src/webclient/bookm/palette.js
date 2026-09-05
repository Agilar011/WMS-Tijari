import { _t } from '@web/core/l10n/translation';
import { useHotkey } from '@web/core/hotkeys/hotkey_hook';
import { KeepLast, Race } from '@web/core/utils/concurrency';
import { useAutofocus, useBus, useService } from '@web/core/utils/hooks';
import { usePopover } from '@web/core/popover/popover_hook';
import { CommandPalette, DefaultCommandItem } from '@web/core/commands/command_palette';
import { Component, onWillStart, useRef, useState, xml } from '@odoo/owl';

import { VIEW_IMAP } from '../action_utils';


export class FakeDialog extends Component {
    static template = xml`<div class='o_bookm_palette'><t t-slot='default'/></div>`;
    static props = { '*': true };
}

export class BookmarkPalette extends CommandPalette {
    static template = 'wub.BookmarkPalette';
    static components = {
        ...CommandPalette.components,
        Dialog: FakeDialog,
    }

    setup() {
        this.view_imap = VIEW_IMAP;

        this.keyId = 1;
        this.race = new Race();
        this.keepLast = new KeepLast();
        this._sessionId = BookmarkPalette.lastSessionId++;
        this.DefaultCommandItem = DefaultCommandItem;
        this.activeElement = useService('ui').activeElement;
        this.inputRef = useAutofocus();

        useHotkey('Enter', () => this.executeSelectedCommand(), { bypassEditableProtection: true });
        useHotkey('Control+Enter', () => this.executeSelectedCommand(true), {
            bypassEditableProtection: true,
        });
        useHotkey('ArrowUp', () => this.selectCommandAndScrollTo('PREV'), {
            bypassEditableProtection: true,
            allowRepeat: true,
        });
        useHotkey('ArrowDown', () => this.selectCommandAndScrollTo('NEXT'), {
            bypassEditableProtection: true,
            allowRepeat: true,
        });

        this.state = useState({});
        this.root = useRef('root');
        this.listboxRef = useRef('listbox');

        this.cpop = usePopover(BookmContextMenu, {
            setActiveElement: false,
            closeOnClickAway: true,
            animation: false,
        });

        onWillStart(() => this.setCommandPaletteConfig(this.props.config));

        useBus(this.env.bus, 'BMK:SEARCH', ({ detail: text }) => {
            this.debounceSearch(text);
        });
    }

    openItemCtx(idx) {
        this.cpop.open(this.root.el.querySelector(`span[data-bmkid='${idx}']`), {
            item: this.state.commands[idx],
        });
    }
}

export class BookmarkCommandItem extends Component {
    static template = 'wub.BookmarkCommandItem';
    static props = {
        slots: { type: Object, optional: true },
        // Props send by the command palette:
        hotkey: { type: String, optional: true },
        hotkeyOptions: { type: String, optional: true },
        name: { type: String, optional: true },
        searchValue: { type: String, optional: true },
        executeCommand: { type: Function, optional: true },
    };
}

class BookmContextMenu extends Component {
    static template = 'wub.BookmContextMenu';
    static props = { '*': true };

    open(flag) {
        this.props.close();
        this.props.item.action(flag);
    }

    copy() {
        this.props.close();
        this.props.item.copy();
    }

    delete() {
        this.props.close();
        this.props.item.delete();
    }
}