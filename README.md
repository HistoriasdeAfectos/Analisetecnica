# Analisetecnica

Software de análise de técnica corporal por vídeo e fotografia, multidesporto.

Compara a execução técnica de um atleta com bandas de referência de elite ou com
o seu próprio histórico, extrai métricas biomecânicas a partir de deteção de pose
e gera relatórios de evolução.

**Estado:** fase de desenho. Ainda sem implementação.

## Documentação

- [Arquitectura](docs/ARCHITECTURE.md) — abstracções centrais, pipeline, modelo
  de pontuação e de dados
- [Protocolo de captura](docs/CAPTURE.md) — definições de câmara, calibração,
  multicâmara

## Desportos

| Desporto | Perfil | Maturidade alvo |
|---|---|---|
| Ciclismo | [ciclismo.md](docs/sports/ciclismo.md) | `stable` |
| Atletismo — corrida | [atletismo-corrida.md](docs/sports/atletismo-corrida.md) | `stable` |
| Tiro com arco olímpico | [tiro-com-arco.md](docs/sports/tiro-com-arco.md) | `beta` |
| Natação | [natacao.md](docs/sports/natacao.md) | `beta` |
| Lançamentos | [lancamentos.md](docs/sports/lancamentos.md) | `experimental` |

Acrescentar um desporto é escrever um perfil, não alterar o pipeline.
