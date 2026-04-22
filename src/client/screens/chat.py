# src/client/screens/chat.py
"""
Экран чата с полной поддержкой E2EE, дополнительной фразы, WebSocket,
адаптивного паддинга и системных сообщений для LRP протокола.
"""
import asyncio
import json
import time
from typing import List, Dict, Optional, Any

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Button, Input, Static
from textual import log

# Импортируем ClientCrypto из переименованного файла
from src.client.client_crypto import ClientCrypto


class ChatMessage:
    """Модель сообщения в чате."""

    def __init__(
        self,
        message_id: str,
        from_id: str,
        to_id: str,
        encrypted: str,
        session_key: str,
        timestamp: int,
        has_phrase: bool = False,
        delivered: bool = False,
        read: bool = False,
        decrypted_text: Optional[str] = None,
        padding_size: Optional[int] = None,
        counter: Optional[int] = None,
        is_system: bool = False,
        system_type: Optional[str] = None,
        system_data: Optional[Dict] = None,
    ):
        self.id = message_id
        self.from_id = from_id
        self.to_id = to_id
        self.encrypted = encrypted
        self.session_key = session_key
        self.timestamp = timestamp
        self.has_phrase = has_phrase
        self.delivered = delivered
        self.read = read
        self.decrypted_text = decrypted_text
        self.is_own = False
        self.padding_size = padding_size
        self.counter = counter
        self.is_system = is_system
        self.system_type = system_type
        self.system_data = system_data or {}

    @property
    def display_text(self) -> str:
        """Форматированный текст для отображения."""
        if self.is_system:
            return self._format_system_message()
        if self.decrypted_text:
            return self.decrypted_text
        if self.has_phrase:
            return "🔒 [Encrypted with phrase]"
        return "🔒 [Encrypted message]"

    def _format_system_message(self) -> str:
        """Форматирование системного сообщения."""
        messages = {
            'rotation_request': {
                'icon': '🔄',
                'text': '{} запросил(а) смену ключа шифрования'
            },
            'rotation_ack': {
                'icon': '✅',
                'text': '{} подтвердил(а) смену ключа'
            },
            'rotation_complete': {
                'icon': '🔐',
                'text': 'Ключ шифрования успешно обновлён'
            },
            'rotation_timeout': {
                'icon': '⏰',
                'text': 'Запрос на смену ключа истёк'
            },
        }

        msg = messages.get(self.system_type, {
            'icon': '📢',
            'text': 'Системное сообщение'
        })

        if self.system_type in ('rotation_request', 'rotation_ack'):
            sender = self.from_id.split('@')[1] if '@' in self.from_id else self.from_id
            return f"{msg['icon']} {msg['text'].format(sender)}"
        elif self.system_type == 'rotation_complete' and self.system_data:
            initiator = self.system_data.get('initiator', '')
            initiator_name = initiator.split('@')[1] if '@' in initiator else initiator
            return f"{msg['icon']} {msg['text']} (инициатор: {initiator_name})"

        return f"{msg['icon']} {msg['text']}"

    @property
    def system_detail(self) -> str:
        """Детали системного сообщения."""
        if not self.is_system:
            return ""

        details = {
            'rotation_request': 'Запрос на обновление ключа шифрования. Ожидается подтверждение собеседника.',
            'rotation_ack': 'Подтверждение получено. Ключ будет обновлён.',
            'rotation_complete': 'Ключ шифрования успешно обновлён.',
            'rotation_timeout': 'Собеседник не подтвердил смену ключа в течение 24 часов.',
        }

        detail = details.get(self.system_type, 'Системное сообщение')
        if self.system_data:
            detail += f"\nДанные: {json.dumps(self.system_data, ensure_ascii=False)}"
        return detail


class ChatScreen(Screen):
    """Экран чата с контактом."""

    CSS = """
    ChatScreen {
        layout: vertical;
    }
    .chat-header {
        height: 3;
        background: $surface;
        border-bottom: solid $primary;
        padding: 0 1;
    }
    .messages-container {
        height: 1fr;
        overflow-y: auto;
        padding: 1;
    }
    .message-row {
        margin-bottom: 1;
        width: 100%;
    }
    .message-bubble {
        max-width: 80%;
        padding: 0 1;
        border-radius: 1;
    }
    .message-own {
        background: $primary;
        color: $text;
        text-align: right;
        margin-left: auto;
    }
    .message-other {
        background: $surface;
        color: $text;
        text-align: left;
        margin-right: auto;
        border: solid $primary;
    }
    .message-hidden {
        opacity: 0.6;
    }
    /* Системные сообщения */
    .system-message {
        text-align: center;
        margin: 0.5 auto;
        padding: 0 1;
        width: auto;
        max-width: 90%;
        background: $surface;
        border-radius: 2;
        border-left: solid 2;
    }
    .system-message.rotation_request {
        border-left-color: #ff9800;
        color: #e65100;
    }
    .system-message.rotation_ack {
        border-left-color: #4caf50;
        color: #2e7d32;
    }
    .system-message.rotation_complete {
        border-left-color: #2196f3;
        color: #1565c0;
    }
    .system-message.rotation_timeout {
        border-left-color: #f44336;
        color: #c62828;
    }
    .system-message:hover {
        opacity: 0.8;
    }
    .message-time {
        color: $text-muted;
        text-style: italic;
        font-size: 8;
    }
    .message-status {
        color: $text-muted;
        font-size: 8;
        margin-left: 1;
    }
    .padding-indicator {
        color: $text-muted;
        font-size: 7;
        margin-left: 1;
    }
    .input-area {
        height: 3;
        border-top: solid $surface;
        padding: 0 1;
    }
    .input-area Input {
        width: 1fr;
    }
    .input-area Button {
        width: 10;
    }
    .phrase-area {
        height: 3;
        border-top: solid $surface;
        padding: 0 1;
    }
    .phrase-status {
        width: auto;
        padding: 0 1;
        background: $warning;
    }
    .phrase-status.has-phrase {
        background: $success;
    }
    .typing-indicator {
        height: 1;
        color: $text-muted;
        padding: 0 1;
        font-style: italic;
    }
    .rotation-info {
        height: 2;
        color: $text-muted;
        padding: 0 1;
        font-size: 8;
    }
    """

    def __init__(self, contact: Dict[str, Any]):
        super().__init__()
        self.contact = contact
        self.contact_id = contact.get("public_id")
        self.contact_name = contact.get("name", self.contact_id)
        self.messages: List[ChatMessage] = []
        self.session_key: Optional[bytes] = None
        self.session_key_hex: Optional[str] = None
        self.current_phrase: Optional[str] = None
        self.phrase_known: bool = False
        self._typing_timeout: Optional[asyncio.Task] = None
        self._loading_messages = False
        self._message_offset = 0
        self._has_more = True

        # Состояние для паддинга
        self._message_counter: int = 0
        self._last_padding_size: int = 0
        self._last_received_padding: int = 0
        self._dialog_id: Optional[str] = None

        # Состояние ротации
        self._rotation_info: Dict = {}
        self._rotation_update_task: Optional[asyncio.Task] = None

    def compose(self) -> ComposeResult:
        """Создание интерфейса."""
        yield Horizontal(
            Static(f"💬 Chat with {self.contact_name}", classes="chat-header"),
            id="chat-header",
        )
        yield Static("", id="rotation-info", classes="rotation-info")
        yield ScrollableContainer(id="messages-container")
        yield Static("", id="typing-indicator")
        yield Horizontal(
            Input(placeholder="Type a message...", id="message-input"),
            Button("Send", id="send-btn", variant="primary"),
            classes="input-area",
        )
        yield Horizontal(
            Static("🔓 No phrase", id="phrase-status", classes="phrase-status"),
            Button("Set Phrase", id="set-phrase-btn", variant="default"),
            Button("Clear Phrase", id="clear-phrase-btn", variant="error", disabled=True),
            classes="phrase-area",
        )

    async def on_mount(self) -> None:
        """При монтировании экрана."""
        # Формируем ID диалога
        self._dialog_id = f"{self.app.public_id}:{self.contact_id}" if self.app.public_id < self.contact_id else f"{self.contact_id}:{self.app.public_id}"

        # Загружаем session_key
        await self._load_session_key()

        # Загружаем статус фразы
        await self._load_phrase_status()

        # Загружаем историю сообщений
        await self._load_messages()

        # Подключаем WebSocket
        await self.app.connect_chat_ws(self.contact_id)

        # Запускаем периодическое обновление статуса ротации
        self._rotation_update_task = asyncio.create_task(self._periodic_rotation_update())

        # Обновляем UI
        self._update_phrase_ui()
        await self._update_rotation_info()

    async def on_unmount(self) -> None:
        """При закрытии экрана."""
        if self._rotation_update_task:
            self._rotation_update_task.cancel()
        await self.app.disconnect_chat_ws()

    async def _periodic_rotation_update(self) -> None:
        """Периодическое обновление статуса ротации."""
        while True:
            try:
                await asyncio.sleep(30)
                await self._update_rotation_info()
            except asyncio.CancelledError:
                break
            except Exception as e:
                log(f"Rotation update error: {e}")

    async def _update_rotation_info(self) -> None:
        """Обновление информации о ротации ключа."""
        try:
            response = await self.app.api_client._request(
                "get",
                f"/api/messages/rotation-status/{self.contact_id}"
            )
            if response.get("success"):
                self._rotation_info = response
                self._update_rotation_ui()
        except Exception as e:
            log(f"Failed to update rotation info: {e}")

    def _update_rotation_ui(self) -> None:
        """Обновление UI информации о ротации."""
        info_widget = self.query_one("#rotation-info", Static)
        data = self._rotation_info

        if not data.get("success"):
            info_widget.update("")
            return

        mode = data.get("mode", "none")
        can_rotate_me = data.get("can_rotate_by_me", False)
        can_rotate_peer = data.get("can_rotate_by_peer", False)
        my_cooldown = data.get("my_cooldown_remaining", 0)
        peer_cooldown = data.get("peer_cooldown_remaining", 0)

        if mode == "transition":
            info_widget.update("⏳ Ожидание подтверждения смены ключа...")
            btn = self.query_one("#rotateKeyBtn", Button) if self.query("#rotateKeyBtn") else None
            if btn:
                btn.disabled = True
        else:
            my_status = "✅ Можно" if can_rotate_me else f"⏳ Через {my_cooldown // 3600}ч" if my_cooldown > 0 else "❓"
            peer_status = "✅ Можно" if can_rotate_peer else f"⏳ Через {peer_cooldown // 3600}ч" if peer_cooldown > 0 else "❓"
            info_widget.update(f"👤 Вы: {my_status} | 👥 Собеседник: {peer_status}")

    async def _load_session_key(self) -> bool:
        """Загрузка session_key для диалога."""
        try:
            session_key_hex = await self.app.api_client.get_session_key(self.contact_id)
            if session_key_hex:
                self.session_key_hex = session_key_hex
                self.session_key = bytes.fromhex(session_key_hex)
                log(f"Session key loaded for {self.contact_id}")
                return True
            else:
                log(f"No session key found for {self.contact_id}")
                self.app.show_warning(
                    f"No session key found for {self.contact_name}.\n"
                    "Please wait for them to accept your invite."
                )
                return False
        except Exception as e:
            log(f"Failed to load session key: {e}")
            return False

    async def _load_phrase_status(self) -> None:
        """Загрузка статуса дополнительной фразы."""
        try:
            response = await self.app.api_client._request(
                "get", f"/api/web/chat/{self.contact_id}/phrase"
            )
            if response.get("success"):
                self.phrase_known = response.get("data", {}).get("phrase_known", False)
                cached = self.app.get_phrase(self.contact_id)
                if cached:
                    self.current_phrase = cached
        except Exception as e:
            log(f"Failed to load phrase status: {e}")

    async def _set_phrase(self, phrase: str) -> bool:
        """Установка дополнительной фразы."""
        try:
            response = await self.app.api_client._request(
                "post",
                f"/api/web/chat/{self.contact_id}/phrase",
                json={"phrase": phrase},
            )
            if response.get("success"):
                self.current_phrase = phrase
                self.phrase_known = True
                self.app.save_phrase(self.contact_id, phrase)
                self._update_phrase_ui()
                await self._reload_messages()
                return True
        except Exception as e:
            log(f"Failed to set phrase: {e}")
        return False

    async def _clear_phrase(self) -> bool:
        """Удаление дополнительной фразы."""
        try:
            response = await self.app.api_client._request(
                "delete", f"/api/web/chat/{self.contact_id}/phrase"
            )
            if response.get("success"):
                self.current_phrase = None
                self.phrase_known = False
                self.app.forget_phrase(self.contact_id)
                self._update_phrase_ui()
                await self._reload_messages()
                return True
        except Exception as e:
            log(f"Failed to clear phrase: {e}")
        return False

    def _update_phrase_ui(self) -> None:
        """Обновление UI статуса фразы."""
        status_widget = self.query_one("#phrase-status", Static)
        clear_btn = self.query_one("#clear-phrase-btn", Button)

        if self.current_phrase:
            status_widget.update("🔐 Phrase active")
            status_widget.add_class("has-phrase")
            clear_btn.disabled = False
        elif self.phrase_known:
            status_widget.update("🔐 Phrase set (not entered)")
            status_widget.add_class("has-phrase")
            clear_btn.disabled = False
        else:
            status_widget.update("🔓 No phrase")
            status_widget.remove_class("has-phrase")
            clear_btn.disabled = True

    async def _load_messages(self, reset: bool = True) -> None:
        """Загрузка истории сообщений."""
        if self._loading_messages:
            return

        self._loading_messages = True
        if reset:
            self._message_offset = 0
            self._has_more = True
            self.messages.clear()
            self._message_counter = 0
            self._last_padding_size = 0

        try:
            messages = await self.app.api_client.get_messages(
                self.contact_id,
                limit=50,
                offset=self._message_offset
            )

            if not messages:
                self._has_more = False
                return

            # Расшифровываем сообщения
            for msg_data in messages:
                # Извлекаем счётчик из message_id
                counter = ClientCrypto.extract_counter_from_message_id(msg_data["id"])

                # Системное сообщение
                if msg_data.get("is_system") == 1:
                    system_data = None
                    if msg_data.get("system_data"):
                        try:
                            system_data = json.loads(msg_data["system_data"])
                        except:
                            system_data = {"raw": msg_data["system_data"]}

                    msg = ChatMessage(
                        message_id=msg_data["id"],
                        from_id=msg_data["from_id"],
                        to_id=msg_data["to_id"],
                        encrypted=msg_data["encrypted"],
                        session_key=msg_data["session_key"],
                        timestamp=msg_data["timestamp"],
                        has_phrase=msg_data["has_phrase"],
                        delivered=msg_data["delivered"],
                        read=msg_data["read"],
                        is_system=True,
                        system_type=msg_data.get("system_type"),
                        system_data=system_data,
                    )
                    msg.is_own = (msg.from_id == self.app.public_id)
                    self.messages.append(msg)
                    continue

                # Обычное сообщение
                msg = ChatMessage(
                    message_id=msg_data["id"],
                    from_id=msg_data["from_id"],
                    to_id=msg_data["to_id"],
                    encrypted=msg_data["encrypted"],
                    session_key=msg_data["session_key"],
                    timestamp=msg_data["timestamp"],
                    has_phrase=msg_data["has_phrase"],
                    delivered=msg_data["delivered"],
                    read=msg_data["read"],
                    padding_size=msg_data.get("padding_size"),
                    counter=counter,
                )
                msg.is_own = (msg.from_id == self.app.public_id)

                # Расшифровываем если есть ключ
                if self.session_key:
                    decrypted = await self._decrypt_message(msg)
                    if decrypted:
                        msg.decrypted_text = decrypted

                self.messages.append(msg)

                # Обновляем состояние паддинга (для исходящих сообщений)
                if msg.is_own and msg.padding_size:
                    self._last_padding_size = msg.padding_size
                if msg.counter is not None:
                    self._message_counter = max(self._message_counter, msg.counter + 1)

            self._message_offset += len(messages)
            self._has_more = len(messages) == 50

            # Обновляем UI
            self._refresh_messages_ui()

        except Exception as e:
            log(f"Failed to load messages: {e}")
        finally:
            self._loading_messages = False

    async def _reload_messages(self) -> None:
        """Перезагрузка всех сообщений (после смены фразы)."""
        self._loading_messages = True
        self.messages.clear()
        self._message_offset = 0
        self._has_more = True
        self._message_counter = 0
        self._last_padding_size = 0
        self._loading_messages = False
        await self._load_messages(reset=True)

    async def _decrypt_message(self, msg: ChatMessage) -> Optional[str]:
        """Расшифровка одного сообщения с учётом паддинга."""
        if not self.session_key:
            return None

        try:
            encrypted_bytes = bytes.fromhex(msg.encrypted)
            session_key_bytes = bytes.fromhex(msg.session_key)

            phrase = self.current_phrase if msg.has_phrase else None

            if msg.padding_size is not None and len(encrypted_bytes) > msg.padding_size:
                original_size = len(encrypted_bytes) - msg.padding_size
                return ClientCrypto.decrypt_message_with_padding(
                    ciphertext=encrypted_bytes,
                    session_key=session_key_bytes,
                    from_id=msg.from_id,
                    to_id=msg.to_id,
                    original_size=original_size,
                    phrase=phrase,
                )
            else:
                return ClientCrypto.decrypt_message(
                    ciphertext=encrypted_bytes,
                    session_key=session_key_bytes,
                    from_id=msg.from_id,
                    to_id=msg.to_id,
                    phrase=phrase,
                )
        except Exception as e:
            log(f"Decryption error: {e}")
            return None

    async def _encrypt_and_send(self, plaintext: str) -> bool:
        """Шифрование и отправка сообщения с адаптивным паддингом."""
        if not self.session_key:
            self.app.show_warning("Session key not loaded")
            return False

        has_phrase = self.current_phrase is not None
        phrase = self.current_phrase if has_phrase else None

        try:
            encrypted, padding_size = ClientCrypto.encrypt_message_with_padding(
                plaintext=plaintext,
                session_key=self.session_key,
                from_id=self.app.public_id,
                to_id=self.contact_id,
                message_counter=self._message_counter,
                prev_padding=self._last_padding_size,
                phrase=phrase,
            )

            message_id = ClientCrypto.generate_message_id(self._message_counter)
            timestamp = int(time.time())

            result = await self.app.api_client.send_message(
                to=self.contact_id,
                encrypted=encrypted.hex(),
                session_key=self.session_key.hex(),
                has_phrase=has_phrase,
                plaintext_len=len(plaintext),
                prev_padding=padding_size,
                message_counter=self._message_counter,
            )

            if result.get("success"):
                self._last_padding_size = padding_size
                self._message_counter += 1

                msg = ChatMessage(
                    message_id=message_id,
                    from_id=self.app.public_id,
                    to_id=self.contact_id,
                    encrypted=encrypted.hex(),
                    session_key=self.session_key.hex(),
                    timestamp=timestamp,
                    has_phrase=has_phrase,
                    decrypted_text=plaintext,
                    padding_size=padding_size,
                    counter=self._message_counter - 1,
                )
                msg.is_own = True
                msg.delivered = True
                self.messages.append(msg)
                self._refresh_messages_ui()
                return True
            else:
                self.app.show_warning(f"Send failed: {result.get('error')}")
                return False

        except Exception as e:
            log(f"Encryption/send error: {e}")
            self.app.show_warning(f"Failed to send: {e}")
            return False

    def _refresh_messages_ui(self) -> None:
        """Обновление отображения сообщений."""
        container = self.query_one("#messages-container", ScrollableContainer)
        container.remove_children()

        sorted_msgs = sorted(self.messages, key=lambda m: m.timestamp)

        for msg in sorted_msgs:
            time_str = time.strftime("%H:%M", time.localtime(msg.timestamp))

            if msg.is_system:
                # Системное сообщение
                message_row = Vertical(classes="message-row")
                bubble = Static(
                    f"{msg.display_text}\n"
                    f"[dim]{time_str}[/dim]",
                    classes=f"system-message {msg.system_type}"
                )
                bubble.tooltip = msg.system_detail
                message_row.mount(bubble)
                container.mount(message_row)
                continue

            # Обычное сообщение
            message_row = Vertical(classes="message-row")

            status_icons = ""
            if msg.is_own:
                if msg.delivered:
                    status_icons = "✓✓" if msg.read else "✓"
                else:
                    status_icons = "○"

            padding_info = f" [dim][{msg.padding_size}][/dim]" if msg.padding_size else ""

            bubble = Static(
                f"{msg.display_text}{padding_info}\n"
                f"[dim]{time_str}[/dim] {status_icons}",
                classes=f"message-bubble {'message-own' if msg.is_own else 'message-other'}"
            )

            if not msg.decrypted_text and msg.has_phrase and not self.current_phrase:
                bubble.add_class("message-hidden")

            message_row.mount(bubble)
            container.mount(message_row)

        container.scroll_end(animate=False)

    # =========================================================================
    # Обработчики событий
    # =========================================================================

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Обработка нажатий кнопок."""
        if event.button.id == "send-btn":
            input_widget = self.query_one("#message-input", Input)
            text = input_widget.value.strip()
            if text:
                input_widget.value = ""
                await self._encrypt_and_send(text)

        elif event.button.id == "set-phrase-btn":
            def on_submit(phrase: str):
                if phrase.strip():
                    asyncio.create_task(self._set_phrase(phrase.strip()))

            from textual.widgets import Input as TInput
            from textual.containers import Horizontal as H
            from textual.screen import ModalScreen

            class PhraseInputScreen(ModalScreen):
                def compose(self):
                    yield Vertical(
                        Static("Enter secret phrase:", id="title"),
                        TInput(placeholder="Phrase", id="phrase-input", password=True),
                        H(
                            Button("Save", id="save", variant="primary"),
                            Button("Cancel", id="cancel", variant="default"),
                        ),
                        id="dialog",
                    )

                def on_button_pressed(self, e):
                    if e.button.id == "save":
                        phrase = self.query_one("#phrase-input").value
                        self.dismiss(phrase)
                    else:
                        self.dismiss(None)

            phrase = await self.app.push_screen_wait(PhraseInputScreen())
            if phrase:
                await self._set_phrase(phrase)

        elif event.button.id == "clear-phrase-btn":
            from textual.screen import ModalScreen

            class ConfirmScreen(ModalScreen):
                def compose(self):
                    yield Vertical(
                        Static("Clear phrase? Messages will become unreadable.", id="title"),
                        H(
                            Button("Yes", id="yes", variant="error"),
                            Button("No", id="no", variant="default"),
                        ),
                        id="dialog",
                    )

                def on_button_pressed(self, e):
                    self.dismiss(e.button.id == "yes")

            confirmed = await self.app.push_screen_wait(ConfirmScreen())
            if confirmed:
                await self._clear_phrase()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Отправка по Enter."""
        if event.input.id == "message-input" and event.value.strip():
            await self._encrypt_and_send(event.value.strip())
            event.input.value = ""

    async def on_new_message(
        self,
        message_id: str,
        from_id: str,
        encrypted: str,
        session_key_hex: str,
        padding_size: Optional[int] = None,
        is_system: bool = False,
        system_type: Optional[str] = None,
        system_data: Optional[str] = None,
    ) -> None:
        """Обработка нового сообщения из WebSocket."""
        if from_id != self.contact_id:
            return

        counter = ClientCrypto.extract_counter_from_message_id(message_id)

        if is_system:
            data = None
            if system_data:
                try:
                    data = json.loads(system_data)
                except:
                    data = {"raw": system_data}

            msg = ChatMessage(
                message_id=message_id,
                from_id=from_id,
                to_id=self.app.public_id,
                encrypted=encrypted,
                session_key=session_key_hex,
                timestamp=int(time.time()),
                is_system=True,
                system_type=system_type,
                system_data=data,
            )
            msg.is_own = False
            self.messages.append(msg)
            self._refresh_messages_ui()
            return

        msg = ChatMessage(
            message_id=message_id,
            from_id=from_id,
            to_id=self.app.public_id,
            encrypted=encrypted,
            session_key=session_key_hex,
            timestamp=int(time.time()),
            padding_size=padding_size,
            counter=counter,
        )
        msg.is_own = False

        if self.session_key:
            decrypted = await self._decrypt_message(msg)
            if decrypted:
                msg.decrypted_text = decrypted

        self.messages.append(msg)
        self._refresh_messages_ui()

    async def on_message_delivered(self, message_id: str) -> None:
        """Обработка подтверждения доставки."""
        for msg in self.messages:
            if msg.id == message_id:
                msg.delivered = True
                self._refresh_messages_ui()
                break

    async def on_message_read(self, message_id: str) -> None:
        """Обработка подтверждения прочтения."""
        for msg in self.messages:
            if msg.id == message_id:
                msg.read = True
                self._refresh_messages_ui()
                break
