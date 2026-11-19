import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

PADRAO_PROTOCOLO = re.compile(r"^UNIFAP-\d{4}(0[1-9]|1[0-2])-\d{6}$")


@dataclass(frozen=True, slots=True)
class Protocolo:
    valor: str

    def __post_init__(self) -> None:
        if not PADRAO_PROTOCOLO.fullmatch(self.valor):
            raise ValueError(f"Protocolo inválido: {self.valor!r}")

    def __str__(self) -> str:
        return self.valor


def agora_utc() -> datetime:
    return datetime.now(UTC)


class GeradorProtocoloUnifap:
    """Gera protocolos UNIFAP-AAAAMM-NNNNNN com sequência reiniciada a cada mês (thread-safe)."""

    def __init__(self, relogio: Callable[[], datetime] = agora_utc) -> None:
        self._relogio = relogio
        self._sequencias: dict[str, int] = {}
        self._lock = threading.Lock()

    def gerar(self) -> Protocolo:
        periodo = self._relogio().strftime("%Y%m")
        with self._lock:
            seq = self._sequencias.get(periodo, 0) + 1
            if seq > 999_999:
                raise OverflowError("Sequência mensal de protocolos esgotada.")
            self._sequencias[periodo] = seq
        return Protocolo(f"UNIFAP-{periodo}-{seq:06d}")
