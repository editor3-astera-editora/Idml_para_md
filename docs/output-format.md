# Formato de saída

Anatomia da pasta `out/<slug>/` e schemas dos JSONs gerados.

## Anatomia geral

Após uma conversão, a pasta de um livro contém:

```
out/<book_slug>/
├── <book_slug>.md                  ← conversão (idml2md convert)
├── _report.json                    ← auditoria da conversão
└── assets/
    ├── img/                        ← raster copiado (JPG/PNG/GIF/TIF/WebP)
    ├── vector/                     ← SVG ou PNG (de .ai e .eps não-mat)
    └── eqs/                        ← (reservado) fallback raster de equações
```

O cache de equações compartilhado (entre execuções) fica fora desta pasta, em `<output_dir>/../.idml2md_cache/equations/<sha1>.tex`.

## `<slug>.md` (Markdown)

Layout fixo:

```markdown
# <Título do livro>

<front matter — title em **bold**, authors/imprint em *italic*>

## Sumário

- [Capítulo 1](#capitulo-1)
  - [Seção 1.1](#secao-1-1)
- [Capítulo 2](#capitulo-2)

<corpo: headings, parágrafos, listas, imagens, admonitions, code, tabelas, eqs>

## Referências

<reference entries>
```

Convenções:
- Headings em `#`..`####` (nível derivado do `level` no `paragraph_styles`).
- Inline: `**bold**`, `*italic*`, `***bold_italic***`, `<sup>`, `<sub>`.
- Equação inline: `$latex$`. Equação display: `$$\nlatex\n$$`.
- Imagens: `![alt](caminho-relativo)`; legenda em `*texto*` na linha seguinte.
- Admonition: GFM (`> [!NOTE]`, `> [!TIP]`, etc.).
- Listas: `-`, `1.`, `I.`, `A.` conforme `marker`. Sublistas indentadas com 2 espaços.

## `_report.json` (ConversionReport)

Schema completo (campos do dataclass em `idml_to_md.report.ConversionReport`):

```jsonc
{
  "tool_version": "0.1.0",
  "book_slug": "81-matematica-financeira",
  "book_title": "81 Matemática Financeira",

  "seen_paragraph_styles":     { "Texto principal": 412, "Títulos:T1": 18, ... },
  "unmapped_paragraph_styles": { "Estilo Novo Que Apareceu": 3 },
  "seen_character_styles":     { "Bold": 87, "Italic": 24 },
  "unmapped_character_styles": { },

  "block_counts": {
    "heading": 65, "paragraph": 412, "list": 19,
    "admonition": 8, "image": 23, "equation_display": 51, "table": 5, ...
  },

  "missing_assets": ["INOVA_F009.jpg"],
  "copied_assets": 71,

  "front_matter_blocks": 4,
  "body_blocks": 612,
  "reference_entries": 22,

  "equations_total": 84,
  "equations_failed": ["81_MF_Eqn073.eps"],
  "equation_cache_hits": 12,
  "equation_cache_misses": 72,

  "vector_converted": ["INOVA_F012.ai"],
  "vector_failed": []
}
```

Indicadores que merecem revisão imediata:
- `unmapped_paragraph_styles` ≠ `{}` → criar overlay YAML para a coleção.
- `missing_assets` ≠ `[]` → checar se a pasta `Links/` está completa.
- `equations_failed` longo → conferir se os EPS são realmente MathType (podem ser ilustrações).
- `vector_failed` ≠ `[]` → verificar Inkscape; fallback Ghostscript também falhou.

## Próximo

[scripts.md](scripts.md) — scripts auxiliares.
