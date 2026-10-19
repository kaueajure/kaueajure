#!/usr/bin/env python3
"""Gera SVGs públicos com métricas agregadas, sem divulgar repositórios privados."""
import html
import json
import os
import pathlib
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

LOGIN = "kaueajure"
TOKEN = os.environ.get("PROFILE_STATS_TOKEN", "").strip()
BASE = "https://api.github.com"
DESTINO = pathlib.Path("assets")
CORES = ["#58a6ff", "#3fb950", "#d2a8ff", "#f0883e", "#f778ba", "#79c0ff"]

def github(caminho, params=None, aceitar_vazio=False):
    url = BASE + caminho
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + TOKEN,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "perfil-estatisticas-kaueajure",
    })
    try:
        with urlopen(req, timeout=35) as res:
            return json.load(res)
    except HTTPError as err:
        if aceitar_vazio and err.code in (404, 409):
            return []
        raise RuntimeError(f"GitHub API retornou HTTP {err.code}") from err
    except (URLError, TimeoutError) as err:
        raise RuntimeError("Nao foi possivel consultar a API do GitHub") from err

def listar_repositorios():
    encontrados = []
    pagina = 1
    while True:
        lote = github("/user/repos", {
            "affiliation": "owner", "visibility": "all",
            "per_page": 100, "page": pagina,
        })
        encontrados.extend(r for r in lote
                          if r.get("owner", {}).get("login", "").lower() == LOGIN.lower()
                          and not r.get("fork")
                          and r.get("name", "").lower() != LOGIN.lower())
        if len(lote) < 100:
            return encontrados
        pagina += 1
        if pagina > 20:
            raise RuntimeError("Paginacao incompleta dos repositorios")

def contar_commits(repo, desde):
    total = 0
    pagina = 1
    while True:
        lote = github("/repos/" + LOGIN + "/" + quote(repo, safe="") + "/commits", {
            "author": LOGIN, "since": desde,
            "per_page": 100, "page": pagina,
        }, aceitar_vazio=True)
        total += len(lote)
        if len(lote) < 100:
            return total
        pagina += 1
        if pagina > 100:
            raise RuntimeError("Muitos commits para paginar com seguranca")

def texto(x, y, conteudo, tamanho=18, cor="#c9d1d9", peso="400", ancora="start"):
    return (f'<text x="{x}" y="{y}" font-family="Arial,Helvetica,sans-serif" '
            f'font-size="{tamanho}" font-weight="{peso}" text-anchor="{ancora}" '
            f'fill="{cor}">{html.escape(str(conteudo))}</text>')

def fundo(largura, altura, titulo):
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="{html.escape(titulo, quote=True)}" '
        f'viewBox="0 0 {largura} {altura}" width="{largura}" height="{altura}">',
        f'<title>{html.escape(titulo)}</title>',
        f'<rect x="0.5" y="0.5" width="{largura-1}" height="{altura-1}" '
        f'rx="14" fill="#0d1117" stroke="#30363d"/>',
    ]

def geral(qtd, privados, commits, total_linguagens, atualizado):
    desenho = fundo(840, 230, "Estatisticas de desenvolvimento de Kauê Ajure")
    desenho += [texto(30, 44, "ATIVIDADE DE DESENVOLVIMENTO", 17, "#58a6ff", "700")]
    for i, (numero, rotulo) in enumerate((
        (qtd, "Projetos analisados"),
        (commits, "Commits em 12 meses"),
        (total_linguagens, "Linguagens identificadas"),
    )):
        x = 42 + i * 273
        desenho += [texto(x, 111, numero, 47, "#f0f6fc", "700"),
                    texto(x, 144, rotulo, 15, "#8b949e")]
    desenho += [
        '<line x1="30" y1="172" x2="810" y2="172" stroke="#30363d"/>',
        texto(30, 196, f"Inclui {privados} projetos privados; sem publicar nomes ou codigo.", 13, "#8b949e"),
        texto(810, 215, f"Atualizado em {atualizado} (UTC)", 11, "#8b949e", ancora="end"),
        "</svg>",
    ]
    return "\n".join(desenho) + "\n"

def linguagens(contador, atualizado):
    total = sum(contador.values())
    if not total:
        raise RuntimeError("Sem dados de linguagens: verificar o acesso aos repositorios")
    principais = contador.most_common(6)
    restantes = total - sum(valor for _, valor in principais)
    if restantes:
        principais.append(("Outras", restantes))
    h = 110 + len(principais) * 41 + 34
    desenho = fundo(840, h, "Linguagens usadas nos repositorios do GitHub")
    desenho += [
        texto(30, 43, "LINGUAGENS NOS PROJETOS", 18, "#58a6ff", "700"),
        texto(30, 69, "Percentuais por bytes de codigo identificados pelo GitHub Linguist", 13, "#8b949e"),
    ]
    for i, (linguagem, bytes_codigo) in enumerate(principais):
        y = 107 + i * 41
        percentual = bytes_codigo / total * 100
        cor = CORES[i % len(CORES)]
        largura = max(2, round(460 * bytes_codigo / total))
        desenho += [
            texto(30, y + 4, linguagem, 15, "#c9d1d9", "600"),
            f'<rect x="260" y="{y-13}" width="460" height="17" rx="5" fill="#21262d"/>',
            f'<rect x="260" y="{y-13}" width="{largura}" height="17" rx="5" fill="{cor}"/>',
            texto(805, y + 4, f"{percentual:.1f}%", 14, "#f0f6fc", "600", "end"),
        ]
    desenho += [texto(30, h - 17, f"Projetos publicos e privados | {atualizado} (UTC)", 12, "#8b949e"),
                "</svg>"]
    return "\n".join(desenho) + "\n"

def main():
    if not TOKEN:
        raise RuntimeError("Configure PROFILE_STATS_TOKEN nos Secrets do repositorio de perfil")
    dono = github("/user").get("login", "")
    if dono.lower() != LOGIN.lower():
        raise RuntimeError("O token nao pertence ao usuario esperado")
    repos = listar_repositorios()
    if len(repos) < 13:
        raise RuntimeError("Acesso incompleto: esperados pelo menos 13 projetos (incluindo privados).")
    desde = (datetime.now(timezone.utc) - timedelta(days=365)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    contagem = Counter()
    commits = 0
    for repo in repos:
        nome = repo["name"]
        codificado = quote(nome, safe="")
        langs = github("/repos/" + LOGIN + "/" + codificado + "/languages")
        for idioma, tamanho in langs.items():
            contagem[idioma] += tamanho
        commits += contar_commits(nome, desde)
    hoje = datetime.now(timezone.utc).strftime("%d/%m/%Y")
    DESTINO.mkdir(parents=True, exist_ok=True)
    (DESTINO / "stats-gerais.svg").write_text(
        geral(len(repos), sum(bool(r.get("private")) for r in repos), commits, len(contagem), hoje),
        encoding="utf-8")
    (DESTINO / "linguagens.svg").write_text(linguagens(contagem, hoje), encoding="utf-8")
    print("Estatisticas agregadas geradas; nenhum nome privado foi incluido nos SVGs.")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        sys.exit(1)
