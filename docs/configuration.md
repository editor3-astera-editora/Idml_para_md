# Configuração

Tudo que muda entre coleções editoriais (mapeamentos de estilo) mora em YAML.

## `config/styles.default.yaml`

Mapa declarativo de **ParagraphStyle** e **CharacterStyle** do InDesign para a semântica Markdown. Carregado por `idml_to_md.style_mapper.build_style_map`.

### Estrutura geral

```yaml
version: 1

defaults:
  unknown_paragraph_style: passthrough   # passthrough | warn | drop
  unknown_character_style: passthrough

paragraph_styles:
  "Nome do estilo no InDesign":   { kind: <kind>, ... }

character_styles:
  "Nome do char style":           { wrap: "**" }   # ou: { html: sup }

admonitions:
  format: github                  # github | obsidian | mkdocs
  variants:
    note:    { gh_tag: NOTE,    emoji: "" }

tables:
  prefer: gfm
  fallback_html_on_merged_cells: true
  fallback_html_on_nested_table: true
  fallback_html_on_block_content_in_cell: true

equations:
  inline_delim: ["$", "$"]
  display_delim: ["$$", "$$"]
  save_eps_fallback: true
  cache_dir: ".idml2md_cache/equations"

images:
  ai_to: svg                       # svg | png
  eps_nonmath_to: svg
  copy_dir: assets/img
  vector_dir: assets/vector
  equations_dir: assets/eqs
  dedup_by_hash: true
```

### Kinds de parágrafo suportados

Devem ser sincronizados com `idml_to_md.models.BlockKind`:

| `kind` | Comportamento no MD |
|---|---|
| `heading` | `#` … `####` conforme `level`. `starts_chapter: true` é metadado (sem efeito no MD ainda). |
| `paragraph` | Parágrafo de texto corrente. |
| `list` | Item de lista. Aceita `ordered`, `marker` (`decimal`/`upper-roman`/`upper-alpha`), `level`, `nested` (aninha sob lista anterior de tipo diferente). |
| `admonition` | Conteúdo de admonition. Aceita `variant` (`note`/`tip`/`warning`/`important`/`caution`) e `title`. |
| `admonition_title` | Marca um parágrafo como _título_ da próxima admonition (não cria bloco). |
| `blockquote` | `> ...`. |
| `code_block` | Fenced code block. `language` é opcional. |
| `caption` | Itálico abaixo de imagem/tabela. `role`: `caption`, `source_line`, `image_credit`, `image_anchor`, `infographic_label`. |
| `front_matter` | Coletado em `Document.front_matter` (renderiza antes do TOC). `role`: `title`, `authors`, `imprint`, `cover_page`, `unit_title`. |
| `reference_entry` | Coletado em `Document.references` (renderiza após o corpo, sob `## Referências`). |
| `drop` | Silenciosamente descartado (ex.: `Rodapé`, `Sumario:*`). |
| `passthrough` | Política para estilos desconhecidos — caem em parágrafo genérico. |

### Kinds de CharacterStyle

| `kind` (chave do dict) | Efeito |
|---|---|
| `wrap` | Envolve o texto: `wrap: "**"` → `**texto**`. |
| `html` | Envolve em tag HTML: `html: sup` → `<sup>texto</sup>`. |

CharacterStyles ausentes do mapeamento são silenciados quando começam com `$ID/` (estilos defaults do InDesign) e contabilizados em `unmapped_character_styles` no `_report.json` caso contrário.

### Como customizar por coleção

Crie `config/styles.<colecao>.yaml` com apenas o que diferir do default. O carregador faz **deep-merge** preservando chaves não mencionadas:

```yaml
# config/styles.matematica.yaml
paragraph_styles:
  "Texto BOX DICA":   { kind: admonition, variant: tip, title: "Dica" }
  "Lema":             { kind: blockquote }

character_styles:
  "Itálico_destaque": { wrap: "_" }
```

Aplique com:

```bash
idml2md convert livro.idml -c config/styles.matematica.yaml
```

### Política para estilos desconhecidos

`defaults.unknown_paragraph_style` controla o que fazer com ParagraphStyles que não aparecem em `paragraph_styles`:

- `passthrough` _(default)_ — converte como parágrafo genérico; registra em `unmapped_paragraph_styles` no `_report.json`.
- `warn` — idem, mas garante registro (mesmo efeito prático).
- `drop` — descarta o parágrafo (perigo: pode perder conteúdo; use só após inspecionar com `idml2md inspect`).

## Próximo

[pipeline-conversion.md](pipeline-conversion.md) — como a configuração é aplicada na conversão.
