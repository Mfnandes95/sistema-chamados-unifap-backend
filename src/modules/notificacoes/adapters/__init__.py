"""Adaptadores de canal em memória (mocks de SMTP e Push)."""

from dataclasses import dataclass, field

from src.modules.notificacoes.interfaces import Destinatario, EventoNotificacao


@dataclass(frozen=True, slots=True)
class MensagemEnviada:
    destino: str
    protocolo: str
    assunto: str
    corpo: str


@dataclass
class InMemorySmtpAdapter:
    enviadas: list[MensagemEnviada] = field(default_factory=list)
    falhar: bool = False

    @property
    def nome(self) -> str:
        return "smtp"

    async def enviar(self, evento: EventoNotificacao, destinatario: Destinatario) -> None:
        if self.falhar:
            raise ConnectionError("SMTP indisponível (simulado)")
        self.enviadas.append(MensagemEnviada(
            destinatario.email, evento.protocolo, f"[UNIFAP] {evento.tipo.value}",
            evento.mensagem))


@dataclass
class InMemoryPushAdapter:
    enviadas: list[MensagemEnviada] = field(default_factory=list)
    falhar: bool = False

    @property
    def nome(self) -> str:
        return "push"

    async def enviar(self, evento: EventoNotificacao, destinatario: Destinatario) -> None:
        if self.falhar:
            raise ConnectionError("Push indisponível (simulado)")
        self.enviadas.append(MensagemEnviada(
            destinatario.id, evento.protocolo, evento.tipo.value, evento.mensagem))


__all__ = ["InMemoryPushAdapter", "InMemorySmtpAdapter", "MensagemEnviada"]
