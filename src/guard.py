import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional

CREDENTIAL_PATTERNS: dict[str, re.Pattern] = {
    "token Bearer": re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]{16,}=*"),
    "chave privada": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "chave de acesso AWS": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "chave de API do Google": re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),
    "token do GitHub": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "token do Slack": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    "chave de API (sk-)": re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    "segredo hexadecimal longo": re.compile(r"\b[a-fA-F0-9]{48,}\b"),
    "senha ou segredo atribuído": re.compile(
        r"(?i)\b(?:password|passwd|senha|secret|api[_-]?key|access[_-]?token|token)\b\s*[:=]\s*[\"'][^\"'\s]{8,}[\"']"
    ),
}


class ContentRejected(ValueError):
    pass


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def parse_terms(raw: Optional[str]) -> list[str]:
    return [term.strip() for term in (raw or "").split(",") if term.strip()]


@dataclass(frozen=True)
class ContentGuard:
    blocked_terms: tuple[str, ...] = ()

    @classmethod
    def from_terms(cls, terms: Iterable[str]) -> "ContentGuard":
        return cls(tuple(t for t in terms if t.strip()))

    def find_credential(self, text: str) -> Optional[str]:
        for label, pattern in CREDENTIAL_PATTERNS.items():
            if pattern.search(text):
                return label
        return None

    def find_blocked_term(self, text: str) -> Optional[str]:
        normalized = _normalize(text)
        for term in self.blocked_terms:
            if re.search(rf"(?<!\w){re.escape(_normalize(term))}(?!\w)", normalized):
                return term
        return None

    def check(self, **fields: object) -> None:
        for field, value in fields.items():
            if value is None:
                continue
            text = " ".join(value) if isinstance(value, (list, tuple)) else str(value)

            credential = self.find_credential(text)
            if credential:
                raise ContentRejected(
                    f"Memória recusada: o campo '{field}' parece conter uma credencial ({credential}). "
                    "Remova o valor sensível e descreva só o procedimento."
                )

            term = self.find_blocked_term(text)
            if term:
                raise ContentRejected(
                    f"Memória recusada: o campo '{field}' contém o termo bloqueado '{term}'. "
                    "Reescreva de forma genérica, sem nomes de empresa, sistemas internos, clientes ou regras de negócio."
                )
