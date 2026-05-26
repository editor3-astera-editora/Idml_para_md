# Documentação — idml-to-md

Pipeline IDML-first em Python para converter livros didáticos editoriais do Adobe InDesign em Markdown estruturado.

Substitui o pipeline anterior baseado em PyMuPDF + DocLayout-YOLO operando sobre o PDF final.

## Pipeline de conversão

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Conversão IDML → Markdown                                                │
│                                                                          │
│ <livro.idml>                                                             │
│      │                                                                   │
│      ├─► idml_reader       (abre ZIP de XMLs)                            │
│      ├─► thread_resolver   (ordem de leitura via PreviousTextFrame)      │
│      ├─► style_mapper      (YAML → kinds semânticos)                     │
│      ├─► story_walker      (XML → DocAST blocos)                         │
│      │     ├─► anchored_resolver  (raster / vetor / equação MathType)    │
│      │     ├─► equation_extractor (EPS → MathML)                         │
│      │     ├─► mathml_to_latex    (MathML → LaTeX, com cache)            │
│      │     └─► table_renderer     (Table → TableBlock)                   │
│      ├─► asset_processor   (cópia raster + Inkscape/Ghostscript)         │
│      ├─► toc_builder       (Headings → âncoras GFM)                      │
│      ├─► md_writer         (Document → string Markdown)                  │
│      └─► report            (auditoria → _report.json)                    │
│                                                                          │
│ out/<slug>/<slug>.md   +   _report.json   +   assets/                    │
└──────────────────────────────────────────────────────────────────────────┘
```

## Índice

### Guias de uso

- [installation.md](installation.md) — pré-requisitos, instalação, binários externos, validação.
- [cli.md](cli.md) — referência completa do CLI `idml2md`.
- [configuration.md](configuration.md) — `styles.default.yaml`, overlays por coleção.
- [pipeline-conversion.md](pipeline-conversion.md) — fluxo passo-a-passo da conversão IDML→MD.
- [output-format.md](output-format.md) — anatomia de `out/<slug>/` e schemas dos JSONs.
- [scripts.md](scripts.md) — scripts auxiliares (`extract_mathml_smoke`).
- [testing.md](testing.md) — suíte pytest, marcadores, cobertura, fixtures.
- [troubleshooting.md](troubleshooting.md) — problemas comuns e diagnóstico.

### Referência de API

- [api/core.md](api/core.md) — `cli`, `pipeline`, `config`, `models`, `report`.
- [api/idml-parsing.md](api/idml-parsing.md) — `idml_reader`, `thread_resolver`, `anchored_resolver`, `story_walker`, `style_mapper`.
- [api/equations-assets.md](api/equations-assets.md) — `equation_extractor`, `mathml_to_latex`, `asset_processor`, `table_renderer`.
- [api/output.md](api/output.md) — `toc_builder`, `md_writer`.
- [api/utils.md](api/utils.md) — `slugify`, `subprocess_safe`, `xml`.

## Status do projeto

| Fase | Escopo | Status |
|------|--------|--------|
| F0 | Scaffolding + CI + gate de cobertura ≥80% | entregue |
| F1 | MVP de conversão (headings, parágrafos, listas, imagens raster, TOC) | entregue |
| F2 | Equações MathType (MathML embutido → LaTeX, cache SHA-1) | entregue |
| F3 | Tabelas, admonitions, code blocks, vetoriais via Inkscape | entregue |
| F4 | `idml2md batch` paralelo + `validate` vs. PDF de referência | **previsto, não implementado** |

Os subcomandos `idml2md batch` e `idml2md validate` aparecem no plano original mas **ainda não existem** no `cli.py` — apenas `convert`, `inspect` e `version` estão implementados.

## Próximo

Comece por [installation.md](installation.md).
