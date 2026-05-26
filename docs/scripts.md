# Scripts auxiliares

Scripts em `scripts/` que complementam o CLI principal.

## `scripts/extract_mathml_smoke.py`

**Propósito.** Smoke test do pipeline de equações (F2): extrai MathML de todos os `.eps` de uma pasta, converte para LaTeX, e reporta a taxa de sucesso. Útil para validar uma coleção nova antes de rodar a conversão completa.

**Uso.**

```bash
python scripts/extract_mathml_smoke.py <pasta_com_eps> [OPÇÕES]
```

| Argumento | Tipo | Default | Descrição |
|---|---|---|---|
| `links_dir` | Path | — | Pasta com os `.eps` (obrigatório). |
| `--verbose` | flag | desativado | Imprime cada equação processada (LaTeX truncado em 80 chars). |
| `--threshold` | float | `0.95` | Taxa mínima de sucesso para considerar OK. |

**Saída (stdout).**

```
Total EPS:           125
  OK (MathML→LaTeX): 119
  SKIP (sem MathType): 4
  FAIL:              2
Taxa sobre MathType: 98.3%
Cache hits/misses:   0/119

Falhas:
  81_MF_Eqn073.eps: XML inválido: ...
```

**Exit codes.**

| Código | Significado |
|---|---|
| 0 | Taxa ≥ threshold. |
| 1 | Pasta inexistente, sem `.eps`, ou taxa abaixo do threshold. |

**Notas.**
- Conta **3 categorias**: OK (MathML extraído e convertido), SKIP (EPS sem marcador `%MathType` — é ilustração vetorial, não falha), FAIL (extração ou conversão falhou).
- A taxa é calculada sobre `OK + FAIL` (excluindo SKIPs), porque SKIPs são esperados e legítimos.
- Usa o mesmo `EquationConverter` do pipeline, sem cache em disco — o `cache_hits` reflete apenas hits em memória durante esta execução.

## Próximo

[testing.md](testing.md) — como rodar os testes.
