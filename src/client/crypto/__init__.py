# src/client/crypto/__init__.py
"""
Клиентская криптография для TUI и веб-интерфейса.
Реализует те же алгоритмы, что и в веб-версии.
"""

from .aes import generate_session_key, encrypt, decrypt
from .directional import (
    get_directional_key,
    encrypt_directional,
    decrypt_directional,
    encrypt_directional_with_padding,
    decrypt_directional_with_padding,
)
from .phrase import encrypt_with_phrase, decrypt_with_phrase, derive_phrase_key, xor_keys
from .pfs import (
    DialogState,
    rotate_key,
    attach_flags,
    extract_flags,
    should_rotate,
    send_rotate_confirmation,
    request_resync,
)
from .ecdh import (
    generate_ecdh_keypair,
    compute_shared_secret,
    derive_new_key,
    generate_request_id,
)

# LRP модули удалены. Для обратной совместимости оставляем заглушки.
# Если какой-то код ещё импортирует LotteryRatchet, он получит None.
LotteryRatchet = None
LotteryMessage = None
KeyPoolState = None
KeyPoolManager = None
TransitionManager = None
TransitionState = None
ACTIVE_POOL_SIZE = 8
TOTAL_POOL_SIZE = 16

__all__ = [
    # AES
    "generate_session_key", "encrypt", "decrypt",
    # Directional
    "get_directional_key", "encrypt_directional", "decrypt_directional",
    "encrypt_directional_with_padding", "decrypt_directional_with_padding",
    # Phrase
    "encrypt_with_phrase", "decrypt_with_phrase", "derive_phrase_key", "xor_keys",
    # PFS
    "DialogState", "rotate_key", "attach_flags", "extract_flags",
    "should_rotate", "send_rotate_confirmation", "request_resync",
    # ECDH (новое)
    "generate_ecdh_keypair", "compute_shared_secret", "derive_new_key", "generate_request_id",
    # LRP заглушки (для обратной совместимости)
    "LotteryRatchet", "LotteryMessage", "KeyPoolState", "KeyPoolManager",
    "TransitionManager", "TransitionState", "ACTIVE_POOL_SIZE", "TOTAL_POOL_SIZE",
]
