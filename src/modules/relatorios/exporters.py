"""Exportadores CSV e PDF (PDF 1.4 mínimo gerado sem dependências externas)."""

import csv
import io

from src.modules.relatorios.interfaces import AgregadoDTO, RelatorioHistoricoDTO

_PREFIXOS_FORMULA_CSV = ("=", "+", "-", "@", "\t", "\r")


def _sanitizar_celula_csv(valor: str) -> str:
    """V12: neutraliza CSV / Formula Injection em planilhas (OWASP)."""
    if valor and valor.lstrip().startswith(_PREFIXOS_FORMULA_CSV):
        return "'" + valor
    return valor


def _sanitizar_linha_csv(campos: list[str]) -> list[str]:
    return [_sanitizar_celula_csv(c) for c in campos]


def _linhas_agregado(secao: str, itens: list[AgregadoDTO]) -> list[list[str]]:
    return [[secao, a.chave, str(a.total), str(a.resolvidos), str(a.reaberturas),
             "" if a.tmr_horas is None else f"{a.tmr_horas:.2f}"] for a in itens]


def exportar_csv(r: RelatorioHistoricoDTO) -> bytes:
    buffer = io.StringIO()
    w = csv.writer(buffer, delimiter=";")
    w.writerow(_sanitizar_linha_csv(
        ["secao", "chave", "total", "resolvidos", "reaberturas", "tmr_horas"]))
    w.writerow(_sanitizar_linha_csv(
        ["GERAL", "TOTAL", str(r.total_chamados), "", "",
         "" if r.tmr_geral_horas is None else f"{r.tmr_geral_horas:.2f}"]))
    for status, qtd in sorted(r.por_status.items()):
        w.writerow(_sanitizar_linha_csv(["STATUS", status, str(qtd), "", "", ""]))
    for linha in _linhas_agregado("LOCAL", r.por_local) + _linhas_agregado(
            "EQUIPAMENTO", r.por_equipamento):
        w.writerow(_sanitizar_linha_csv(linha))
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")  # BOM para Excel


def _escapar_pdf(texto: str) -> str:
    """V19: remove quebras de linha/controle e escapa delimitadores do PDF."""
    limpo = "".join(" " if ord(ch) < 32 or ord(ch) == 127 else ch for ch in texto)
    return limpo.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def exportar_pdf(r: RelatorioHistoricoDTO) -> bytes:
    linhas = [
        "Relatorio de Chamados - UNIFAP",
        f"Gerado em: {r.gerado_em:%d/%m/%Y %H:%M} UTC",
        f"Total de chamados: {r.total_chamados}",
        f"TMR geral (h): {r.tmr_geral_horas if r.tmr_geral_horas is not None else '-'}",
        f"Media de avaliacao: {r.media_avaliacao if r.media_avaliacao is not None else '-'}",
        "",
        "Por local:",
        *(f"  {a.chave}: total={a.total} resolvidos={a.resolvidos} tmr={a.tmr_horas}"
          for a in r.por_local),
        "",
        "Por equipamento:",
        *(f"  {a.chave}: total={a.total} resolvidos={a.resolvidos} tmr={a.tmr_horas}"
          for a in r.por_equipamento),
    ][:50]
    corpo = ["BT", "/F1 11 Tf", "14 TL", "50 800 Td"]
    corpo += [f"({_escapar_pdf(linha)}) '" for linha in linhas]
    corpo.append("ET")
    stream = "\n".join(corpo).encode("latin-1", errors="replace")

    objetos = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    saida = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, obj in enumerate(objetos, start=1):
        offsets.append(len(saida))
        saida += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(saida)
    saida += f"xref\n0 {len(objetos) + 1}\n0000000000 65535 f \n".encode()
    saida += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    saida += (f"trailer\n<< /Size {len(objetos) + 1} /Root 1 0 R >>\n"
              f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(saida)
