"""
Integração com a planilha de follow-up (Excel) no OneDrive/SharePoint,
via Microsoft Graph API - sem precisar abrir o Excel.

Variáveis de ambiente necessárias:
    MS_CLIENT_ID       - Application (client) ID do App Registration no Azure
    MS_CLIENT_SECRET   - Client secret gerado para o App Registration
    MS_TENANT_ID       - Directory (tenant) ID
    MS_REFRESH_TOKEN   - Refresh token obtido uma vez via login delegado
                          (mesma ideia do GOOGLE_TOKEN usado na agenda)
    MS_DRIVE_ITEM_ID   - ID do arquivo .xlsx no OneDrive/SharePoint
    MS_DRIVE_ID        - (opcional) ID do drive, necessário se o arquivo estiver
                          num SharePoint/OneDrive compartilhado e não no "meu drive"
    MS_WORKSHEET_NAME  - (opcional) Nome da aba a usar. Padrão: "PLANILHA CONSOLIDADA"

Ver o guia de setup (SETUP_AZURE.md) para o passo a passo de como gerar
essas credenciais.
"""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import msal

MS_CLIENT_ID = os.getenv("MS_CLIENT_ID")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")
MS_TENANT_ID = os.getenv("MS_TENANT_ID")
MS_REFRESH_TOKEN = os.getenv("MS_REFRESH_TOKEN")
MS_DRIVE_ITEM_ID = os.getenv("MS_DRIVE_ITEM_ID")
MS_DRIVE_ID = os.getenv("MS_DRIVE_ID")
WORKSHEET_NAME = os.getenv("MS_WORKSHEET_NAME", "PLANILHA CONSOLIDADA")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
AUTHORITY = f"https://login.microsoftonline.com/{MS_TENANT_ID}" if MS_TENANT_ID else None


def _get_access_token():
    if not all([MS_CLIENT_ID, MS_CLIENT_SECRET, MS_TENANT_ID, MS_REFRESH_TOKEN]):
        raise ValueError(
            "Credenciais do Microsoft Graph não configuradas "
            "(MS_CLIENT_ID / MS_CLIENT_SECRET / MS_TENANT_ID / MS_REFRESH_TOKEN)."
        )

    app_msal = msal.ConfidentialClientApplication(
        client_id=MS_CLIENT_ID,
        client_credential=MS_CLIENT_SECRET,
        authority=AUTHORITY,
    )

    result = app_msal.acquire_token_by_refresh_token(
        MS_REFRESH_TOKEN,
        scopes=["Files.ReadWrite.All"],
    )

    if "access_token" not in result:
        raise ValueError(
            f"Falha ao obter token do Microsoft Graph: "
            f"{result.get('error_description', result)}"
        )

    return result["access_token"]


def _graph_headers():
    return {
        "Authorization": f"Bearer {_get_access_token()}",
        "Content-Type": "application/json",
    }


def _item_base_url():
    if not MS_DRIVE_ITEM_ID:
        raise ValueError("MS_DRIVE_ITEM_ID não configurado.")
    if MS_DRIVE_ID:
        return f"{GRAPH_BASE}/drives/{MS_DRIVE_ID}/items/{MS_DRIVE_ITEM_ID}"
    return f"{GRAPH_BASE}/me/drive/items/{MS_DRIVE_ITEM_ID}"


def _worksheet_url(path=""):
    return f"{_item_base_url()}/workbook/worksheets('{WORKSHEET_NAME}')" + path


def _get_used_range():
    resp = requests.get(
        _worksheet_url("/usedRange(valuesOnly=true)"),
        headers=_graph_headers(),
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _proximo_item_e_linha():
    """
    Lê o intervalo usado da aba e descobre:
    - o próximo número de ITEM (maior ITEM existente na coluna B + 1)
    - a próxima linha em branco para escrever a nova solicitação

    Assume que a coluna B (índice 0 dentro do range retornado) é a coluna ITEM,
    igual ao layout real da planilha PLANILHA CONSOLIDADA / ROT (colunas A:Q,
    onde a primeira coluna do usedRange normalmente é A, então B fica no
    índice 1 - por isso pegamos row[1] abaixo. Se o usedRange já começar em B,
    ajuste para row[0].
    """
    data = _get_used_range()
    values = data.get("values", [])
    row_offset = data.get("rowIndex", 0)
    col_offset = data.get("columnIndex", 0)

    # índice da coluna B dentro do array de valores retornado
    idx_item = 1 - col_offset if col_offset <= 1 else 0

    maior_item = 0
    ultima_linha_com_dado = row_offset

    for i, row in enumerate(values):
        linha_absoluta = row_offset + i + 1  # +1 porque o Graph é 0-based e o Excel é 1-based
        if not row or idx_item >= len(row):
            continue
        item_val = row[idx_item]
        if item_val not in (None, ""):
            ultima_linha_com_dado = linha_absoluta
            try:
                num = int(float(str(item_val).split(".")[0]))
                maior_item = max(maior_item, num)
            except (ValueError, TypeError):
                pass

    return maior_item + 1, ultima_linha_com_dado + 1


def criar_solicitacao_planilha(responsavel, contrato, pedido, solicitante):
    """
    Insere uma nova linha na aba configurada (padrão: PLANILHA CONSOLIDADA)
    seguindo o layout real da planilha FUP-001:

        B=ITEM, C=CC/PP, D=SOLICITANTE(GMS), E=CONTRATO, F=SOLICITANTE(cliente),
        G=RESPONSÁVEL/EXECUTANTE, H=LANÇAMENTO, I=ACOMPANHAMENTO,
        J=PALAVRA CHAVE, K=SOLICITAÇÃO, L=FOLLOW-UP, M=STATUS,
        N=DATA SOLICITAÇÃO, O=PROG, P=REPROG., Q=CONCLUSÃO

    Colunas que o bot não tem como preencher automaticamente (C, F, H, I, J,
    L, O, P, Q) ficam em branco para a assistente física completar depois.
    Retorna o número do ITEM criado.
    """
    proximo_item, proxima_linha = _proximo_item_e_linha()
    hoje = datetime.now(ZoneInfo("America/Sao_Paulo")).strftime("%Y-%m-%d")

    linha_valores = [[
        proximo_item,   # B - ITEM
        "",              # C - CC/PP
        solicitante,     # D - SOLICITANTE (GMS)
        contrato or "",  # E - CONTRATO
        "",              # F - SOLICITANTE (cliente)
        responsavel,     # G - RESPONSÁVEL/EXECUTANTE
        "",              # H - LANÇAMENTO
        "",              # I - ACOMPANHAMENTO
        "",              # J - PALAVRA CHAVE
        pedido,          # K - SOLICITAÇÃO
        "",              # L - FOLLOW-UP
        "PENDENTE",      # M - STATUS
        hoje,            # N - DATA SOLICITAÇÃO
        "",              # O - PROG
        "",              # P - REPROG.
        "",              # Q - CONCLUSÃO
    ]]

    endereco = f"B{proxima_linha}:Q{proxima_linha}"
    resp = requests.patch(
        _worksheet_url(f"/range(address='{endereco}')"),
        headers=_graph_headers(),
        json={"values": linha_valores},
        timeout=30,
    )
    resp.raise_for_status()
    return proximo_item
