# idml-to-md

> Pipeline **IDML-first** para converter livros didáticos do Adobe InDesign em Markdown estruturado, com **alta fidelidade** ao conteúdo editorial original — sem OCR.
>

---

## Por que IDML?

O `.idml` é a representação XML aberta do projeto InDesign — preserva a semântica editorial que se perde ao rasterizar para PDF. Combinado com os assets vinculados (`Links/*.eps`, `*.ai`, `*.jpg`), permite reconstruir o livro com fidelidade máxima:

- **Hierarquia** derivada dos nomes de ParagraphStyle (`Títulos:T1`–`T4` → `#`–`####`).
- **Equações** extraídas do **MathML embutido** nos comentários PostScript dos EPS gerados pela MathType — sem OCR, sem heurística visual.
- **Imagens** copiadas (raster) ou convertidas (vetorial `.ai`/`.eps` → SVG via Inkscape).
- **Tabelas** mapeadas para GFM, com fallback HTML para células mescladas/aninhadas.
- **Caixas de destaque** viram admonitions GFM (`> [!NOTE]`).

## Recursos principais

- Conversão **um IDML → um arquivo `.md`** com TOC automático no topo.
- Mapeamento de estilos InDesign → Markdown via YAML (default + overlays por coleção, deep-merge).
- Conversão **MathML → LaTeX** em Python puro, com cache em disco por hash.
- Processamento de assets: cópia de raster, conversão vetorial via Inkscape (fallback Ghostscript → PNG 300 dpi).
- Renderização de tabelas em GFM ou HTML automático conforme a estrutura.
- `_report.json` de auditoria por conversão: estilos não mapeados, assets faltando, equações que falharam, contagens por tipo de bloco.
- CLI `idml2md` (Typer + Rich) com saída legível e logs estruturados (loguru).

## Pré-requisitos

- **Python ≥ 3.11** — obrigatório.
- **Binários externos — todos opcionais**, com degradação graciosa:

| Binário | Versão mínima | Para quê | Sem ele |
|---------|---------------|----------|---------|
| Inkscape | 1.2 | `.ai`/`.eps` não-matemáticos → SVG | Fallback para Ghostscript (PNG) |
| Ghostscript | 10 | Fallback raster de vetores a 300 dpi | Vetores não convertem; aparecem como links faltando no report |
| Saxon-HE + Java 17 | 12+ | Alternativa MathML→LaTeX via `mml2tex` | O conversor padrão é Python puro; não precisa instalar |

> **Windows.** O CLI procura o `inkscape.exe` em três lugares, nessa ordem: a flag `--inkscape`, a env var `IDML2MD_INKSCAPE_PATH`, e o `PATH` do sistema. Em instalações típicas o caminho é `C:\Program Files\Inkscape\bin\inkscape.exe`.

## Instalação

```bash
# Uso de desenvolvimento (com pytest, ruff, mypy)
pip install -e ".[dev]"

# Uso simples
pip install .
```

Verifique:

```bash
idml2md version
# 0.1.0
```

## Como gerar um arquivo Markdown — passo a passo

### Passo 1 — Organize as entradas

O conversor espera um `.idml` com uma pasta `Links/` **irmã** contendo os assets vinculados (imagens raster, ilustrações vetoriais, EPS gerados pela MathType):

```
Indesign_exemplos/
  81_Matemática Financeira.idml
  Links/
    81_MF_Eqn001.eps      ← equação MathType (MathML embutido)
    diagrama.ai           ← ilustração vetorial
    capa.jpg
    foto_01.png
    grafico.eps
```

Se a pasta `Links/` estiver em outro lugar, use `--links <caminho>` na conversão.

### Passo 2 — Converta

Comando mínimo:

```bash
idml2md convert "Indesign_exemplos/81_Matemática Financeira.idml" -o out
```

Com overlay e Inkscape explícito (caso Windows):

```bash
idml2md convert "Indesign_exemplos/81_Matemática Financeira.idml" \
  -o out \
  -c config/styles.matematica.yaml \
  --inkscape "C:/Program Files/Inkscape/bin/inkscape.exe" \
  -v
```

Flags úteis: `-o/--output` (pasta-pai, default `out/`), `-c/--config` (overlay YAML), `-t/--title` (sobrescreve o título derivado do nome do arquivo), `--links` (pasta de assets se não for irmã), `-v/--verbose` (logs DEBUG).

### Passo 3 — Verifique a saída

Para cada livro convertido:

```
out/<book_slug>/
  <book_slug>.md       ← arquivo único, com TOC no topo
  _report.json         ← auditoria da conversão
  assets/
    img/               ← JPG/PNG copiados de Links/
    vector/            ← SVG (oriundos de .ai/.eps não-matemáticos)
    eqs/               ← fallback raster de equações quando MathML falha
```

O `<book_slug>` é o nome do arquivo convertido para minúsculas/ASCII/hífens (ex.: `81_Matemática Financeira` → `81-matematica-financeira`).

### Passo 4 — Audite via `_report.json`

Campos mais úteis para revisão:

| Campo | Para quê serve |
|-------|----------------|
| `unmapped_paragraph_styles` | Estilos do IDML que **não** estão no YAML — candidatos a overlay. |
| `seen_paragraph_styles` | Contagem de cada estilo realmente encontrado no livro. |
| `missing_assets` | Imagens referenciadas no IDML mas ausentes na pasta `Links/`. |
| `equations_failed` | EPS de MathType cuja extração de MathML falhou. |
| `equation_cache_hits/misses` | Eficiência do cache de conversão MathML→LaTeX. |
| `vector_converted` / `vector_failed` | Resultado da conversão Inkscape/Ghostscript. |
| `block_counts` | Contagem por tipo (headings, paragraphs, lists, tables, images, equations…). |

Fluxo típico: revise os `unmapped_paragraph_styles`, ajuste o overlay (passo 3), reconverta. Repita até a lista zerar.

## Referência da CLI

```bash
idml2md --help
```

| Comando | O que faz | Flags principais |
|---------|-----------|------------------|
| `idml2md convert <idml>` | Converte um IDML para um único `.md` | `-o`, `-c`, `-t`, `--links`, `--inkscape`, `-v` |
| `idml2md inspect <idml>` | Lista `ParagraphStyles` com contagem de uso | `--top N` |
| `idml2md version` | Imprime a versão instalada | — |

Detalhes completos em [`docs/cli.md`](docs/cli.md).

## Configuração

O ponto de partida é [`config/styles.default.yaml`](config/styles.default.yaml). Cada coleção pode ter um overlay próprio em `config/styles.<colecao>.yaml`, aplicado via `-c`. As seções principais do YAML são:

- `paragraph_styles` — mapeia cada nome de `ParagraphStyle` do InDesign para um `kind` Markdown (com opções como `level`, `ordered`, `marker`, `variant`, `role`).
- `character_styles` — mapeia `CharacterStyle` para envoltórios (`wrap: "**"`) ou tags HTML (`html: sup`).
- `admonitions` — formato (`github`/`obsidian`/`mkdocs`) e variantes (`note`/`tip`/`warning`).
- `tables` — preferência GFM e regras de fallback HTML.
- `equations` — delimitadores `$...$`/`$$...$$`, cache, fallback raster.
- `images` — destino dos diferentes tipos de asset e deduplicação por hash.

Referência completa: [`docs/configuration.md`](docs/configuration.md).

## Desenvolvimento

```bash
pytest                              # unit (rápido, binários mockados)
pytest -m integration               # testes com binários reais
pytest --cov --cov-fail-under=80    # gate do CI
ruff check . && ruff format .
mypy idml_to_md
```

Cobertura de testes mínima **80%** — política do projeto, gate no CI. Marcadores disponíveis: `integration` (pulado por default no loop local) e `slow` (>5s). Detalhes em [`docs/testing.md`](docs/testing.md).

Smoke test específico para extração de equações:

```bash
python scripts/extract_mathml_smoke.py "Indesign_exemplos/Links" --verbose
```

Falha se a taxa de sucesso sobre EPS de MathType cair abaixo de 95%. Veja [`docs/scripts.md`](docs/scripts.md).

## Troubleshooting rápido

- **`Inkscape não encontrado`** → use `--inkscape <caminho>` ou exporte `IDML2MD_INKSCAPE_PATH`. Sem ele, vetores caem para PNG via Ghostscript; sem Ghostscript, aparecem em `vector_failed` no report.
- **Equações faltando ou sem fórmula** → rode `scripts/extract_mathml_smoke.py` na pasta `Links/`. Se um EPS não tem MathML embutido (não foi gerado pela MathType), aparece em `equations_failed`.
- **`unmapped_paragraph_styles` longa** → rode `idml2md inspect` para ver os mais frequentes, adicione-os ao overlay YAML e reconverta.
- **`Links/` em local fora do padrão** → passe `--links <pasta>`.
- **Saída sem assets / imagens quebradas** → verifique `missing_assets` no `_report.json`; geralmente é caminho de `Links/` errado ou arquivo não exportado pelo InDesign.

Mais cenários em [`docs/troubleshooting.md`](docs/troubleshooting.md).

## Documentação adicional

- [`docs/installation.md`](docs/installation.md) — instalação detalhada (incl. binários no Windows/macOS/Linux).
- [`docs/cli.md`](docs/cli.md) — referência completa dos comandos e flags.
- [`docs/configuration.md`](docs/configuration.md) — schema YAML, todos os `kind` e opções.
- [`docs/pipeline-conversion.md`](docs/pipeline-conversion.md) — fluxo interno passo a passo.
- [`docs/output-format.md`](docs/output-format.md) — anatomia da pasta de saída e schema do `_report.json`.
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — diagnóstico de problemas comuns.
- [`docs/api/`](docs/api/) — referência por módulo (parsing, equações/assets, output, utils, core).